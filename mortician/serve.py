"""Local HTTP dashboard: incident bundles + SSE when files change."""

from __future__ import annotations

import asyncio
import io
import json
import mimetypes
import zipfile
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
    ASSETS_DIRNAME,
    INCIDENTS_DIR,
    INDEX_SECTION_SLUGS,
    SUB_IMPACT_AFFECTED,
    SUB_IMPACT_BUSINESS,
    SUB_IMPACT_DURATION,
    append_action_row,
    append_timeline_row,
    bulk_set_action_done,
    find_bundle_dir,
    list_incident_summaries,
    load_postmortem,
    patch_action_item,
    patch_timeline_item,
    patch_index_md_section,
    reorder_action_item,
    reorder_timeline_item,
    sort_timeline_by_time,
    write_index_md_atomic,
)
from .statuses import status_config_payload

STATIC_DIR = Path(__file__).resolve().parent / "static"

_subscribers: List[asyncio.Queue] = []
_SSE_QUEUE_MAX = 8


def _json_error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _bundle_or_404(issue_id: str) -> Optional[Path]:
    return find_bundle_dir(issue_id)


async def _decode_utf8_body(request: Request) -> Optional[str]:
    body = await request.body()
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return None


async def _parse_json_object(request: Request) -> tuple[Optional[dict], Optional[JSONResponse]]:
    body = await request.body()
    try:
        text = body.decode("utf-8") if body else "{}"
        payload = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, _json_error("invalid JSON", 400)
    if not isinstance(payload, dict):
        return None, _json_error("body must be a JSON object", 400)
    return payload, None


def _parse_index_or_400(index_raw: str) -> tuple[Optional[int], Optional[JSONResponse]]:
    try:
        return int(index_raw), None
    except (TypeError, ValueError):
        return None, _json_error("invalid index", 400)


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


async def api_statuses(_request: Request):
    cfg = status_config_payload()
    cfg["impact_headings"] = {
        "affected_services": SUB_IMPACT_AFFECTED,
        "duration_of_outage": SUB_IMPACT_DURATION,
        "business_impact": SUB_IMPACT_BUSINESS,
    }
    return JSONResponse(cfg)


async def api_get(request: Request):
    issue_id = request.path_params["issue_id"]
    data = load_postmortem(issue_id)
    if data is None:
        return _json_error("not found", 404)
    return JSONResponse(data)


async def put_index_md(request: Request):
    issue_id = request.path_params["issue_id"]
    bundle = _bundle_or_404(issue_id)
    if bundle is None:
        return _json_error("not found", 404)
    text = await _decode_utf8_body(request)
    if text is None:
        return _json_error("invalid encoding", 400)
    write_index_md_atomic(bundle, text)
    _notify_subscribers()
    return Response(status_code=204)


def _bundle_zip_bytes(bundle: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(bundle.rglob("*")):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(bundle)
            except ValueError:
                continue
            if any(part.startswith(".") for part in rel.parts):
                continue
            zf.write(path, rel.as_posix())
    return buf.getvalue()


async def api_export_zip(request: Request):
    issue_id = request.path_params["issue_id"]
    bundle = _bundle_or_404(issue_id)
    if bundle is None:
        return _json_error("not found", 404)
    data = _bundle_zip_bytes(bundle)
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{issue_id}.zip"',
        },
    )


async def api_put_section(request: Request):
    issue_id = request.path_params["issue_id"]
    section = request.path_params["section"]
    bundle = _bundle_or_404(issue_id)
    if bundle is None:
        return _json_error("not found", 404)
    if section not in INDEX_SECTION_SLUGS:
        return _json_error("unknown section", 400)
    text = await _decode_utf8_body(request)
    if text is None:
        return _json_error("invalid encoding", 400)
    try:
        patch_index_md_section(bundle, section, text)
    except ValueError as e:
        return _json_error(str(e), 400)
    _notify_subscribers()
    return Response(status_code=204)


async def api_post_actions(request: Request):
    issue_id = request.path_params["issue_id"]
    bundle = _bundle_or_404(issue_id)
    if bundle is None:
        return _json_error("not found", 404)
    data, err = await _parse_json_object(request)
    if err is not None:
        return err
    assert data is not None
    raw_task = data.get("task")
    if raw_task is None:
        return _json_error("task is required", 400)
    task = str(raw_task).strip()
    if not task:
        return _json_error("task is required", 400)
    owner = data.get("owner")
    due = data.get("due")
    o = (owner.strip() if isinstance(owner, str) else "") or ""
    d = (due.strip() if isinstance(due, str) else "") or ""
    try:
        append_action_row(bundle, task=task, owner=o, due=d)
    except ValueError as e:
        return _json_error(str(e), 400)
    _notify_subscribers()
    return Response(status_code=204)


async def api_patch_action(request: Request):
    issue_id = request.path_params["issue_id"]
    index_raw = request.path_params["action_index"]
    bundle = _bundle_or_404(issue_id)
    if bundle is None:
        return _json_error("not found", 404)
    index, idx_err = _parse_index_or_400(index_raw)
    if idx_err is not None:
        return idx_err
    updates, err = await _parse_json_object(request)
    if err is not None:
        return err
    assert updates is not None and index is not None
    if not updates:
        return Response(status_code=204)
    try:
        patch_action_item(bundle, index, updates)
    except ValueError as e:
        return _json_error(str(e), 400)
    _notify_subscribers()
    return Response(status_code=204)


