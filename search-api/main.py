"""FastAPI app — composition root."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from es_client import ESClient
from routers import anomalies as anomalies_router
from routers import health as health_router
from routers import logs as logs_router
from ws.broadcaster import ConnectionManager


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings
    es = ESClient(settings)
    await es.connect()
    app.state.es_client = es
    app.state.start_time = time.time()
    # Phase 2 broadcast slot — instantiated but never wired in Phase 1.
    app.state.connection_manager = ConnectionManager()
    try:
        yield
    finally:
        await es.close()


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_logging(settings.log_level)

    app = FastAPI(
        title="mini-elk search API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    app.include_router(health_router.router)
    app.include_router(logs_router.router)
    app.include_router(anomalies_router.router)
    return app


app = create_app()
