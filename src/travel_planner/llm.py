"""Переиспользуемая LLM, без запросов и остановки event bus."""
from travel_planner.runtime import configure_runtime
from travel_planner.settings import Settings, load_settings


def create_llm(settings: Settings | None = None, *, interceptor=None, max_tokens=1800, timeout=30):
    settings = settings if settings is not None else load_settings()
    missing = [name for name, value in (
        ("LLM_PROVIDER", settings.provider), ("LLM_MODEL", settings.model),
        ("LLM_API_KEY", settings.api_key), ("LLM_BASE_URL", settings.base_url),
    ) if not value]
    if missing:
        raise ValueError("Заполните локальный .env: " + ", ".join(missing))
    configure_runtime()
    from crewai import LLM
    return LLM(provider=settings.provider, model=settings.model,
               base_url=settings.base_url, api_key=settings.api_key,
               timeout=timeout, max_retries=0, max_tokens=max_tokens, interceptor=interceptor)