async def api_bulk_action_state(request: Request):
    issue_id = request.path_params["issue_id"]
    bundle = _bundle_or_404(issue_id)
    if bundle is None:
        return _json_error("not found", 404)
    payload, err = await _parse_json_object(request)
    if err is not None:
        return err
    assert payload is not None
    if "done" not in payload:
        return _json_error("done is required", 400)
    updated = bulk_set_action_done(bundle, bool(payload.get("done")))
    _notify_subscribers()
    return JSONResponse({"updated": updated})


async def api_reorder_action(request: Request):
    issue_id = request.path_params["issue_id"]
    bundle = _bundle_or_404(issue_id)
    if bundle is None:
        return _json_error("not found", 404)
    payload, err = await _parse_json_object(request)
    if err is not None:
        return err
    assert payload is not None
    try:
        from_index = int(payload.get("from_index"))
        to_index = int(payload.get("to_index"))
    except (TypeError, ValueError):
        return _json_error("from_index and to_index are required integers", 400)
    try:
        reorder_action_item(bundle, from_index, to_index)
    except ValueError as e:
        return _json_error(str(e), 400)
    _notify_subscribers()
    return Response(status_code=204)


async def api_post_timeline(request: Request):
    issue_id = request.path_params["issue_id"]
    bundle = _bundle_or_404(issue_id)
    if bundle is None:
        return _json_error("not found", 404)
    data, err = await _parse_json_object(request)
    if err is not None:
        return err
    assert data is not None
    raw_time = data.get("time")
    raw_action = data.get("action")
    if raw_time is None:
        return _json_error("time is required", 400)
    if raw_action is None:
        return _json_error("action is required", 400)
    time = str(raw_time).strip()
    action = str(raw_action).strip()
    if not time:
        return _json_error("time is required", 400)
    if not action:
        return _json_error("action is required", 400)
    try:
        append_timeline_row(bundle, time=time, action=action)
    except ValueError as e:
        return _json_error(str(e), 400)
    _notify_subscribers()
    return Response(status_code=204)


async def api_reorder_timeline(request: Request):
    issue_id = request.path_params["issue_id"]
    bundle = _bundle_or_404(issue_id)
    if bundle is None:
        return _json_error("not found", 404)
    payload, err = await _parse_json_object(request)
    if err is not None:
        return err
    assert payload is not None
    try:
        from_index = int(payload.get("from_index"))
        to_index = int(payload.get("to_index"))
    except (TypeError, ValueError):
        return _json_error("from_index and to_index are required integers", 400)
    try:
        reorder_timeline_item(bundle, from_index, to_index)
    except ValueError as e:
        return _json_error(str(e), 400)
    _notify_subscribers()
    return Response(status_code=204)


async def api_sort_timeline_by_time(request: Request):
    issue_id = request.path_params["issue_id"]
    bundle = _bundle_or_404(issue_id)
    if bundle is None:
        return _json_error("not found", 404)
    updated = sort_timeline_by_time(bundle)
    _notify_subscribers()
    return JSONResponse({"updated": updated})


async def api_patch_timeline(request: Request):
    issue_id = request.path_params["issue_id"]
    index_raw = request.path_params["timeline_index"]
    bundle = _bundle_or_404(issue_id)
    if bundle is None:
        return _json_error("not found", 404)
    index, idx_err = _parse_index_or_400(index_raw)
    if idx_err is not None:
        return idx_err
    updates, err = await _parse_json_object(request)
    if err is not None:
        return err
    assert updates is not None and index is not None
    if not updates:
        return Response(status_code=204)
    try:
        patch_timeline_item(bundle, index, updates)
    except ValueError as e:
        return _json_error(str(e), 400)
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
    bundle = _bundle_or_404(issue_id)
    if bundle is None:
        return _json_error("not found", 404)
    path = _safe_asset_file(bundle, asset_path)
    if path is None:
        return _json_error("not found", 404)
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
    Route("/api/statuses", endpoint=api_statuses, methods=["GET"]),
    Route("/api/postmortems", endpoint=api_list, methods=["GET"]),
    Route(
        "/api/postmortems/{issue_id}/export.zip",
        endpoint=api_export_zip,
        methods=["GET"],
    ),
    Route(
        "/api/postmortems/{issue_id}/actions",
        endpoint=api_post_actions,
        methods=["POST"],
    ),
    Route(
        "/api/postmortems/{issue_id}/actions/bulk-state",
        endpoint=api_bulk_action_state,
        methods=["PATCH"],
    ),
    Route(
        "/api/postmortems/{issue_id}/actions/reorder",
        endpoint=api_reorder_action,
        methods=["PATCH"],
    ),
    Route(
        "/api/postmortems/{issue_id}/actions/{action_index}",
        endpoint=api_patch_action,
        methods=["PATCH"],
    ),
    Route(
        "/api/postmortems/{issue_id}/timeline",
        endpoint=api_post_timeline,
        methods=["POST"],
    ),
    Route(
        "/api/postmortems/{issue_id}/timeline/reorder",
        endpoint=api_reorder_timeline,
        methods=["PATCH"],
    ),
    Route(
        "/api/postmortems/{issue_id}/timeline/sort-by-time",
        endpoint=api_sort_timeline_by_time,
        methods=["PATCH"],
    ),
    Route(
        "/api/postmortems/{issue_id}/timeline/{timeline_index}",
        endpoint=api_patch_timeline,
        methods=["PATCH"],
    ),
    Route(
        "/api/postmortems/{issue_id}/sections/{section}",
        endpoint=api_put_section,
        methods=["PUT"],
    ),
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
