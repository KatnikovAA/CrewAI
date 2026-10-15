"""JSON → один ограниченный запуск Crew → новый JSON результата."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from uuid import uuid4

from travel_planner.models import TripInput
from travel_planner.runner import RunResult, run_trip


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=float, default=420)
    parser.add_argument("--max-llm-calls", type=int, default=24)
    args = parser.parse_args()
    try:
        if not 0 < args.timeout <= 900 or not 1 <= args.max_llm_calls <= 60:
            raise ValueError("Invalid limits")
        trip = TripInput.model_validate_json(args.input.read_text(encoding="utf-8-sig"))
        output = args.output or Path("results") / f"trip-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        # Reserve before spending requests; never overwrite an existing file.
        with output.open("x", encoding="utf-8") as stream:
            json.dump(dict(status="running", final=None), stream)
    except (ValueError, OSError):
        print("Неверный вход или недоступный/существующий выходной файл. Запуск не выполнен.")
        return 2
    journal = output.with_suffix(".events.jsonl")
    try:
        with journal.open("x", encoding="utf-8") as stream:
            def observe(event):
                line = json.dumps(event, ensure_ascii=False)
                stream.write(line + "\n")
                stream.flush()
                print(line, flush=True)
            result = run_trip(trip, timeout=args.timeout, max_llm_calls=args.max_llm_calls, on_event=observe)
        # Only our reservation is replaced; other runs cannot reserve this path.
        output.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError):
        failure = RunResult(status="failed", trip=trip, error="cli_file_or_parameter_error")
        try:
            output.write_text(json.dumps(failure.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        print("Запуск/сохранение не завершены. Проверьте выходной файл и журнал событий.")
        return 2
    print(f"Статус: {result.status}; результат: {output.resolve()}")
    return 0 if result.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
