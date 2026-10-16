"""Один настоящий запрос через CrewAI LLM; запуск из установленного проекта."""

import contextlib
import io
import logging
import os
import sys

from travel_planner.settings import PROJECT_ROOT, load_settings


def main() -> int:
    # Читаемые русские сообщения в PowerShell и перенаправленном выводе Windows.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    settings = load_settings()
    missing = []
    if not settings.provider:
        missing.append("LLM_PROVIDER")
    if not settings.model:
        missing.append("LLM_MODEL")
    if not settings.api_key:
        missing.append("LLM_API_KEY (API-ключ)")
    if not settings.base_url:
        missing.append("LLM_BASE_URL (адрес API LLM-провайдер)")
    if missing:
        print("Заполните локальный .env: " + ", ".join(missing), file=sys.stderr)
        print("Не отправляйте API-ключ в чат. Запрос к модели не выполнялся.", file=sys.stderr)
        return 2

    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["CREWAI_TELEMETRY_ENABLED"] = "false"
    os.environ["CREWAI_TRACING_ENABLED"] = "false"
    os.environ.setdefault("CREWAI_STORAGE_DIR", str(PROJECT_ROOT / ".crewai"))
    previous_logging = logging.root.manager.disable
    try:
        # SDK может писать диагностические данные. Не показываем их и текст исключений.
        logging.disable(logging.CRITICAL)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from crewai import LLM
            from crewai.events import crewai_event_bus

            kwargs = {
                "model": settings.model,
                "provider": settings.provider,
                "api_key": settings.api_key,
                "timeout": 30,
                "max_retries": 0,
            }
            if settings.base_url:
                kwargs["base_url"] = settings.base_url
            llm = LLM(**kwargs)
            try:
                response = llm.call([
                    {"role": "user", "content": "Ответь одной короткой фразой: подключение работает."}
                ])
            finally:
                # События SDK обрабатываются в фоне. Завершаем их, пока вывод скрыт.
                crewai_event_bus.shutdown(wait=True)
        if not isinstance(response, str) or not response.strip():
            print("Модель не вернула текстовый ответ. Подключение не подтверждено.", file=sys.stderr)
            return 1
        safe_response = response.replace(settings.api_key, "[секрет скрыт]")
        print("Настоящий ответ модели:")
        print(safe_response)
        return 0
    except Exception as error:
        current = error
        status = None
        for _ in range(5):
            candidate = getattr(current, "status_code", None)
            if isinstance(candidate, int):
                status = candidate
                break
            current = current.__cause__ or current.__context__
            if current is None:
                break
        if status == 403:
            print("API отказал в доступе (HTTP 403): проверьте разрешения ключа на выбранную модель.", file=sys.stderr)
        elif status == 401:
            print("API не принял ключ (HTTP 401): проверьте локальный LLM_API_KEY.", file=sys.stderr)
        elif status == 429:
            print("API сообщил об ограничении (HTTP 429): проверьте лимиты и баланс.", file=sys.stderr)
        print(
            "Не удалось получить ответ модели. Проверьте провайдера, модель, ключ, "
            "доступ к API, баланс и необходимые зависимости провайдера. "
            "Детали SDK скрыты, чтобы не раскрыть секреты.",
            file=sys.stderr,
        )
        return 1
    finally:
        logging.disable(previous_logging)


if __name__ == "__main__":
    raise SystemExit(main())
