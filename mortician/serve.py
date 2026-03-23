"""Local HTTP dashboard: incident bundles + SSE when files change."""

from __future__ import annotations

import asyncio
import json
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from watchfiles import awatch

from .bundle import (
    INCIDENTS_DIR,
    find_bundle_dir,
    list_incident_summaries,
    load_postmortem,
    write_index_md_atomic,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

_subscribers: List[asyncio.Queue] = []
_SSE_QUEUE_MAX = 8


def _summaries():
    return list_incident_summaries()


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
    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    events: asyncio.Queue = asyncio.Queue()

    async def pump() -> None:
        try:
            async for _ in awatch(INCIDENTS_DIR):
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


async def api_list(_request: Request):
    return JSONResponse(_summaries())


async def api_get(request: Request):
    issue_id = request.path_params["issue_id"]
    data = load_postmortem(issue_id)
    if data is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(data)


async def put_index_md(request: Request):
    issue_id = request.path_params["issue_id"]
    bundle = find_bundle_dir(issue_id)
    if bundle is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    body = await request.body()
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return JSONResponse({"error": "invalid encoding"}, status_code=400)
    write_index_md_atomic(bundle, text)
    _notify_subscribers()
    return Response(status_code=204)


def _safe_asset_file(bundle: Path, asset_path: str) -> Optional[Path]:
    if not asset_path or asset_path.startswith(("/", "\\")):
        return None
    parts = Path(asset_path).parts
    if ".." in parts:
        return None
    base = bundle / ASSETS_DIRNAME
    candidate = (base / asset_path).resolve()
    root = base.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


async def api_asset(request: Request):
    issue_id = request.path_params["issue_id"]
    asset_path = request.path_params["asset_path"]
    bundle = find_bundle_dir(issue_id)
    if bundle is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    path = _safe_asset_file(bundle, asset_path)
    if path is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(path, media_type=media_type or "application/octet-stream")


async def api_events(_request: Request):
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
    Route(
        "/api/postmortems/{issue_id}/index.md",
        endpoint=put_index_md,
        methods=["PUT"],
    ),
    Route(
        "/api/postmortems/{issue_id}/assets/{asset_path:path}",
        endpoint=api_asset,
        methods=["GET"],
    ),
    Route("/api/postmortems/{issue_id}", endpoint=api_get, methods=["GET"]),
    Route("/api/events", endpoint=api_events, methods=["GET"]),
    Mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static"),
]

app = Starlette(routes=routes, lifespan=lifespan)
