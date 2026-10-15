"""Настройка служебных файлов до импорта CrewAI; без сетевых запросов."""
import os
from travel_planner.settings import PROJECT_ROOT


def configure_runtime():
    os.environ.setdefault("CREWAI_STORAGE_DIR", str(PROJECT_ROOT / ".crewai"))
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["CREWAI_TELEMETRY_ENABLED"] = "false"
    os.environ["CREWAI_TRACING_ENABLED"] = "false"
