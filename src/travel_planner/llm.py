"""Переиспользуемая LLM, без запросов и остановки event bus."""
from travel_planner.runtime import configure_runtime
from travel_planner.settings import Settings, load_settings


def create_llm(settings: Settings | None = None, *, interceptor=None, max_tokens=1800, timeout=30, response_format=None):
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
               timeout=timeout, max_retries=0, max_tokens=max_tokens, interceptor=interceptor,
               response_format=response_format)


def _trip_request_format(request):
    """Never combine native tools with constrained text output in one request."""
    import json
    import httpx

    payload = json.loads(request.content)
    if payload.get("tools"):
        if "response_format" not in payload:
            return request
        del payload["response_format"]
    elif "response_format" not in payload:
        # No tools: a final formatting/conversion request. Preserve any explicit schema.
        payload["response_format"] = {"type": "json_object"}
    else:
        return request
    headers = request.headers.copy()
    headers.pop("content-length", None)
    headers.pop("transfer-encoding", None)
    return httpx.Request(request.method, request.url, headers=headers,
                         content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                         extensions=request.extensions)


def create_trip_llm(settings: Settings | None = None, *, interceptor=None):
    """Native tools stay unconstrained; tool-free formatting requests use JSON mode."""
    configure_runtime()
    from crewai.llms.hooks.base import BaseInterceptor

    class TripFormatInterceptor(BaseInterceptor):
        def on_outbound(self, request):
            if interceptor is not None:
                request = interceptor.on_outbound(request)
            return _trip_request_format(request)

        def on_inbound(self, response):
            return interceptor.on_inbound(response) if interceptor is not None else response

        async def aon_outbound(self, request):
            if interceptor is not None:
                request = await interceptor.aon_outbound(request)
            return _trip_request_format(request)

        async def aon_inbound(self, response):
            return await interceptor.aon_inbound(response) if interceptor is not None else response

    return create_llm(settings, interceptor=TripFormatInterceptor(), max_tokens=12000, timeout=90)
