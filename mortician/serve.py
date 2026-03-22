"""Local HTTP dashboard: JSON postmortems + SSE when files change."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from watchfiles import awatch

from .utils import POSTMORTEMS_DIR, load_postmortem

STATIC_DIR = Path(__file__).resolve().parent / "static"

# SSE subscribers; each holds a small queue so slow clients do not block others.
_subscribers: List[asyncio.Queue] = []
_SSE_QUEUE_MAX = 8


def _summaries():
    rows = []
    for path in sorted(POSTMORTEMS_DIR.glob("*.json")):
        data = load_postmortem(path.stem)
        if data is None:
            continue
        overview = data.get("overview") or {}
        rows.append(
            {
                "id": path.stem,
                "title": overview.get("incident_title", ""),
                "status": overview.get("status", ""),
                "date": overview.get("date", ""),
            }
        )
    return rows


def _notify_subscribers() -> None:
    stale = []
    for q in list(_subscribers):
        try:
            q.put_nowait({"type": "postmortems_updated"})
        except asyncio.QueueFull:
            stale.append(q)
    for q in stale:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass


async def _watch_loop() -> None:
    POSTMORTEMS_DIR.mkdir(exist_ok=True)
    events: asyncio.Queue = asyncio.Queue()

    async def pump() -> None:
        try:
            async for _ in awatch(POSTMORTEMS_DIR):
                await events.put(None)
        except asyncio.CancelledError:
            raise

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            await events.get()
            await asyncio.sleep(0.2)
            while True:
                try:
                    events.get_nowait()
                except asyncio.QueueEmpty:
                    break
            _notify_subscribers()
    finally:
        pump_task.cancel()
        try:
            await pump_task
        except asyncio.CancelledError:
            pass


@asynccontextmanager
async def lifespan(app: Starlette):
    watcher = asyncio.create_task(_watch_loop())
    yield
    watcher.cancel()
    try:
        await watcher
    except asyncio.CancelledError:
        pass


async def api_list(_request):
    return JSONResponse(_summaries())


async def api_get(request):
    issue_id = request.path_params["issue_id"]
    data = load_postmortem(issue_id)
    if data is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(data)


async def api_events(_request):
    queue: asyncio.Queue = asyncio.Queue(maxsize=_SSE_QUEUE_MAX)
    _subscribers.append(queue)

    async def gen():
        try:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                msg = await queue.get()
                yield f"data: {json.dumps(msg)}\n\n"
        finally:
            try:
                _subscribers.remove(queue)
            except ValueError:
                pass

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


routes = [
    Route("/api/postmortems", endpoint=api_list, methods=["GET"]),
    Route("/api/postmortems/{issue_id}", endpoint=api_get, methods=["GET"]),
    Route("/api/events", endpoint=api_events, methods=["GET"]),
    Mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static"),
]

app = Starlette(routes=routes, lifespan=lifespan)
