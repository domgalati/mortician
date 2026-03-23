from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def _default_cache_dir() -> Path:
    """
    Resolve a user-writable cache directory in a shell-agnostic way.
    Works on WSL/Linux and Windows.
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "mortician"

    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "mortician"

    return Path.home() / ".cache" / "mortician"


def _state_path() -> Path:
    return _default_cache_dir() / "state.json"


def _read_state() -> Dict[str, Any]:
    p = _state_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        # Corrupt/invalid state should not block CLI usage.
        return {}


def _write_state(state: Dict[str, Any]) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def set_active_issue_id(issue_id: str) -> None:
    """Persist the active incident id for future CLI commands."""
    issue_id = (issue_id or "").strip()
    if not issue_id:
        raise ValueError("issue_id must be non-empty")
    state = _read_state()
    state["active_issue_id"] = issue_id
    _write_state(state)


def get_active_issue_id() -> Optional[str]:
    """Return the persisted active incident id, or None if not set."""
    state = _read_state()
    v = state.get("active_issue_id")
    if v is None:
        return None
    if not isinstance(v, str):
        return None
    v = v.strip()
    return v or None


def require_active_issue_id() -> str:
    """Get active issue id or raise a user-friendly error."""
    v = get_active_issue_id()
    if not v:
        raise RuntimeError(
            "No active incident selected. Run `mortician select <issue_id>` first."
        )
    return v


def clear_active_issue_id_if_matches(issue_id: str) -> None:
    """Drop persisted active id when it equals ``issue_id`` (e.g. after aborted create)."""
    issue_id = (issue_id or "").strip()
    if not issue_id:
        return
    state = _read_state()
    cur = state.get("active_issue_id")
    if isinstance(cur, str) and cur.strip() == issue_id:
        state.pop("active_issue_id", None)
        _write_state(state)

