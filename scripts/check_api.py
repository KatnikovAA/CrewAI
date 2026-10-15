"""One real paid trip through a local Uvicorn HTTP server; no fixtures or retries."""
import json
from pathlib import Path
import socket
import threading
import time
from uuid import uuid4

import httpx
import uvicorn

from travel_planner.api import create_app, TripResultResponse
from travel_planner.models import TripInput
from travel_planner.settings import PROJECT_ROOT


def main():
    evidence_path = PROJECT_ROOT / 'results' / ('stage6-http-' + uuid4().hex[:12] + '.json')
    evidence = {'real_execution': True, 'health_samples': [], 'polls': []}
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.listen(128)
    server = uvicorn.Server(uvicorn.Config(create_app(), host='127.0.0.1', port=port,
                                           workers=1, log_level='warning', access_log=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, name='http-check-server')
    thread.start()
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=5, trust_env=False) as client:
            startup_deadline = time.monotonic() + 15
            while not server.started:
                if not thread.is_alive() or time.monotonic() > startup_deadline:
                    raise RuntimeError('server_start_failed')
                time.sleep(.05)
            assert client.get('/health').json()['external_services'] == 'not_checked'
            trip = TripInput.model_validate_json((PROJECT_ROOT / 'examples' / 'trip.json').read_text(encoding='utf-8-sig'))
            begin = time.monotonic()
            response = client.post('/trips', json=trip.model_dump(mode='json'))
            assert response.status_code == 202
            evidence['accepted'] = response.json()
            evidence['post_seconds'] = round(time.monotonic() - begin, 3)
            trip_id = response.json()['trip_id']
            print(json.dumps({'trip_id': trip_id, 'http': 202, 'post_seconds': evidence['post_seconds']}), flush=True)
            previous = None
            while time.monotonic() - begin < 450:
                response = client.get(f'/trips/{trip_id}')
                response.raise_for_status()
                state = response.json()
                snapshot = {key: state[key] for key in ('status', 'current_task', 'events_total')}
                evidence['polls'].append(snapshot)
                if snapshot != previous:
                    print(json.dumps(snapshot), flush=True)
                    previous = snapshot
                health_start = time.monotonic()
                health = client.get('/health')
                assert health.status_code == 200
                evidence['health_samples'].append({'status': state['status'], 'seconds': round(time.monotonic()-health_start, 4)})
                if state['status'] in ('completed', 'failed'):
                    break
                time.sleep(2)
            evidence['state'] = state
            response = client.get(f'/trips/{trip_id}/result')
            evidence['result_http_status'] = response.status_code
            if state['status'] != 'completed':
                print(json.dumps({'status': state['status'], 'error': state.get('error')}), flush=True)
                return 1
            assert response.status_code == 200
            model = TripResultResponse.model_validate(response.json())
            evidence['result'] = model.model_dump(mode='json')
            saved = json.loads((PROJECT_ROOT / 'results' / 'api' / (trip_id+'.json')).read_text(encoding='utf-8'))
            assert saved['status'] == 'success' and saved['worker_stopped'] and all(saved['checks'].values())
            assert response.json()['final'] == saved['final']
            assert model.final.known_total == model.tasks.budget.known_total
            assert [day.date.isoformat() for day in model.final.days] == [trip.start_date.isoformat(), trip.end_date.isoformat()]
            assert isinstance(response.json()['final']['known_total'], str)
            assert any(sample['status'] == 'running' for sample in evidence['health_samples'])
            evidence['checks'] = saved['checks']
            evidence['duration_seconds'] = round(time.monotonic()-begin, 2)
            print(json.dumps({'status': 'completed', 'duration_seconds': evidence['duration_seconds'],
                              'health_max_seconds': max(row['seconds'] for row in evidence['health_samples']),
                              'known_total': response.json()['final']['known_total']}), flush=True)
            return 0
    except Exception:
        evidence['check_error'] = 'http_integration_not_confirmed'
        print('HTTP integration not confirmed; see safe evidence file.', flush=True)
        return 1
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        sock.close()
        evidence['server_stopped'] = not thread.is_alive()
        with evidence_path.open('x', encoding='utf-8') as stream:
            json.dump(evidence, stream, ensure_ascii=False, indent=2)
        print('Evidence: ' + str(evidence_path), flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
