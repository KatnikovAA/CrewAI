@echo off
chcp 65001 >nul
setlocal
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" goto missing
"%~dp0.venv\Scripts\python.exe" -B "%~dp0scripts\desktop_launcher.py" start
if errorlevel 1 goto failed
exit /b 0
:missing
echo Не найдено настроенное окружение Python в папке проекта.
echo Попросите настроить проект один раз. Автоматическая переустановка не выполняется.
:failed
echo.
echo Нажмите любую клавишу, чтобы закрыть окно.
pause >nul
exit /b 1
