"""Offline HTTP tests. Controlled executors do not prove CrewAI connectivity."""
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import threading
import time
import unittest

from fastapi.testclient import TestClient
from test_tasks import trip_data, research_data, budget_data, itinerary_data
from test_crew import sleepy_worker
from travel_planner.models import TripInput, ResearchResult, BudgetResult, ItineraryResult
from travel_planner.runner import RunResult, supervise
from travel_planner.api import create_app
from travel_planner.api_jobs import TripManager


def success(trip, *, on_event, cancel_event, **limits):
    on_event({'type': 'task_started', 'task': 'research', 'frames': 'PRIVATE'})
    on_event({'type': 'tool_completed', 'task': 'research', 'tool': 'internet_search', 'status': 'ok', 'urls': ['PRIVATE']})
    tasks = {k: schema.model_validate(data()) for k, schema, data in [
        ('research', ResearchResult, research_data), ('budget', BudgetResult, budget_data),
        ('itinerary', ItineraryResult, itinerary_data)]}
    return RunResult(status='success', trip=trip, tasks=tasks, final=tasks['itinerary'])


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def manager(self, executor=success, **kwargs):
        return TripManager(executor=executor, result_dir=Path(self.temp.name), **kwargs)

    def wait(self, client, trip_id):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            data = client.get('/trips/' + trip_id).json()
            if data['status'] in ('completed', 'failed'):
                return data
            time.sleep(.02)
        self.fail('Execution did not finish')

    def test_health_validation_unknown_and_cors(self):
        with TestClient(create_app(manager=self.manager())) as client:
            self.assertEqual(client.get('/health').json(), {'status': 'ok', 'external_services': 'not_checked'})
            self.assertEqual(client.post('/trips', json={}).status_code, 422)
            bad = trip_data(); bad['budget'] = 1.25
            self.assertEqual(client.post('/trips', json=bad).status_code, 422)
            for suffix in ('', '/result'):
                self.assertEqual(client.get('/trips/unknown' + suffix).status_code, 404)
            response = client.options('/trips', headers={'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST'})
            self.assertEqual(response.headers['access-control-allow-origin'], 'http://localhost:5173')
            self.assertNotIn('access-control-allow-credentials', response.headers)
            response = client.options('/trips', headers={'Origin': 'https://other.example', 'Access-Control-Request-Method': 'POST'})
            self.assertNotIn('access-control-allow-origin', response.headers)
            self.assertEqual(client.get('/openapi.json').status_code, 200)

    def test_accepted_events_result_precision_and_file(self):
        with TestClient(create_app(manager=self.manager())) as client:
            response = client.post('/trips', json=trip_data())
            self.assertEqual(response.status_code, 202)
            accepted = response.json(); trip_id = accepted['trip_id']
            self.assertEqual(accepted['status_url'], '/trips/' + trip_id)
            state = self.wait(client, trip_id)
            self.assertEqual(state['status'], 'completed')
            self.assertTrue(all(state[k] for k in ('created_at', 'started_at', 'finished_at')))
            events = state['events']
            self.assertEqual([e['seq'] for e in events], list(range(1, len(events)+1)))
            self.assertNotIn('PRIVATE', str(events))
            result = client.get(accepted['result_url'])
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['final']['known_total'], '0.40')
            self.assertEqual(set(result.json()['tasks']), {'research', 'budget', 'itinerary'})
            self.assertNotIn('events', result.json())
            self.assertTrue((Path(self.temp.name) / (trip_id + '.json')).is_file())
            self.assertTrue((Path(self.temp.name) / (trip_id + '.events.jsonl')).is_file())

    def test_concurrent_creation_busy_and_shutdown(self):
        started = threading.Event()
        def blocked(trip, *, on_event, cancel_event, **limits):
            started.set()
            cancel_event.wait(10)
            return RunResult(status='failed', trip=trip, error='cancelled')
        manager = self.manager(blocked)
        with TestClient(create_app(manager=manager)) as client:
            with ThreadPoolExecutor(2) as pool:
                responses = list(pool.map(lambda _: client.post('/trips', json=trip_data()), range(2)))
            self.assertEqual(sorted(r.status_code for r in responses), [202, 409])
            trip_id = next(r.json()['trip_id'] for r in responses if r.status_code == 202)
            self.assertTrue(started.wait(2))
            self.assertEqual(client.get('/trips/' + trip_id).json()['status'], 'running')
            pending = client.get('/trips/' + trip_id + '/result')
            self.assertEqual(pending.status_code, 409)
            self.assertEqual(pending.json()['detail']['status'], 'running')
            self.assertEqual(client.get('/health').status_code, 200)
        self.assertEqual(manager.get(trip_id)['status'], 'failed')
        self.assertFalse(manager.thread.is_alive())
        self.assertEqual(manager.get(trip_id)['error']['code'], 'cancelled')

    def test_failure_safe_and_next_run_available(self):
        def broken(*args, **kwargs):
            raise RuntimeError('SDK SECRET C:/private Authorization: Bearer secret')
        manager = self.manager(broken)
        with TestClient(create_app(manager=manager)) as client:
            for _ in range(2):
                response = client.post('/trips', json=trip_data())
                self.assertEqual(response.status_code, 202)
                state = self.wait(client, response.json()['trip_id'])
                self.assertEqual(state['status'], 'failed')
                self.assertNotIn('SECRET', str(state))
                self.assertTrue((Path(self.temp.name) / (response.json()['trip_id'] + '.json')).is_file())
                result = client.get(response.json()['result_url'])
                self.assertEqual(result.status_code, 409)
                self.assertEqual(result.json()['detail']['status'], 'failed')

    def test_real_supervisor_timeout_and_shutdown_reap_process(self):
        executor = partial(supervise, worker=sleepy_worker)
        manager = self.manager(executor, timeout=.6)
        with TestClient(create_app(manager=manager)) as client:
            for _ in range(2):
                response = client.post('/trips', json=trip_data())
                state = self.wait(client, response.json()['trip_id'])
                self.assertEqual(state['error']['code'], 'timeout')
                import json
                saved = json.loads((Path(self.temp.name) / (response.json()['trip_id'] + '.json')).read_text(encoding='utf-8'))
                self.assertTrue(saved['worker_stopped'])
                self.assertEqual(state['status'], 'failed')
        manager = self.manager(executor, timeout=30)
        start = time.monotonic()
        with TestClient(create_app(manager=manager)) as client:
            response = client.post('/trips', json=trip_data())
            time.sleep(.2)
        self.assertLess(time.monotonic() - start, 8)
        self.assertFalse(manager.thread.is_alive())
        self.assertEqual(manager.get(response.json()['trip_id'])['error']['code'], 'cancelled')

    def test_bounded_history_events_and_no_active_eviction(self):
        def many(trip, **kwargs):
            for _ in range(520):
                kwargs['on_event']({'type': 'task_started', 'task': 'research'})
            return success(trip, **kwargs)
        manager = self.manager(many)
        with TestClient(create_app(manager=manager)) as client:
            ids = []
            for _ in range(22):
                response = client.post('/trips', json=trip_data())
                ids.append(response.json()['trip_id'])
                state = self.wait(client, ids[-1])
            self.assertEqual(client.get('/trips/' + ids[0]).status_code, 404)
            self.assertEqual(len(manager.records), 20)
            self.assertEqual(len(state['events']), 500)
            self.assertGreater(state['events'][0]['seq'], 1)
            self.assertEqual(state['events'][-1]['seq'], state['events_total'])

    def test_unconfirmed_worker_stop_rejects_next_run(self):
        def unsafe(trip, **kwargs):
            return RunResult(status='failed', trip=trip, worker_stopped=False)
        with TestClient(create_app(manager=self.manager(unsafe))) as client:
            response = client.post('/trips', json=trip_data())
            self.assertEqual(self.wait(client, response.json()['trip_id'])['status'], 'failed')
            self.assertEqual(client.post('/trips', json=trip_data()).status_code, 503)

    def test_cors_wildcard_is_rejected(self):
        with patch.dict('os.environ', {'API_CORS_ORIGIN': '*'}):
            with self.assertRaises(ValueError):
                create_app(manager=self.manager())

    def test_active_record_survives_history_limit(self):
        manager = self.manager()
        with TestClient(create_app(manager=manager)) as client:
            for _ in range(20):
                response = client.post('/trips', json=trip_data())
                self.wait(client, response.json()['trip_id'])
            def blocked(trip, *, cancel_event, **kwargs):
                cancel_event.wait(5)
                return RunResult(status='failed', trip=trip, error='cancelled')
            manager.executor = blocked
            response = client.post('/trips', json=trip_data())
            self.assertEqual(response.status_code, 202)
            self.assertEqual(len(manager.records), 21)
            self.assertEqual(client.get(response.json()['status_url']).status_code, 200)
        self.assertEqual(len(manager.records), 20)

    def test_unwritable_storage_fails_without_execution(self):
        called = []
        def counted(*args, **kwargs):
            called.append(True)
            return success(*args, **kwargs)
        manager = self.manager(counted)
        manager.result_dir = Path(self.temp.name) / 'file'
        manager.result_dir.write_text('occupied')
        with TestClient(create_app(manager=manager)) as client:
            response = client.post('/trips', json=trip_data())
            state = self.wait(client, response.json()['trip_id'])
            self.assertEqual(state['error']['code'], 'storage_failed')
            self.assertFalse(called)


if __name__ == '__main__':
    unittest.main()
