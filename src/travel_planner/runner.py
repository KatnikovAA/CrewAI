"""Переиспользуемый запуск в отдельном процессе, безопасные события и результат."""
import ast
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
import multiprocessing
import os
from pathlib import Path
import queue
import threading
import time
import traceback

from travel_planner.models import TripInput, ResearchResult, BudgetResult, ItineraryResult

SCHEMAS = {"research": ResearchResult, "budget": BudgetResult, "itinerary": ItineraryResult}


class LimitReached(BaseException):
    """A deliberate stop that SDK/converter Exception retries must not swallow."""


class RequestBudget:
    def __init__(self, limit, deadline=float("inf")):
        self.limit, self.deadline, self.calls = limit, deadline, 0
        self.lock = threading.Lock()

    def claim(self):
        with self.lock:
            if self.calls >= self.limit or time.monotonic() >= self.deadline:
                raise LimitReached()
            self.calls += 1
            return self.calls


class _Notifier:
    """Observer code never runs on the process-deadline supervisor thread."""
    def __init__(self, callback):
        self.callback = callback
        self.queue = queue.SimpleQueue()
        self.failed = threading.Event()
        self.thread = None
        if callback:
            self.thread = threading.Thread(target=self._deliver, daemon=True, name="travel-events")
            self.thread.start()

    def _deliver(self):
        while True:
            entry = self.queue.get()
            if entry is None:
                return
            try:
                self.callback(entry)
            except BaseException:
                self.failed.set()
                return

    def put(self, entry):
        if self.thread and not self.failed.is_set():
            self.queue.put(entry)

    def finish(self):
        if self.thread:
            self.queue.put(None)
            self.thread.join(timeout=0.5)
            if self.thread.is_alive():
                self.failed.set()


@dataclass
class RunResult:
    status: str
    trip: TripInput | None = None
    final: ItineraryResult | None = None
    tasks: dict = field(default_factory=dict)
    rejected: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)
    error: str | None = None
    worker_stopped: bool = True

    def as_dict(self):
        return dict(status=self.status, trip=self.trip.model_dump(mode="json") if self.trip else None,
                    final=self.final.model_dump(mode="json") if self.final else None,
                    tasks={key: value.model_dump(mode="json") for key, value in self.tasks.items()},
                    rejected={key: value.model_dump(mode="json") for key, value in self.rejected.items()},
                    events=self.events, checks=self.checks, error=self.error, worker_stopped=self.worker_stopped)


