"""Offline checks; synthetic execution never proves model/network access."""
import json
import time
import unittest
from unittest.mock import patch

from test_tasks import trip_data, research_data, budget_data, itinerary_data
from travel_planner.models import TripInput
from travel_planner.crew import create_crew
from travel_planner.runner import RunResult, RequestBudget, supervise


def sleepy_worker(connection, data, limit):
    connection.send({"kind": "partial", "task": "research", "result": research_data()})
    connection.send({"kind": "event", "event": {"type": "task_started", "task": "budget"}})
    time.sleep(30)


def successful_worker(connection, data, limit):
    for name, fixture in [("research", research_data()), ("budget", budget_data()), ("itinerary", itinerary_data())]:
        connection.send(dict(kind="partial", task=name, result=fixture))
    connection.send(dict(kind="done", checks={"synthetic": True}))
    connection.close()


class CrewTests(unittest.TestCase):
    def test_existing_models_serialize_in_crewai_execution_storage(self):
        from crewai.utilities.crew_json_encoder import CrewJSONEncoder
        from travel_planner.models import ResearchResult
        data = research_data()
        data["places"][0]["description"]["sources"] = ["https://example.com/"]
        encoded = json.dumps(ResearchResult(**data), cls=CrewJSONEncoder)
        self.assertIn("https://example.com/", encoded)

    def factory(self):
        from travel_planner.llm import create_llm
        from travel_planner.settings import Settings
        with patch("socket.socket.connect", side_effect=AssertionError("No network")):
            llm = create_llm(Settings("openai", "provider/model-id", "test", "https://api.example.com/v1"))
            crew = create_crew(TripInput(**trip_data()), llm=llm)
        return crew

    def test_factory_identity_order_and_no_network(self):
        from crewai import Process
        crew = self.factory()
        self.assertEqual(crew.process, Process.sequential)
        self.assertEqual([task.name for task in crew.tasks], ["research", "budget", "itinerary"])
        self.assertEqual(len(crew.agents), 3)
        for task, agent in zip(crew.tasks, crew.agents): self.assertIs(task.agent, agent)
        self.assertEqual(crew.tasks[0].context, [])
        self.assertIs(crew.tasks[1].context[0], crew.tasks[0])
        self.assertIs(crew.tasks[2].context[0], crew.tasks[0])
        self.assertIs(crew.tasks[2].context[1], crew.tasks[1])
        self.assertFalse(crew.memory)
        self.assertFalse(crew.planning)
        self.assertIsNone(crew.manager_agent)
        self.assertFalse(crew.cache)

    def test_real_sequential_engine_with_synthetic_agent_answers(self):
        from crewai import Agent
        crew = self.factory()
        seen = []
        fixtures = [research_data(), budget_data(), itinerary_data()]
        def fake_execute(agent, task, context=None, tools=None):
            seen.append((task.name, context))
            return json.dumps(fixtures[len(seen) - 1])
        # asyncio on Windows uses a local socketpair; block outbound SDK HTTP instead.
        with patch.object(Agent, "execute_task", fake_execute), patch("httpx.Client.send", side_effect=AssertionError("No HTTP")):
            result = crew.kickoff()
        self.assertEqual([key for key, _ in seen], ["research", "budget", "itinerary"])
        self.assertIn(crew.tasks[0].output.raw, seen[1][1])
        self.assertIn(crew.tasks[0].output.raw, seen[2][1])
        self.assertIn(crew.tasks[1].output.raw, seen[2][1])
        self.assertEqual(len(result.tasks_output), 3)
        self.assertEqual(result.pydantic.known_total, crew.tasks[1].output.pydantic.known_total)
        self.assertIn('"selected_place_ids": ["p1"]', crew.tasks[2].expected_output)
        self.assertIn('"known_total": "0.40"', crew.tasks[2].expected_output)

    def test_incomplete_exact_budget_projection_remains_undetermined(self):
        from crewai import Agent
        from travel_planner.llm import create_llm
        from travel_planner.settings import Settings
        data = trip_data(); data["budget"] = "0.40"
        llm = create_llm(Settings("openai", "provider/model-id", "test", "https://api.example.com/v1"))
        crew = create_crew(TripInput(**data), llm=llm)
        costs = budget_data(); costs["complete"] = False
        route = itinerary_data(); route.update(complete=False, budget_status="undetermined")
        fixtures = iter([research_data(), costs, route])
        def fake_execute(agent, task, context=None, tools=None): return json.dumps(next(fixtures))
        with patch.object(Agent, "execute_task", fake_execute): crew.kickoff()
        self.assertIn('"budget_status": "undetermined"', crew.tasks[2].expected_output)

    def test_spawn_start_failure_is_safe_and_closes_channels(self):
        from unittest.mock import MagicMock
        context = MagicMock()
        parent, child = context.Pipe.return_value = (MagicMock(), MagicMock())
        process = context.Process.return_value
        process.start.side_effect = OSError('PRIVATE SDK exception')
        process.is_alive.return_value = False
        with patch('travel_planner.runner.multiprocessing.get_context', return_value=context):
            result = supervise(TripInput(**trip_data()), timeout=1)
        self.assertEqual(result.status, 'failed')
        self.assertEqual(result.error, 'supervisor_failed')
        self.assertTrue(result.worker_stopped)
        parent.close.assert_called_once()
        child.close.assert_called_once()

    def test_request_budget_and_deadline(self):
        from travel_planner.runner import LimitReached
        budget = RequestBudget(1, time.monotonic() + 20)
        budget.claim()
        with self.assertRaises(LimitReached): budget.claim()
        self.assertEqual(budget.calls, 1)
        with self.assertRaises(LimitReached): RequestBudget(2, time.monotonic() - 1).claim()

    def test_hard_timeout_preserves_partial_and_reaps_worker(self):
        result = supervise(TripInput(**trip_data()), timeout=2, max_llm_calls=1, worker=sleepy_worker)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "timeout")
        self.assertIsNone(result.final)
        self.assertIn("research", result.tasks)
        self.assertTrue(result.worker_stopped)
        self.assertEqual(result.events[-1]["type"], "run_failed")

    def test_raising_observer_preserves_partial_and_stops_worker(self):
        def broken(event): raise OSError("Do not expose this message")
        result = supervise(TripInput(**trip_data()), timeout=3, worker=sleepy_worker, on_event=broken)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "observer_failed")
        self.assertIn("research", result.tasks)
        self.assertTrue(result.worker_stopped)
        self.assertNotIn("Do not expose", json.dumps(result.as_dict()))

    def test_blocking_observer_cannot_defeat_timeout(self):
        def slow(event): time.sleep(10)
        before = time.monotonic()
        result = supervise(TripInput(**trip_data()), timeout=2, worker=sleepy_worker, on_event=slow)
        self.assertEqual(result.error, "timeout")
        self.assertTrue(result.worker_stopped)
        self.assertLess(time.monotonic() - before, 5)

    def test_export_money_and_no_overwrite(self):
        import tempfile
        from pathlib import Path
        from travel_planner.runner import write_result
        from travel_planner.models import ItineraryResult
        result = RunResult(status="success", final=ItineraryResult(**itinerary_data()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            write_result(result, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["final"]["known_total"], "0.40")
            with self.assertRaises(FileExistsError): write_result(result, path)

    def test_cli_existing_result_and_journal_collision(self):
        import tempfile
        from pathlib import Path
        from scripts.run_trip import main
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.json"
            output_path = Path(directory) / "result.json"
            input_path.write_text(json.dumps(trip_data()), encoding="utf-8")
            output_path.with_suffix(".events.jsonl").write_text("old journal", encoding="utf-8")
            argv = ["run_trip", str(input_path), "--output", str(output_path)]
            with patch("sys.argv", argv), patch("scripts.run_trip.run_trip") as run:
                self.assertEqual(main(), 2)
                run.assert_not_called()
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["status"], "failed")
            old = output_path.read_bytes()
            with patch("sys.argv", argv), patch("scripts.run_trip.run_trip") as run:
                self.assertEqual(main(), 2)
                run.assert_not_called()
            self.assertEqual(output_path.read_bytes(), old)

    def test_supervisor_success_and_limit_validation(self):
        result = supervise(TripInput(**trip_data()), timeout=10, worker=successful_worker)
        self.assertEqual(result.status, "success", result.as_dict())
        self.assertTrue(result.worker_stopped)
        self.assertIs(result.final, result.tasks["itinerary"])
        for kwargs in [dict(timeout=0), dict(timeout=901), dict(max_llm_calls=0), dict(max_llm_calls=True)]:
            with self.assertRaises(ValueError): supervise(TripInput(**trip_data()), **kwargs)

    def test_evidence_rejects_unobserved_tool_claims(self):
        from crewai import Agent
        from travel_planner.runner import verify_execution
        crew = self.factory()
        fixtures = iter([research_data(), budget_data(), itinerary_data()])
        def fake_execute(agent, task, context=None, tools=None): return json.dumps(next(fixtures))
        with patch.object(Agent, "execute_task", fake_execute): output = crew.kickoff()
        records = [dict(type="task_started", task=key) for key in ("research", "budget", "itinerary")]
        records += [dict(type="task_completed", task=key) for key in ("research", "budget", "itinerary")]
        records += [dict(type="llm_request", task="budget", context_received={"research": True}),
                    dict(type="llm_request", task="itinerary", context_received={"research": True, "budget": True})]
        with self.assertRaises(ValueError): verify_execution(crew, output, records)
