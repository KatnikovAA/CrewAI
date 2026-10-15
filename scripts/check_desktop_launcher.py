"""Real Windows CMD integration check; no trip submissions or paid calls."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('desktop_launcher', ROOT / 'scripts/desktop_launcher.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
report = {'success': False, 'checks': [], 'paid_requests': 0}


def cmd(name):
    # Explorer opens this same CMD entry point. Deliberately use an unrelated cwd.
    result = subprocess.run(['cmd.exe', '/d', '/c', str(ROOT / name)], cwd=tempfile.gettempdir(),
                            input='\n', capture_output=True, text=True, encoding='utf-8', timeout=115)
    return result.returncode, result.stdout + result.stderr


def check(condition, label):
    assert condition, label
    report['checks'].append(label)


unrelated = None
try:
    initial = launcher.read_state()
    check(launcher.alive(initial) and launcher.ready(), 'real API and Vite ready after CMD start from unrelated directory')
    code, output = cmd('Запустить планировщик.cmd')
    check(code == 0 and 'уже работает' in output, 'repeat CMD reuses running application')
    check(launcher.read_state() == initial, 'supervisor and child identities unchanged: no duplicate processes')
    unrelated = subprocess.Popen([str(launcher.PYTHON), '-B', '-c', 'import time; time.sleep(180)'],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
    code, output = cmd('Остановить планировщик.cmd')
    check(code == 0 and 'остановлен' in output, 'stop CMD completes successfully')
    check(not launcher.alive(initial), 'owned supervisor stopped')
    check(all(not launcher.alive(child) for child in initial['children']), 'owned API and Vite roots stopped')
    check(not launcher.occupied(8000) and not launcher.occupied(5173), 'both listener ports released')
    check(unrelated.poll() is None, 'unrelated Python process remains alive')
    log = (launcher.RUNTIME / 'api.log').read_text(encoding='utf-8')
    check('Application shutdown complete' in log, 'API lifespan shutdown completed gracefully')
    code, output = cmd('Остановить планировщик.cmd')
    check(code == 0 and 'уже остановлен' in output, 'repeat stop is safe')
    with socket.socket() as blocker:
        blocker.bind(('127.0.0.1', 8000))
        blocker.listen()
        code, output = cmd('Запустить планировщик.cmd')
        check(code == 1 and 'Порт 8000 занят' in output, 'occupied port produces clear Russian failure')
        check(launcher.occupied(8000), 'foreign listener untouched after failed start')
    # Two simultaneous Explorer-equivalent launches must serialize and reuse one app.
    commands = [subprocess.Popen(['cmd.exe', '/d', '/c', str(ROOT / 'Запустить планировщик.cmd')],
                                cwd=tempfile.gettempdir(), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT) for _ in range(2)]
    outputs = [process.communicate(timeout=115)[0].decode('utf-8') for process in commands]
    check(all(process.returncode == 0 for process in commands), 'two simultaneous CMD starts both succeed')
    check(sum('уже работает' in text for text in outputs) == 1, 'simultaneous starts create one application only')
    check(launcher.ready() and launcher.alive(launcher.read_state()), 'final application left running and ready')
    check(unrelated.poll() is None, 'unrelated process survives all launcher operations')
    report['state'] = launcher.read_state()
    report['success'] = True
finally:
    if unrelated:
        unrelated.terminate()  # Our explicitly created test process only.
        unrelated.wait(timeout=5)
    destination = ROOT / 'results/desktop-launcher-check.json'
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
