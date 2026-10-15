"""Windows desktop entry point. Stdlib only; never installs or calls paid services."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import json
import msvcrt
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
RUNTIME = ROOT / '.launcher'
STATE = RUNTIME / 'state.json'
PYTHON = ROOT / '.venv/Scripts/python.exe'
URL = 'http://localhost:5173'
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
KERNEL = ctypes.WinDLL('kernel32', use_last_error=True)
KERNEL.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
KERNEL.OpenProcess.restype = w.HANDLE
KERNEL.CloseHandle.argtypes = [w.HANDLE]
KERNEL.GetProcessTimes.argtypes = [w.HANDLE, ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME)]
KERNEL.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]


class LaunchError(Exception):
    pass


def identity(pid):
    """Creation time prevents a stale PID from referring to an unrelated process."""
    handle = KERNEL.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        code = w.DWORD()
        times = [w.FILETIME() for _ in range(4)]
        if not KERNEL.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
            return None
        if not KERNEL.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        KERNEL.CloseHandle(handle)


def alive(state):
    return bool(state and identity(state['pid']) == state['created'])


def read_state():
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def write_state(state):
    temp = STATE.with_suffix('.tmp')
    temp.write_text(json.dumps(state), encoding='utf-8')
    temp.replace(STATE)


def ready():
    try:
        with HTTP.open('http://127.0.0.1:8000/health', timeout=2) as response:
            if json.load(response).get('status') != 'ok':
                return False
        with HTTP.open(URL, timeout=2) as response:
            html = response.read(100000).decode('utf-8')
            if response.status != 200 or '/src/main.tsx' not in html:
                return False
        with HTTP.open(URL + '/src/main.tsx', timeout=2) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def occupied(port):
    with socket.socket() as connection:
        connection.settimeout(.5)
        return connection.connect_ex(('127.0.0.1', port)) == 0


class Job:
    """Only this supervisor's children enter the kill-on-close Windows job."""
    def __init__(self):
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', w.DWORD), ('min_working', ctypes.c_size_t),
                        ('max_working', ctypes.c_size_t), ('active', w.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t),
                        ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        KERNEL.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        KERNEL.CreateJobObjectW.restype = w.HANDLE
        KERNEL.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        KERNEL.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.handle = KERNEL.CreateJobObjectW(None, None)
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle or not KERNEL.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise LaunchError('Windows не разрешила безопасное управление процессами приложения.')

    def add(self, process):
        if not KERNEL.AssignProcessToJobObject(self.handle, w.HANDLE(int(process._handle))):
            process.terminate()
            process.wait(timeout=5)
            raise LaunchError('Не удалось подключить процесс к безопасной остановке.')

    def close(self):
        if self.handle:
            KERNEL.CloseHandle(self.handle)
            self.handle = None


def api_host(stop):
    import uvicorn
    server = uvicorn.Server(uvicorn.Config('travel_planner.api:app', host='127.0.0.1', port=8000, workers=1))
    def watch():
        while not stop.exists():
            time.sleep(.2)
        server.should_exit = True
    threading.Thread(target=watch, daemon=True).start()
    server.run()


