"""Server-Sent Events stream for live dashboard updates."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.core.clock import utc_now
from app.core.deps import get_hub, get_scanner

router = APIRouter(tags=["stream"])


async def _event_source(request: Request):
    hub = get_hub(request)
    scanner = get_scanner(request)

    yield "retry: 3000\n\n"
    yield (
        "event: status\n"
        f"data: {json.dumps({'type': 'status', 'ts': utc_now().isoformat(), 'data': {'state': 'running' if scanner.running else 'stopped'}})}\n\n"
    )
    async with hub.subscribe() as queue:
        while True:
            if await request.is_disconnected():
                break
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=15.0)
            except TimeoutError:
                payload = hub.heartbeat_payload()
            yield f"event: {payload['type']}\ndata: {json.dumps(payload)}\n\n"


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    return StreamingResponse(
        _event_source(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
