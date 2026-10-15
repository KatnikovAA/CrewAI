"""Bounded in-memory HTTP job registry around the stage-5 process supervisor."""
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import traceback
from uuid import uuid4

from travel_planner.runner import RunResult, run_trip, write_result
from travel_planner.settings import PROJECT_ROOT


def now():
    return datetime.now(timezone.utc).isoformat()


ERRORS = {
    'timeout': 'Превышено время выполнения. Исполнитель остановлен.',
    'cancelled': 'Запуск остановлен при завершении сервера.',
    'llm_request_limit': 'Достигнут лимит обращений к модели.',
    'storage_failed': 'Не удалось сохранить результат на сервере.',
    'execution_failed': 'Команда не завершила проверенный маршрут.',
    'worker_failed': 'Исполнитель завершился без результата.',
    'observer_failed': 'Не удалось обработать события исполнения.',
    'supervisor_failed': 'Ошибка контроля исполнения.',
}
TASKS = {'research', 'budget', 'itinerary'}
TOOLS = {'internet_search', 'website_reader', 'trip_cost_calculator'}
EVENTS = {'run_started', 'run_completed', 'run_failed', 'task_started',
          'task_completed', 'task_failed', 'tool_started', 'tool_completed',
          'llm_request', 'llm_response', 'validation_failed'}


def safe_error(code):
    code = code if code in ERRORS else 'execution_failed'
    return {'code': code, 'message': ERRORS[code]}


class BusyError(Exception):
    pass


class ClosingError(Exception):
    pass


