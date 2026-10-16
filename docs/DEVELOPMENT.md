# Руководство разработчика

Установка, переменные окружения и запуск: [README](../README.md).
Контракты и ограничения: [техническая спецификация](../SPEC.md).

## Основные модули

| Модуль | Назначение |
|---|---|
| src/travel_planner/api.py | HTTP-контракты, CORS и lifecycle |
| src/travel_planner/api_jobs.py | Реестр поездок, занятость и хранение состояния |
| src/travel_planner/runner.py | Процесс исполнения, события, дедлайн и остановка |
| src/travel_planner/crew.py | Сборка последовательной команды |
| src/travel_planner/tasks.py | Задачи, контекст и guardrail |
| src/travel_planner/structured_task.py | Контролируемая обработка структурированного ответа |
| src/travel_planner/planning.py | Проверки качества и распределения программы |
| frontend/src/api.ts | HTTP-запросы и обработка ошибок |
| frontend/src/useTrip.ts | Последовательный polling и cleanup |

## Проверки

Из корня проекта, без обращения к платным сервисам:

```powershell
$env:CREWAI_STORAGE_DIR = Join-Path (Get-Location) '.crewai'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B -m pip check
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```

Сборка включает TypeScript. Тестовые ответы проверяют обработку состояний и ошибок,
но не доказывают доступность внешних сервисов.

## Диагностика

CLI сохраняет JSON результата и соседний events.jsonl; API — отчёты в results/api/.
Локальные журналы Windows launcher находятся в .launcher/ и исключены из Git.
Существующие результаты не перезаписываются. Неудачный запуск не является маршрутом.
Не публикуйте ключи, заголовки авторизации и сырые сообщения SDK.

При изменении контрактов обновляйте серверные модели, клиентские типы и связанные тесты.
Прерывание ожидания запроса не равнозначно остановке Crew: остановкой рабочего процесса
управляет runner. Уже отправленное обращение провайдер может завершить на своей стороне.
