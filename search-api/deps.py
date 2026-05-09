"""FastAPI dependencies — single source of truth for the ES client handle."""

from __future__ import annotations

from fastapi import Request

from es_client import ESClient


def get_es_client(request: Request) -> ESClient:
    return request.app.state.es_client