class TripManager:
    def __init__(self, *, executor=run_trip, result_dir=None, timeout=420, max_llm_calls=24):
        self.executor = executor
        self.result_dir = Path(result_dir) if result_dir is not None else PROJECT_ROOT / 'results' / 'api'
        self.timeout, self.max_llm_calls = timeout, max_llm_calls
        self.lock = threading.RLock()
        self.records = {}
        self.active = None
        self.thread = None
        self.cancel = threading.Event()
        self.closing = False

    def submit(self, trip):
        with self.lock:
            if self.closing:
                raise ClosingError()
            if self.active is not None:
                raise BusyError()
            trip_id = uuid4().hex
            record = dict(trip_id=trip_id, status='queued', current_task=None,
                          created_at=now(), started_at=None, finished_at=None,
                          events=deque(maxlen=500), events_total=0, error=None, result=None)
            self.records[trip_id] = record
            self.active = trip_id
            self.cancel = threading.Event()
            self._event(trip_id, {'type': 'queued'})
            self.thread = threading.Thread(target=self._execute, args=(trip_id, trip, self.cancel),
                                           name='trip-supervisor')
            try:
                self.thread.start()
            except Exception:
                self.records.pop(trip_id)
                self.active = None
                self.thread = None
                raise ClosingError() from None
            return trip_id

    def _event(self, trip_id, event):
        """Allowlist only. Never forward paths, SDK errors, prompts, URLs or headers."""
        kind = event.get('type')
        if kind not in EVENTS | {'queued'}:
            return
        with self.lock:
            record = self.records[trip_id]
            if record['status'] in ('completed', 'failed'):
                return
            if kind in ('run_completed', 'run_failed') and record['events'] and record['events'][-1]['type'] == kind:
                return
            record['events_total'] += 1
            public = dict(seq=record['events_total'], timestamp=now(), type=kind,
                          task=event.get('task') if event.get('task') in TASKS else None)
            if kind == 'task_started':
                record['current_task'] = public['task']
            elif kind in ('task_completed', 'task_failed') and record['current_task'] == public['task']:
                record['current_task'] = None
            if event.get('tool') in TOOLS:
                public['tool'] = event['tool']
            if event.get('status') in ('ok', 'empty', 'error'):
                public['status'] = event['status']
            if type(event.get('from_cache')) is bool:
                public['from_cache'] = event['from_cache']
            record['events'].append(public)

    def _execute(self, trip_id, trip, cancel):
        error = None
        output = None
        stopped = True
        with self.lock:
            record = self.records[trip_id]
            record.update(status='running', started_at=now())
        try:
            self.result_dir.mkdir(parents=True, exist_ok=True)
            journal_path = self.result_dir / (trip_id + '.events.jsonl')
            with journal_path.open('x', encoding='utf-8') as journal, (self.result_dir / (trip_id + '.diagnostics.jsonl')).open('x', encoding='utf-8') as diagnostics:
                diagnostic_lock = threading.Lock()
                def diagnose(event):
                    # Worker events are already redacted. Keep a diagnostic allowlist;
                    # never persist prompts, raw output, rejected values or SDK messages.
                    fields = {'type', 'task', 'issues', 'reason', 'fenced', 'raw_chars',
                              'raw_json_valid', 'pydantic_present', 'json_error_line',
                              'json_error_column', 'json_error_position', 'error',
                              'error_type', 'causes', 'frames', 'http_status',
                              'finish_reason', 'completion_tokens', 'tool', 'status',
                              'from_cache', 'number'}
                    entry = {key: value for key, value in event.items() if key in fields}
                    entry.update(trip_id=trip_id, timestamp=event.get('timestamp') or now())
                    with diagnostic_lock:
                        diagnostics.write(json.dumps(entry, ensure_ascii=False) + '\n')
                        diagnostics.flush()
                def observe(event):
                    diagnose(event)
                    self._event(trip_id, event)
                diagnose(dict(type='run_started'))
                try:
                    result = self.executor(trip, on_event=observe, cancel_event=cancel,
                                           timeout=self.timeout, max_llm_calls=self.max_llm_calls)
                    stopped = result.worker_stopped
                    if cancel.is_set():
                        error = 'cancelled'
                    elif result.status == 'success' and result.final is not None and stopped:
                        data = result.as_dict()
                        output = dict(trip_id=trip_id, final=data['final'], tasks=data['tasks'])
                    else:
                        error = result.error or 'worker_failed'
                    write_result(result, self.result_dir / (trip_id + '.json'))
                except Exception as exc:
                    error = 'storage_failed' if isinstance(exc, OSError) else 'execution_failed'
                    diagnose(dict(type='execution_exception', error_type=type(exc).__name__,
                                  frames=[dict(file=Path(f.filename).name, line=f.lineno, function=f.name)
                                          for f in traceback.extract_tb(exc.__traceback__)[-8:]]))
                    raise
                finally:
                    diagnose(dict(type='run_failed' if error else 'run_completed',
                                  error=error, task=record.get('current_task')))
                    # Disk journal is a bounded safe snapshot. Full internal events are in the report.
                    with self.lock:
                        entries = list(record['events'])
                    for entry in entries:
                        journal.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except OSError:
            error = 'storage_failed'
        except Exception:
            error = 'execution_failed'
        finally:
            if error and error != 'storage_failed':
                path = self.result_dir / (trip_id + '.json')
                try:
                    write_result(RunResult(status='failed', trip=trip,
                                           error=safe_error(error)['code']), path)
                except FileExistsError:
                    pass
                except OSError:
                    error = 'storage_failed'
            with self.lock:
                error = safe_error(error) if error else None
                self._event(trip_id, {'type': 'run_failed' if error else 'run_completed'})
                record.update(status='failed' if error else 'completed', error=error,
                              result=None if error else output, finished_at=now(), current_task=None)
                if not stopped:
                    # Never accept a second worker if termination could not be established.
                    self.closing = True
                self.active = None
                completed = [key for key, value in self.records.items()
                             if value['status'] in ('completed', 'failed')]
                for key in completed[:-20]:
                    del self.records[key]

    def get(self, trip_id):
        with self.lock:
            record = self.records.get(trip_id)
            if record is None:
                return None
            return {**{key: value for key, value in record.items() if key not in ('result', 'events')},
                    'events': [dict(event) for event in record['events']]}

    def result(self, trip_id):
        with self.lock:
            record = self.records.get(trip_id)
            return record['result'] if record else None

    def get_with_result(self, trip_id):
        # A completed record may be evicted by a different supervisor thread.
        # Keep state and result lookup in one critical section.
        with self.lock:
            return self.get(trip_id), self.result(trip_id)

    def close(self):
        with self.lock:
            self.closing = True
            self.cancel.set()
            thread = self.thread
        if thread is not None:
            thread.join(timeout=15)
            if thread.is_alive():
                raise RuntimeError('Executor shutdown incomplete')
