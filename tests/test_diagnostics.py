"""Offline diagnostics: no LLM calls."""
import json
from pathlib import Path
import threading
from tempfile import TemporaryDirectory
import unittest
from pydantic import ValidationError
from test_tasks import budget_data, trip_data
from travel_planner.models import BudgetResult, TripInput
from travel_planner.runner import RunResult
from travel_planner.api_jobs import TripManager


class DiagnosticsTests(unittest.TestCase):
    def test_validation_retains_explanation_without_input(self):
        from travel_planner.runner import validation_issues
        data = budget_data()
        data['logistics'][0].update(kind='unknown', text='PRIVATE INPUT')
        try:
            BudgetResult.model_validate(data)
        except ValidationError as error:
            issues = validation_issues(error)
        self.assertEqual(issues[0]['location'], ['logistics', 0])
        self.assertIn('unknown требует null', issues[0]['message'])
        self.assertNotIn('PRIVATE INPUT', json.dumps(issues))
        self.assertEqual(set(issues[0]), {'location', 'code', 'message'})

    def test_diagnostics_flushed_while_running_and_private_to_server(self):
        ready, release = threading.Event(), threading.Event()
        def execute(trip, *, on_event, **kwargs):
            on_event(dict(type='validation_failed', task='budget', reason='Schema mismatch',
                          issues=[dict(location=['logistics', 1], code='value_error', message='unknown requires null')]))
            ready.set()
            release.wait(5)
            return RunResult(status='failed', trip=trip, error='execution_failed')
        with TemporaryDirectory() as directory:
            manager = TripManager(executor=execute, result_dir=directory)
            try:
                trip_id = manager.submit(TripInput(**trip_data()))
                self.assertTrue(ready.wait(3))
                path = Path(directory) / (trip_id + '.diagnostics.jsonl')
                self.assertTrue(path.exists())
                entries = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
                entry = next(e for e in entries if e['type'] == 'validation_failed')
                self.assertEqual(entry['trip_id'], trip_id)
                self.assertEqual(entry['issues'][0]['message'], 'unknown requires null')
                self.assertTrue(entry['timestamp'])
                self.assertNotIn('issues', str(manager.get(trip_id)))
            finally:
                release.set()
                manager.close()
            entries = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(entries[-1]['type'], 'run_failed')

    def test_executor_exception_keeps_stack_without_sdk_message(self):
        def broken(*args, **kwargs):
            raise RuntimeError('Authorization: Bearer PRIVATE_SECRET')
        with TemporaryDirectory() as directory:
            manager = TripManager(executor=broken, result_dir=directory)
            trip_id = manager.submit(TripInput(**trip_data()))
            manager.thread.join(3)
            manager.close()
            raw = (Path(directory) / (trip_id + '.diagnostics.jsonl')).read_text(encoding='utf-8')
            entries = [json.loads(line) for line in raw.splitlines()]
            failure = next(e for e in entries if e['type'] == 'execution_exception')
            self.assertEqual(failure['error_type'], 'RuntimeError')
            self.assertTrue(failure['frames'])
            self.assertNotIn('PRIVATE_SECRET', raw)
            self.assertEqual(entries[-1]['type'], 'run_failed')
