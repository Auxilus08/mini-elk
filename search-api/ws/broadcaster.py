"""Phase 2 WebSocket broadcaster — slot reserved.

In Phase 2 the collector will publish anomaly events to a side channel
(probably Redis pub/sub or an in-process queue if we collapse search-api +
collector). Connected dashboard clients will receive pushes here instead of
polling /anomalies/recent.

Phase 1 lives entirely on polling — useAnomalyStream() in the dashboard hides
the transport choice, so flipping to ws happens entirely below the hook.
"""

from __future__ import annotations

from typing import Any, List


class ConnectionManager:
    """Will hold active WebSocket connections and broadcast AnomalyEvents."""

    def __init__(self) -> None:
        self._connections: List[Any] = []  # WebSocket once wired

    async def connect(self, websocket: Any) -> None:
        # Phase 2: await websocket.accept(); self._connections.append(websocket)
        raise NotImplementedError("Phase 2 — not wired in Phase 1")

    async def disconnect(self, websocket: Any) -> None:
        raise NotImplementedError("Phase 2 — not wired in Phase 1")

    async def broadcast(self, event: Any) -> None:
        # Phase 2: for ws in self._connections: await ws.send_json(event)
        raise NotImplementedError("Phase 2 — not wired in Phase 1")
