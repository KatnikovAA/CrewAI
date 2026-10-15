"""Local single-worker HTTP API. No paid requests during startup or health checks."""
from contextlib import asynccontextmanager
import asyncio
import os
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from travel_planner.runtime import configure_runtime
configure_runtime()  # Before any optional CrewAI import, including application extensions.
from travel_planner.api_jobs import TripManager, BusyError, ClosingError
from travel_planner.models import TripInput, ResearchResult, BudgetResult, ItineraryResult
from travel_planner.settings import PROJECT_ROOT


class AcceptedResponse(BaseModel):
    trip_id: str
    status_url: str
    result_url: str


class SafeError(BaseModel):
    code: str
    message: str


class ProgressEvent(BaseModel):
    seq: int
    timestamp: datetime
    type: str
    task: Literal['research', 'budget', 'itinerary'] | None
    tool: Literal['internet_search', 'website_reader', 'trip_cost_calculator'] | None = None
    status: Literal['ok', 'empty', 'error'] | None = None
    from_cache: bool | None = None


class TripStateResponse(BaseModel):
    trip_id: str
    status: Literal['queued', 'running', 'completed', 'failed']
    current_task: Literal['research', 'budget', 'itinerary'] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    events: list[ProgressEvent]
    events_total: int
    error: SafeError | None


class TaskResults(BaseModel):
    research: ResearchResult
    budget: BudgetResult
    itinerary: ItineraryResult


class TripResultResponse(BaseModel):
    trip_id: str
    final: ItineraryResult
    tasks: TaskResults


def create_app(*, manager=None):
    load_dotenv(PROJECT_ROOT / '.env', override=False, encoding='utf-8-sig', interpolate=False)
    origin = os.getenv('API_CORS_ORIGIN', 'http://localhost:5173').strip()
    parts = urlsplit(origin)
    if (parts.scheme not in ('http', 'https') or not parts.netloc or parts.username
            or parts.password or parts.path or parts.query or parts.fragment or '*' in origin):
        raise ValueError('API_CORS_ORIGIN must be one explicit HTTP(S) origin without a path')

    @asynccontextmanager
    async def lifespan(app):
        app.state.trips = manager if manager is not None else TripManager()
        try:
            yield
        finally:
            await asyncio.to_thread(app.state.trips.close)

    app = FastAPI(title='Планировщик путешествий', lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[origin], allow_credentials=False,
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])

    @app.get('/health')
    async def health():
        return {'status': 'ok', 'external_services': 'not_checked'}

    @app.post('/trips', status_code=202, response_model=AcceptedResponse)
    async def submit(trip: TripInput):
        try:
            trip_id = app.state.trips.submit(trip)
        except BusyError:
            raise HTTPException(409, detail={'code': 'trip_in_progress'}) from None
        except ClosingError:
            raise HTTPException(503, detail={'code': 'server_stopping'}) from None
        return dict(trip_id=trip_id, status_url=f'/trips/{trip_id}', result_url=f'/trips/{trip_id}/result')

    @app.get('/trips/{trip_id}', response_model=TripStateResponse, response_model_exclude_unset=True)
    async def status(trip_id: str):
        state = app.state.trips.get(trip_id)
        if state is None:
            raise HTTPException(404, detail={'code': 'trip_not_found'})
        return state

    @app.get('/trips/{trip_id}/result', response_model=TripResultResponse)
    async def result(trip_id: str):
        state, output = app.state.trips.get_with_result(trip_id)
        if state is None:
            raise HTTPException(404, detail={'code': 'trip_not_found'})
        if state['status'] != 'completed':
            raise HTTPException(409, detail={'code': 'result_unavailable', 'status': state['status']})
        return output

    return app


app = create_app()
