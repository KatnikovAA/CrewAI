"""Отдельные реальные проверки, без основных Tasks и Crew."""
import argparse
import contextlib
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from travel_planner.runtime import configure_runtime
from travel_planner.settings import load_settings

PROMPTS = {
    "researcher": (
        "Проверка инструментов: выполни ровно один internet_search с search_query "
        "'site:example.com Example Domain'. Затем прочитай одну найденную страницу "
        "через website_reader. Если example.com есть в выдаче, предпочти её. "
        "Дай 1 подтверждённый факт с URL и отметь, что это демонстрационная страница, "
        "а сведения о достопримечательностях не проверялись. Не делай других запросов."
    ),
    "budget": (
        "Проверка: поездка на 2 дня для 3 человек. Уже ПОЛНЫЕ суммы всей поездки и группы: "
        "проезд 1200.10 RUB, жильё 2400.20 RUB, питание 900.30 RUB. Общий бюджет 5000 RUB. "
        "Вызови trip_cost_calculator ровно один раз с этими тремя статьями и бюджетом. "
        "Сообщи итог и остаток, валюту и что цены заданы пользователем, не проверены рынком. "
        "Не используй поиск/чтение и не умножай суммы."
    ),
    "planner": (
        "Тестовые входные данные, не результаты поиска: день 1 музей 10:00–12:00, "
        "день 2 парк 11:00–13:00; между событиями нет переезда в тот же день. "
        "Переданный источник https://example.com — только демонстрационный URL. "
        "Для всей группы за всю поездку музей 600.10 RUB, парк 0 RUB, транспорт 400.20 RUB. "
        "Бюджет 1500 RUB. Сначала один раз вызови trip_cost_calculator с этими статьями, "
        "потом составь маршрут на 2 дня, итог и остаток. Сохрани ссылку с пояснением, "
        "отметь отсутствие города, дат и подтверждённых часов. Не придумывай поиск."
    ),
}


def worker(name):
    configure_runtime()
    settings = load_settings()
    records = []
    calls = 0
    failure = None
    result = None
    old_logging = logging.root.manager.disable
    try:
        logging.disable(logging.CRITICAL)
        # Сырые SDK-сообщения и страницы не попадают в отчёт.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from travel_planner.agents import create_agents
            from crewai.events import crewai_event_bus
            agents = create_agents()
            agent = agents[name]
            original_call = type(agent.llm).call

            def counted_call(instance, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls > 9:
                    raise RuntimeError("LLM request limit")
                return original_call(instance, *args, **kwargs)

            def observe(tool):
                original = type(tool)._run

                def observed(instance, *args, **kwargs):
                    output = original(instance, *args, **kwargs)
                    entry = {"tool": tool.name, "status": output.get("status")}
                    if tool.name == "internet_search":
                        entry["urls"] = [item["url"] for item in output.get("results", [])]
                    elif tool.name == "website_reader":
                        entry.update(source_url=output.get("source_url"), text_length=len(output.get("text", "")))
                    else:
                        entry.update({key: output.get(key) for key in ("total", "currency", "remaining", "over_budget")})
                    records.append(entry)
                    return output
                return observed

            try:
                with contextlib.ExitStack() as stack:
                    # Только наблюдение: оригинальный _run выполняется и его результат не меняется.
                    for tool in agent.tools:
                        stack.enter_context(patch.object(type(tool), "_run", observe(tool)))
                    stack.enter_context(patch.object(type(agent.llm), "call", counted_call))
                    result = agent.kickoff(PROMPTS[name])
            finally:
                # Только одноразовый CLI; фабрики никогда не останавливают event bus.
                crewai_event_bus.shutdown(wait=True)
    except Exception as error:
        failure = type(error).__name__  # Не печатаем текст исключения/SDK.
    finally:
        logging.disable(old_logging)
    answer = getattr(result, "raw", "")
    successful = [record for record in records if record["status"] == "ok"]
    names = {record["tool"] for record in successful}
    required = {"internet_search", "website_reader"} if name == "researcher" else {"trip_cost_calculator"}
    verified = bool(answer.strip()) and required <= names and failure is None
    if name == "researcher":
        urls = {url for record in successful for url in record.get("urls", [])}
        verified = verified and any(record.get("source_url", "").rstrip("/") in
                                   {url.rstrip("/") for url in urls} for record in successful
                                   if record["tool"] == "website_reader")
    else:
        expected = ("4500.60", "499.40") if name == "budget" else ("1000.30", "499.70")
        verified = verified and any((record.get("total"), record.get("remaining")) == expected
                                   and record.get("currency") == "RUB" for record in successful)
    report = json.dumps({"agent": name, "verified": verified, "llm_calls": calls,
                         "tools": records, "answer": answer, "error_type": failure}, ensure_ascii=False, indent=2)
    for secret in (settings.api_key, os.getenv("TAVILY_API_KEY", "")):
        if secret:
            report = report.replace(secret, "[секрет скрыт]")
    print(report)
    return 0 if verified else 1


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent", choices=PROMPTS)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker(args.agent)
    try:
        process = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), args.agent, "--worker"],
                                 capture_output=True, text=True, encoding="utf-8", timeout=150)
    except subprocess.TimeoutExpired:
        print("Проверка остановлена через 150 секунд; завершение агента не подтверждено.")
        return 1
    # Печатаем только валидный безопасный отчёт; аварийный stderr скрыт.
    try:
        report = json.loads(process.stdout)
    except ValueError:
        print("Нет отчёта агента: проверьте настройки и доступ к служебному хранилищу. Диагностика SDK скрыта.")
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
