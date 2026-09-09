from collections.abc import AsyncGenerator, Callable
from contextlib import _AsyncGeneratorContextManager, asynccontextmanager
from typing import Any

import anyio
import fastapi
import redis.asyncio as redis
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from ..api.dependencies import get_current_superuser
from ..middleware.client_cache_middleware import ClientCacheMiddleware
from ..middleware.logger_middleware import LoggerMiddleware
from ..models import *  # noqa: F403
from .config import (
    AppSettings,
    ClientSideCacheSettings,
    CORSSettings,
    DatabaseSettings,
    EnvironmentOption,
    EnvironmentSettings,
    LlmTierSettings,
    MemorySettings,
    RedisCacheSettings,
    RedisQueueSettings,
    settings,
)
from .db.database import Base
from .db.database import async_engine as engine
from .llm import service as llm_service_module
from .llm.embedding_model import init_embedding_model
from .llm.factory import build_llm_provider
from .llm.provider import LlmProvider, LlmTier
from .llm.service import LlmService
from .utils import cache, queue


# -------------- database --------------
async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# -------------- cache --------------
async def create_redis_cache_pool() -> None:
    cache.pool = redis.ConnectionPool.from_url(settings.REDIS_CACHE_URL)
    cache.client = redis.Redis.from_pool(cache.pool)  # type: ignore


async def close_redis_cache_pool() -> None:
    if cache.client is not None:
        await cache.client.aclose()  # type: ignore


# -------------- queue --------------
async def create_redis_queue_pool() -> None:
    queue.pool = await create_pool(RedisSettings(host=settings.REDIS_QUEUE_HOST, port=settings.REDIS_QUEUE_PORT))


async def close_redis_queue_pool() -> None:
    if queue.pool is not None:
        await queue.pool.aclose()  # type: ignore


# -------------- llm --------------
def build_llm_service() -> None:
    """Builds all three tiers via `build_llm_provider` and assigns the module-level
    `llm_service` global — same lifecycle pattern as `core/utils/queue.py`'s `pool`
    global. Nothing to close at shutdown: plain `httpx.AsyncClient()` per-call, no
    persistent connection pool to tear down, unlike Redis/queue."""
    tiers: list[LlmTier] = ["high", "medium", "low"]
    providers: dict[LlmTier, LlmProvider] = {tier: build_llm_provider(tier, settings) for tier in tiers}
    llm_service_module.llm_service = LlmService(providers)


# -------------- application --------------
async def set_threadpool_tokens(number_of_tokens: int = 100) -> None:
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = number_of_tokens


def lifespan_factory(
    settings: (
        DatabaseSettings
        | RedisCacheSettings
        | AppSettings
        | ClientSideCacheSettings
        | CORSSettings
        | RedisQueueSettings
        | EnvironmentSettings
        | LlmTierSettings
        | MemorySettings
    ),
    create_tables_on_start: bool = True,
    init_llm_on_start: bool = True,
) -> Callable[[FastAPI], _AsyncGeneratorContextManager[Any]]:
    """Factory to create a lifespan async context manager for a FastAPI app.

    `init_llm_on_start` gates both the LLM tier build and the embedding-model load, the
    same way `create_tables_on_start` gates table creation — the embedding model in
    particular downloads/loads real model weights, so any future test that boots a real
    `TestClient(app)` for something unrelated (e.g. login) needs a way to skip it rather
    than blocking on it every time."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator:
        from asyncio import Event

        initialization_complete = Event()
        app.state.initialization_complete = initialization_complete

        await set_threadpool_tokens()

        try:
            if isinstance(settings, RedisCacheSettings):
                await create_redis_cache_pool()

            if isinstance(settings, RedisQueueSettings):
                await create_redis_queue_pool()

            if create_tables_on_start:
                await create_tables()

            if init_llm_on_start and isinstance(settings, LlmTierSettings):
                build_llm_service()

            if init_llm_on_start and isinstance(settings, MemorySettings):
                await init_embedding_model()

            initialization_complete.set()

            yield

        finally:
            if isinstance(settings, RedisCacheSettings):
                await close_redis_cache_pool()

            if isinstance(settings, RedisQueueSettings):
                await close_redis_queue_pool()

    return lifespan


# -------------- application --------------
def create_application(
    router: APIRouter,
    settings: (
        DatabaseSettings
        | RedisCacheSettings
        | AppSettings
        | ClientSideCacheSettings
        | CORSSettings
        | RedisQueueSettings
        | EnvironmentSettings
        | LlmTierSettings
        | MemorySettings
    ),
    create_tables_on_start: bool = True,
    init_llm_on_start: bool = True,
    lifespan: Callable[[FastAPI], _AsyncGeneratorContextManager[Any]] | None = None,
    **kwargs: Any,
) -> FastAPI:
    """Creates and configures a FastAPI application based on the provided settings.

    Parameters
    ----------
    router : APIRouter
        The APIRouter object containing the routes to be included in the FastAPI application.
    settings
        An instance representing the settings for configuring the FastAPI application.
    create_tables_on_start : bool
        A flag to indicate whether to create database tables on application startup.
    init_llm_on_start : bool
        A flag to indicate whether to build the LLM tiers and load the embedding model on
        application startup — see `lifespan_factory`'s docstring.
    **kwargs
        Additional keyword arguments passed directly to the FastAPI constructor.

    Returns
    -------
    FastAPI
        A fully configured FastAPI application instance.
    """
    # --- before creating application ---
    if isinstance(settings, AppSettings):
        to_update = {
            "title": settings.APP_NAME,
            "description": settings.APP_DESCRIPTION,
            "contact": {"name": settings.CONTACT_NAME, "email": settings.CONTACT_EMAIL},
            "license_info": {"name": settings.LICENSE_NAME},
        }
        kwargs.update(to_update)

    if isinstance(settings, EnvironmentSettings):
        kwargs.update({"docs_url": None, "redoc_url": None, "openapi_url": None})

    # Use custom lifespan if provided, otherwise use default factory
    if lifespan is None:
        lifespan = lifespan_factory(
            settings, create_tables_on_start=create_tables_on_start, init_llm_on_start=init_llm_on_start
        )

    application = FastAPI(lifespan=lifespan, **kwargs)
    application.include_router(router)

    if isinstance(settings, ClientSideCacheSettings):
        application.add_middleware(ClientCacheMiddleware, max_age=settings.CLIENT_CACHE_MAX_AGE)

    if isinstance(settings, CORSSettings):
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=settings.CORS_METHODS,
            allow_headers=settings.CORS_HEADERS,
        )
    application.add_middleware(LoggerMiddleware)
    if isinstance(settings, EnvironmentSettings):
        if settings.ENVIRONMENT != EnvironmentOption.PRODUCTION:
            docs_router = APIRouter()
            if settings.ENVIRONMENT != EnvironmentOption.LOCAL:
                docs_router = APIRouter(dependencies=[Depends(get_current_superuser)])

            @docs_router.get("/docs", include_in_schema=False)
            async def get_swagger_documentation() -> fastapi.responses.HTMLResponse:
                return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")

            @docs_router.get("/redoc", include_in_schema=False)
            async def get_redoc_documentation() -> fastapi.responses.HTMLResponse:
                return get_redoc_html(openapi_url="/openapi.json", title="docs")

            @docs_router.get("/openapi.json", include_in_schema=False)
            async def openapi() -> dict[str, Any]:
                out: dict = get_openapi(title=application.title, version=application.version, routes=application.routes)
                return out

            application.include_router(docs_router)

    return application