def supervise(token, node):
    stop = RUNTIME / (token + '.stop')
    state = dict(pid=os.getpid(), created=identity(os.getpid()), token=token, status='starting')
    write_state(state)
    processes = []
    job = None
    try:
        job = Job()
        env = os.environ.copy()
        env['API_CORS_ORIGIN'] = URL
        commands = [([str(PYTHON), '-B', str(SCRIPT), 'api', token], ROOT, 'api.log'),
                    ([node, str(ROOT / 'frontend/node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', '5173', '--strictPort'], ROOT / 'frontend', 'interface.log')]
        for command, cwd, log in commands:
            with (RUNTIME / log).open('wb') as output:
                process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                           stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            processes.append(process)
            job.add(process)
        state['children'] = [dict(pid=p.pid, created=identity(p.pid)) for p in processes]
        write_state(state)
        deadline = time.monotonic() + 90
        while not stop.exists():
            if any(p.poll() is not None for p in processes):
                raise LaunchError('Один из компонентов завершился. Подробности: .launcher\\api.log и interface.log.')
            if state['status'] == 'starting':
                if ready():
                    state['status'] = 'ready'
                    write_state(state)
                elif time.monotonic() > deadline:
                    raise LaunchError('Приложение не успело запуститься за 90 секунд. Попробуйте ещё раз.')
            time.sleep(.3)
    except Exception as error:
        state['error'] = str(error) if isinstance(error, LaunchError) else 'Не удалось запустить компоненты. Проверьте файлы журнала в папке .launcher.'
    finally:
        stop.touch()
        state['status'] = 'stopping'
        write_state(state)
        # API exits through Uvicorn lifespan, which cancels/joins the Crew worker.
        if processes:
            try:
                processes[0].wait(timeout=25)
            except subprocess.TimeoutExpired:
                pass
        if job:
            job.close()  # Node, esbuild and any remaining API descendants only.
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        state['status'] = 'error' if state.get('error') else 'stopped'
        write_state(state)


def start():
    state = read_state()
    if alive(state):
        if state['status'] == 'ready' and ready():
            print('Планировщик уже работает. Открываем его в браузере.')
            os.startfile(URL)
            return
        raise LaunchError('Планировщик ещё запускается или останавливается. Подождите немного и повторите.')
    for port in (8000, 5173):
        if occupied(port):
            raise LaunchError(f'Порт {port} занят другой программой или прежним ручным запуском. Закройте его окно и повторите. Посторонние процессы не остановлены.')
    if not (ROOT / 'frontend/node_modules/vite/bin/vite.js').is_file():
        raise LaunchError('Не найдены готовые компоненты интерфейса. Попросите настроить зависимости проекта один раз.')
    node = shutil.which('node.exe')
    if not node:
        candidate = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'nodejs/node.exe'
        node = str(candidate) if candidate.is_file() else None
    if not node:
        raise LaunchError('Не найден Node.js. Для этого проекта требуется установленный Node.js 26 или новее.')
    check = subprocess.run([node, '--version'], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if check.returncode or int(check.stdout.strip().lstrip('v').split('.')[0]) < 26:
        raise LaunchError('Для интерфейса требуется Node.js 26 или новее.')
    token = uuid.uuid4().hex
    print('Запускаем планировщик. Первое открытие может занять до полутора минут…', flush=True)
    with (RUNTIME / 'launcher.log').open('wb') as output:
        supervisor = subprocess.Popen([str(PYTHON), '-B', str(SCRIPT), 'supervise', token, node], cwd=ROOT,
                                      stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        state = read_state()
        if state and state.get('token') == token:
            if state['status'] == 'ready' and alive(state) and ready():
                print('Готово! Открываем планировщик в браузере. Для остановки нажмите «Остановить планировщик.cmd».')
                os.startfile(URL)
                return
            if state.get('error'):
                raise LaunchError(state['error'])
        if supervisor.poll() is not None:
            raise LaunchError('Не удалось запустить приложение. Подробности сохранены в папке .launcher.')
        time.sleep(.4)
    (RUNTIME / (token + '.stop')).touch()
    raise LaunchError('Время ожидания истекло. Приложение останавливается; попробуйте ещё раз через полминуты.')


def stop():
    state = read_state()
    if not alive(state):
        print('Планировщик уже остановлен. Посторонние программы не затронуты.')
        return
    print('Останавливаем планировщик. Текущая поездка будет прервана…', flush=True)
    (RUNTIME / (state['token'] + '.stop')).touch()
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if not alive(state):
            print('Планировщик остановлен. Вкладку браузера можно закрыть.')
            return
        time.sleep(.3)
    raise LaunchError('Остановка занимает больше времени. Подождите и повторите. Посторонние процессы не завершались.')


def main():
    os.chdir(ROOT)
    RUNTIME.mkdir(exist_ok=True)
    action = sys.argv[1]
    if action == 'api':
        api_host(RUNTIME / (sys.argv[2] + '.stop'))
        return
    if action == 'supervise':
        supervise(sys.argv[2], sys.argv[3])
        return
    # Serialize simultaneous double clicks, including start versus stop.
    with (RUNTIME / 'command.lock').open('a+b') as lock:
        lock.seek(0)
        lock.write(b'0')
        lock.flush()
        deadline = time.monotonic() + 110
        while True:
            try:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise LaunchError('Предыдущая команда ещё выполняется. Подождите немного.')
                time.sleep(.3)
        try:
            {'start': start, 'stop': stop}[action]()
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == '__main__':
    try:
        main()
    except LaunchError as error:
        print('\nНе удалось выполнить команду: ' + str(error), flush=True)
        sys.exit(1)
    except Exception:
        print('\nНе удалось выполнить команду. Проверьте доступ к папке проекта и журналы в .launcher.', flush=True)
        sys.exit(1)
