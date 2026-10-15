"""Отдельные проверки инструментов, без агентов и LLM."""

import argparse
import json
import os
import sys

from travel_planner.settings import PROJECT_ROOT, load_settings


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", choices=["reader", "calculator", "search"])
    parser.add_argument("--url", default="https://example.com")
    parser.add_argument("--query", default="Kazan official tourism")
    args = parser.parse_args()
    # Общий загрузчик сохраняет приоритет окружения; LLM здесь не создаётся.
    load_settings()
    os.environ.setdefault("CREWAI_STORAGE_DIR", str(PROJECT_ROOT / ".crewai"))
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["CREWAI_TELEMETRY_ENABLED"] = "false"
    os.environ["CREWAI_TRACING_ENABLED"] = "false"
    try:
        if args.tool == "reader":
            from travel_planner.tools.web import WebsiteReaderTool
            result = WebsiteReaderTool().run(website_url=args.url)
        elif args.tool == "calculator":
            from travel_planner.tools.calculator import TripCostCalculatorTool
            result = TripCostCalculatorTool().run(
                expenses=[{"name": "Проезд всей группы", "amount": "100.10"},
                          {"name": "Проживание всей группы", "amount": "200.20"}],
                currency="RUB", budget="400",
            )
        else:
            from travel_planner.tools.search import InternetSearchTool
            result = InternetSearchTool().run(search_query=args.query)
        serialized = json.dumps(result, ensure_ascii=False, indent=2)
        for variable in ("LLM_API_KEY", "TAVILY_API_KEY"):
            secret = os.getenv(variable, "")
            if secret:
                serialized = serialized.replace(secret, "[секрет скрыт]")
        print(serialized)
        return 0 if result["status"] == "ok" else 2 if result.get("error_code") == "missing_key" else 1
    except ValueError:
        print("Неверные входные данные. Проверьте схему и URL; сырой текст ошибки скрыт.")
        return 2
    except Exception:
        print("Проверка не завершена: проверьте установку и настройки. Диагностика SDK скрыта.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