def write_result(result: RunResult, path):
    """Exclusive creation; an existing result is never silently replaced."""
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(result.as_dict(), stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _mapping(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            try:
                result = ast.literal_eval(value)
                return result if isinstance(result, dict) else {}
            except (ValueError, SyntaxError):
                pass
    return {}


def _worker(connection, data, max_llm_calls):
    """Only this disposable process imports/runs CrewAI and owns SDK threads."""
    from travel_planner.runtime import configure_runtime
    configure_runtime()
    logging.disable(logging.CRITICAL)
    # Never send SDK stdout/stderr, chain-of-thought, request headers or page text.
    with open(os.devnull, "w", encoding="utf-8") as quiet:
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            _worker_inner(connection, data, max_llm_calls)


def _worker_inner(connection, data, max_llm_calls):
    from travel_planner.crew import create_crew
    from travel_planner.llm import create_llm
    from travel_planner.settings import load_settings
    from crewai.events import crewai_event_bus
    from crewai.events.types.task_events import TaskStartedEvent, TaskFailedEvent
    from crewai.events.types.tool_usage_events import ToolUsageStartedEvent, ToolUsageFinishedEvent, ToolUsageErrorEvent
    from crewai.llms.hooks.base import BaseInterceptor

    lock = threading.RLock()
    records = []
    crew = None
    secrets = []
    counter = RequestBudget(max_llm_calls)

    def send(message):
        encoded = json.dumps(message, ensure_ascii=False)
        for secret in secrets:
            if secret:
                encoded = encoded.replace(secret, "[redacted]")
        with lock:
            connection.send(json.loads(encoded))

    def emit(type_, task=None, **details):
        event = dict(type=type_, task=task, timestamp=datetime.now(timezone.utc).isoformat(), **details)
        with lock:
            records.append(event)
            send(dict(kind="event", event=event))

    def completed(output):
        task = next(task for task in crew.tasks if task.output is output)
        model = SCHEMAS[task.name].model_validate(output.pydantic.model_dump())
        send(dict(kind="partial", task=task.name, result=model.model_dump(mode="json")))
        emit("task_completed", task.name)

    class Interceptor(BaseInterceptor):
        def on_outbound(self, request):
            number = counter.claim()  # Counts every HTTP attempt, including converter/fallback requests.
            payload = json.loads(request.content)
            messages = payload.get("messages", payload.get("input", []))
            contents = "\n".join(str(message.get("content", "")) for message in messages if isinstance(message, dict))
            task = next((task for task in crew.tasks if task.description in contents), None)
            received = {dep.name: bool(dep.output and dep.output.raw and dep.output.raw in contents)
                        for dep in task.context} if task else {}
            emit("llm_request", task.name if task else None, number=number, context_received=received)
            return request

        def on_inbound(self, response):
            response.read()
            try:
                body = response.json()
                choices = body.get("choices", [])
                reason = choices[0].get("finish_reason") if choices else None
                usage = body.get("usage", {})
                emit("llm_response", http_status=response.status_code,
                     finish_reason=reason if reason in ("stop", "length", "tool_calls", "content_filter") else None,
                     completion_tokens=usage.get("completion_tokens"))
            except (ValueError, AttributeError, TypeError):
                emit("llm_response", http_status=response.status_code)
            return response

        async def aon_outbound(self, request):
            return self.on_outbound(request)

        async def aon_inbound(self, response):
            await response.aread()
            return self.on_inbound(response)

    registered = []
    try:
        settings = load_settings()
        secrets.extend([settings.api_key, os.getenv("TAVILY_API_KEY", "")])
        trip = TripInput.model_validate(data)
        llm = create_llm(settings, interceptor=Interceptor(), max_tokens=6000, timeout=60)
        crew = create_crew(trip, llm=llm, task_callback=completed)
        task_ids = {str(task.id): task.name for task in crew.tasks}

        def diagnostic_guard(task):
            original = task.guardrail
            def observed(output):
                result = original(output)
                if not result[0]:
                    from pydantic import ValidationError
                    issues = []
                    try:
                        candidate = task.output_pydantic.model_validate_json(output.raw)
                        send(dict(kind="rejected", task=task.name, result=candidate.model_dump(mode="json")))
                    except ValidationError as error:
                        issues = [dict(location=list(item["loc"]), code=item["type"]) for item in error.errors()[:12]]
                    emit("validation_failed", task.name, issues=issues,
                         reason=result[1], fenced=output.raw.lstrip().startswith("```"), raw_chars=len(output.raw))
                return result
            return observed

        for task in crew.tasks:
            task.guardrail = diagnostic_guard(task)
            task.ensure_guardrail_is_callable()  # 1.15.28 caches callable in a private attribute.

        def started(source, event):
            if event.task_id in task_ids:
                received = {dep.name: bool(dep.output and dep.output.raw in (event.context or ""))
                            for dep in event.task.context}
                emit("task_started", task_ids[event.task_id], context_received=received)

        def failed(source, event):
            if event.task_id in task_ids:
                emit("task_failed", task_ids[event.task_id], error="task_execution_failed")

        def tool_event(source, event):
            if event.task_id not in task_ids:
                return
            task = task_ids[event.task_id]
            if isinstance(event, ToolUsageStartedEvent):
                emit("tool_started", task, tool=event.tool_name)
            elif isinstance(event, ToolUsageErrorEvent):
                emit("tool_completed", task, tool=event.tool_name, status="error", from_cache=False)
            else:
                result = _mapping(event.output)
                details = {}
                if event.tool_name == "internet_search":
                    details["urls"] = [item["url"] for item in result.get("results", [])]
                elif event.tool_name == "website_reader":
                    details.update(source_url=result.get("source_url"), requested_url=result.get("requested_url"),
                                   text_length=len(result.get("text", "")))
                elif event.tool_name == "trip_cost_calculator":
                    details.update({key: result.get(key) for key in ("total", "currency", "budget", "over_budget")})
                    args = _mapping(event.tool_args)
                    details["amounts"] = [str(row.get("amount")) for row in args.get("expenses", [])]
                emit("tool_completed", task, tool=event.tool_name,
                     status=result.get("status", "error"), from_cache=event.from_cache, **details)

        for event_type, handler in [(TaskStartedEvent, started), (TaskFailedEvent, failed),
                                    (ToolUsageStartedEvent, tool_event), (ToolUsageFinishedEvent, tool_event),
                                    (ToolUsageErrorEvent, tool_event)]:
            crewai_event_bus.on(event_type)(handler)
            registered.append((event_type, handler))
        emit("run_started", max_llm_calls=max_llm_calls)
        output = crew.kickoff()
        if not crewai_event_bus.flush(timeout=5):
            raise ValueError("Event flush failed")
        checks = verify_execution(crew, output, records, trip)
        send(dict(kind="done", checks=checks))
    except LimitReached:
        emit("run_failed", error="llm_request_limit")
        send(dict(kind="failure", error="llm_request_limit"))
    except Exception as error:
        # Exception messages may contain raw SDK output or secrets. Keep only a fixed code.
        causes = []
        cause = error
        for _ in range(5):
            if cause is None:
                break
            causes.append(type(cause).__name__)
            cause = cause.__cause__ or cause.__context__
        frames = [dict(file=Path(frame.filename).name, line=frame.lineno, function=frame.name)
                  for frame in traceback.extract_tb(error.__traceback__)[-8:]]
        emit("run_failed", error="execution_failed", error_type=type(error).__name__, causes=causes, frames=frames)
        send(dict(kind="failure", error="execution_failed"))
    finally:
        crewai_event_bus.flush(timeout=5)
        for event_type, handler in registered:
            crewai_event_bus.off(event_type, handler)
        crewai_event_bus.shutdown(wait=True)  # Only the disposable worker, never factory/API parent.
        connection.close()


def verify_execution(crew, output, records, trip=None):
    """Strict evidence check: no tool claim is accepted without a real usage event."""
    if len(output.tasks_output) != 3:
        raise ValueError("Incomplete crew output")
    for task, result in zip(crew.tasks, output.tasks_output):
        if result is not task.output or not task.guardrail(result)[0]:
            raise ValueError("Task contract failed")
    started = [event["task"] for event in records if event["type"] == "task_started"]
    completed = [event["task"] for event in records if event["type"] == "task_completed"]
    expected = ["research", "budget", "itinerary"]
    if started != expected or completed != expected:
        raise ValueError("Task order mismatch")
    for key, dependencies in [("budget", {"research"}), ("itinerary", {"research", "budget"})]:
        sent = [event for event in records if event["type"] == "llm_request" and event["task"] == key]
        if not any(set(event["context_received"]) == dependencies and all(event["context_received"].values()) for event in sent):
            raise ValueError("Context delivery to model unproven")
    tools = [event for event in records if event["type"] == "tool_completed" and event["status"] == "ok"
             and not event["from_cache"]]
    for task, name in [("research", "internet_search"), ("research", "website_reader"),
                       ("budget", "trip_cost_calculator"), ("itinerary", "trip_cost_calculator")]:
        if not any(event["task"] == task and event["tool"] == name for event in tools):
            raise ValueError("Required tool call unproven")
    searched = {url.rstrip("/") for event in tools if event["task"] == "research"
                and event["tool"] == "internet_search" for url in event.get("urls", [])}
    if not any((event.get("requested_url") or event.get("source_url") or "").rstrip("/") in searched
               and event.get("text_length", 0) > 0 for event in tools
               if event["task"] == "research" and event["tool"] == "website_reader"):
        raise ValueError("Reading a search result unproven")
    costs = crew.tasks[1].output.pydantic
    amounts = sorted(item.amount for item in costs.expenses if item.amount is not None) or [Decimal(0)]
    for key in ("budget", "itinerary"):
        if not any(event["task"] == key and event["tool"] == "trip_cost_calculator"
                   and event.get("currency") == costs.currency and Decimal(event["total"]) == costs.known_total
                   and (trip is None or Decimal(event.get("budget") or "-1") == trip.budget)
                   and sorted(Decimal(value) for value in event["amounts"]) == amounts for event in tools):
            raise ValueError("Calculator input/output mismatch")
    return dict(task_order=True, context_sent_to_llm=True, required_tools=True,
                structured_results=True, contracts=True, calculator_amounts=True)


def supervise(trip: TripInput, *, timeout=420, max_llm_calls=24, on_event=None, worker=_worker):
    """Hard wall-clock deadline. On return, the worker is joined, with no live SDK thread."""
    trip = TripInput.model_validate(trip.model_dump())
    if isinstance(timeout, bool) or not 0 < timeout <= 900:
        raise ValueError("timeout must be within (0, 900]")
    if type(max_llm_calls) is not int or not 1 <= max_llm_calls <= 60:
        raise ValueError("max_llm_calls must be within [1, 60]")
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=worker, args=(child, trip.model_dump(mode="json"), max_llm_calls))
    result = RunResult(status="failed", trip=trip)
    deadline = time.monotonic() + timeout
    done = False
    notifier = _Notifier(on_event)

    def event(entry):
        result.events.append(entry)
        notifier.put(dict(entry))

    process.start()
    child.close()
    try:
        while time.monotonic() < deadline:
            if notifier.failed.is_set():
                result.error = "observer_failed"
                break
            try:
                ready = parent.poll(min(0.1, max(0, deadline - time.monotonic())))
            except (EOFError, BrokenPipeError):
                break
            if ready:
                try:
                    message = parent.recv()
                except (EOFError, OSError):
                    break
                if message["kind"] == "event":
                    event(message["event"])
                elif message["kind"] == "partial":
                    result.tasks[message["task"]] = SCHEMAS[message["task"]].model_validate(message["result"])
                elif message["kind"] == "rejected":
                    result.rejected[message["task"]] = SCHEMAS[message["task"]].model_validate(message["result"])
                elif message["kind"] == "done":
                    result.checks = message["checks"]
                    done = True
                elif message["kind"] == "failure":
                    result.error = message["error"]
            elif not process.is_alive():
                break
        else:
            result.error = "timeout"
    except KeyboardInterrupt:
        result.error = "cancelled"
    except Exception as error:
        event(dict(type="supervisor_error", task=None, error_type=type(error).__name__,
                   frames=[dict(file=Path(frame.filename).name, line=frame.lineno, function=frame.name)
                           for frame in traceback.extract_tb(error.__traceback__)[-4:]]))
        result.error = "supervisor_failed"
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        result.worker_stopped = not process.is_alive()
        parent.close()
    if done and result.worker_stopped and not result.error and set(result.tasks) == set(SCHEMAS):
        result.status, result.final = "success", result.tasks["itinerary"]
        event(dict(type="run_completed", task=None))
    else:
        result.error = result.error or "worker_failed"
        active = {entry.get("task") for entry in result.events if entry["type"] == "task_started"}
        ended = {entry.get("task") for entry in result.events if entry["type"] in ("task_completed", "task_failed")}
        for key in active - ended:
            event(dict(type="task_failed", task=key, error=result.error))
        event(dict(type="run_failed", task=None, error=result.error))
    notifier.finish()
    if notifier.failed.is_set():
        result.status, result.final = "failed", None
        result.error = result.error or "observer_failed"
        result.events.append(dict(type="run_failed", task=None, error=result.error))
    return result


def run_trip(trip: TripInput, *, on_event=None, timeout=420, max_llm_calls=24) -> RunResult:
    return supervise(trip, on_event=on_event, timeout=timeout, max_llm_calls=max_llm_calls)
