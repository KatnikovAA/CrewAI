"""Загрузка локальных настроек без вывода секретов."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    api_key: str = field(repr=False)
    base_url: str = field(default="", repr=False)


def load_settings(env_path: Path | None = None) -> Settings:
    load_dotenv(
        dotenv_path=env_path if env_path is not None else PROJECT_ROOT / ".env",
        override=False,
        encoding="utf-8-sig",
        interpolate=False,
    )
    return Settings(
        provider=os.getenv("LLM_PROVIDER", "").strip(),
        model=os.getenv("LLM_MODEL", "").strip(),
        api_key=os.getenv("LLM_API_KEY", "").strip(),
        base_url=os.getenv("LLM_BASE_URL", "").strip(),
    )
