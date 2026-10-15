"""Готовый TavilySearchTool с фиксированным basic-поиском."""

import json
import os

from crewai.tools import BaseTool
from crewai_tools import TavilySearchTool
from pydantic import BaseModel, ConfigDict, Field
from tavily import TavilyClient

from travel_planner.settings import load_settings


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    search_query: str = Field(min_length=1, max_length=400, description="Короткий запрос для поиска публичных веб-источников")


class BasicTavilyClient(TavilyClient):
    """Явно отключает автонастройку, которой нет в интерфейсе готового tool."""

    def search(self, query: str, **kwargs):
        kwargs.update(search_depth="basic", auto_parameters=False)
        return super().search(query=query, **kwargs)


class InternetSearchTool(BaseTool):
    name: str = "internet_search"
    description: str = (
        "Ищет публичные веб-источники через Tavily basic. Вход search_query; "
        "выход status ok/empty/error и results с title, url, description. "
        "Advanced-поиск и автоматическое повышение глубины отключены."
    )
    args_schema: type[BaseModel] = SearchInput

    def _run(self, search_query: str) -> dict:
        query = SearchInput.model_validate({"search_query": search_query}).search_query
        load_settings()
        key = os.getenv("TAVILY_API_KEY", "").strip()
        base = {"query": query, "provider": "tavily", "search_depth": "basic", "results": []}
        if not key:
            return {**base, "status": "error", "error_code": "missing_key",
                    "message": "Добавьте TAVILY_API_KEY в локальный .env. Ключ не отправляйте в чат."}
        try:
            backend = TavilySearchTool(
                api_key=key, search_depth="basic", max_results=5, topic="general",
                include_answer=False, include_raw_content=False, include_images=False, timeout=20,
            )
            backend.client = BasicTavilyClient(api_key=key, client_name="crewai")
            raw = json.loads(backend.run(query=query))
            if not isinstance(raw, dict) or not isinstance(raw.get("results"), list):
                raise ValueError("Invalid search response")
            results = []
            for item in raw["results"]:
                if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not isinstance(item.get("url"), str):
                    raise ValueError("Invalid result item")
                results.append({"title": item["title"], "url": item["url"],
                                "description": item.get("content") or ""})
            return {**base, "status": "ok" if results else "empty", "results": results,
                    "error_code": None, "message": "" if results else "Источники не найдены."}
        except Exception:
            return {**base, "status": "error", "error_code": "search_failed",
                    "message": "Запрос Tavily не выполнен: проверьте ключ, доступ, квоту и формат ответа. Сырой текст SDK скрыт."}
