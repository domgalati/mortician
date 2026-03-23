"""Incident bundle storage: YAML + Markdown on disk, canonical dict in memory."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .templates import DEFAULT_POSTMORTEM

INCIDENTS_DIR = Path("incidents")
TITLE_SLUG_MAX_LEN = 50

META_FILENAME = "meta.yaml"
INDEX_FILENAME = "index.md"
TIMELINE_FILENAME = "timeline.yaml"
ACTIONS_FILENAME = "actions.yaml"
ASSETS_DIRNAME = "assets"


class MorticianDumper(yaml.SafeDumper):
    """YAML dumper that uses literal block scalars for multi-line strings."""

    pass


def _str_representer(dumper: yaml.Dumper, data: str):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


MorticianDumper.add_representer(str, _str_representer)


def _yaml_dump(data: Any) -> str:
    return yaml.dump(
        data,
        Dumper=MorticianDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=1000,
    )


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def slug_suffix(title: str, max_len: int = TITLE_SLUG_MAX_LEN) -> str:
    s = _slugify(title or "")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s or "untitled"


def bundle_folder_name(issue_id: str, title: str) -> str:
    return f"{issue_id}-{slug_suffix(title)}"


def find_bundle_dir(issue_id: str) -> Optional[Path]:
    """Return the incident directory for ``issue_id`` if it exists."""
    if not INCIDENTS_DIR.is_dir():
        return None
    prefix = f"{issue_id}-"
    for path in sorted(INCIDENTS_DIR.iterdir()):
        if not path.is_dir() or not path.name.startswith(prefix):
            continue
        meta_path = path / META_FILENAME
        if not meta_path.is_file():
            continue
        try:
            meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if meta.get("id") == issue_id:
            return path
    return None


def _next_collision_suffix(issue_id: str, title: str) -> str:
    """If ``issue_id-title_slug`` exists for another id (should not happen), append -2, -3, ..."""
    base = bundle_folder_name(issue_id, title)
    candidate = base
    n = 2
    while (INCIDENTS_DIR / candidate).exists():
        existing = INCIDENTS_DIR / candidate
        meta_path = existing / META_FILENAME
        if meta_path.is_file():
            try:
                meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
            except Exception:
                meta = {}
            if meta.get("id") == issue_id:
                return candidate
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def new_bundle_path(issue_id: str, title: str) -> Path:
    """Compute a new bundle directory path for create; does not mkdir."""
    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    name = _next_collision_suffix(issue_id, title)
    return INCIDENTS_DIR / name


def list_bundle_dirs() -> List[Path]:
    if not INCIDENTS_DIR.is_dir():
        return []
    out: List[Path] = []
    for path in sorted(INCIDENTS_DIR.iterdir()):
        if path.is_dir() and (path / META_FILENAME).is_file():
            out.append(path)
    return out


def list_incident_summaries() -> List[Dict[str, Any]]:
    """Lightweight rows for CLI list / dashboard (id, title, status, date)."""
    rows: List[Dict[str, Any]] = []
    for bundle in list_bundle_dirs():
        meta = _read_meta(bundle)
        iid = meta.get("id")
        if not iid:
            continue
        rows.append(
            {
                "id": iid,
                "title": meta.get("title", ""),
                "status": meta.get("status", ""),
                "date": meta.get("date", ""),
            }
        )
    return rows


def _read_meta(bundle: Path) -> Dict[str, Any]:
    p = bundle / META_FILENAME
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _write_meta(bundle: Path, meta: Dict[str, Any]) -> None:
    (bundle / META_FILENAME).write_text(_yaml_dump(meta), encoding="utf-8")


def _coerce_simple(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _coerce_simple(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_coerce_simple(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def _coerce_event_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k): _coerce_simple(v) for k, v in d.items()}


def _read_timeline(bundle: Path) -> List[Dict[str, Any]]:
    p = bundle / TIMELINE_FILENAME
    if not p.is_file():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    events = data.get("events")
    if not isinstance(events, list):
        return []
    return [_coerce_event_dict(e) for e in events if isinstance(e, dict)]


def _write_timeline(bundle: Path, timeline: List[Dict[str, Any]]) -> None:
    (bundle / TIMELINE_FILENAME).write_text(
        _yaml_dump({"events": timeline}),
        encoding="utf-8",
    )


def _read_actions(bundle: Path) -> List[Dict[str, Any]]:
    p = bundle / ACTIONS_FILENAME
    if not p.is_file():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    items = data.get("items")
    if not isinstance(items, list):
        return []
    out = []
    for i in items:
        if not isinstance(i, dict):
            continue
        out.append({str(k): _coerce_simple(v) for k, v in i.items()})
    return out


def _write_actions(bundle: Path, items: List[Dict[str, Any]]) -> None:
    (bundle / ACTIONS_FILENAME).write_text(
        _yaml_dump({"items": items}),
        encoding="utf-8",
    )


# index.md section titles (level-2 headings)
H_SUMMARY = "Summary"
H_IMPACT = "Impact & Severity"
H_ROOT = "Root Cause"
H_RESOLUTION = "Resolution"
SUB_TEMP = "Temporary"
SUB_PERM = "Permanent"


def parse_index_md(text: str) -> Dict[str, str]:
    """Split index.md into summary, impact, root cause, resolution temp/perm bodies."""
    lines = text.splitlines()
    section_order = [H_SUMMARY, H_IMPACT, H_ROOT, H_RESOLUTION]
    headings = {s: None for s in section_order}
    for i, line in enumerate(lines):
        if line.startswith("## ") and not line.startswith("###"):
            title = line[3:].strip()
            if title in headings:
                headings[title] = i

    def slice_body(start_line: Optional[int], end_line: Optional[int]) -> str:
        if start_line is None:
            return ""
        a = start_line + 1
        b = end_line if end_line is not None else len(lines)
        chunk = lines[a:b]
        return "\n".join(chunk).strip()

    def next_h2(after: Optional[int]) -> Optional[int]:
        if after is None:
            return None
        for j in range(after + 1, len(lines)):
            if lines[j].startswith("## ") and not lines[j].startswith("###"):
                return j
        return None

    hs, hi, hr, hres = headings[H_SUMMARY], headings[H_IMPACT], headings[H_ROOT], headings[H_RESOLUTION]
    summary = slice_body(hs, next_h2(hs))
    impact = slice_body(hi, next_h2(hi))
    root_cause = slice_body(hr, next_h2(hr))

    res_start = hres
    res_body = slice_body(res_start, next_h2(res_start))
    temp_fix, perm_fix = _parse_resolution_subsections(res_body)

    return {
        "incident_summary": summary,
        "impact_markdown": impact,
        "root_cause": root_cause,
        "resolution_temporary": temp_fix,
        "resolution_permanent": perm_fix,
    }


def _parse_resolution_subsection(resolution_body: str, sub: str) -> str:
    """Extract ### Sub body until next ### or EOF."""
    if not resolution_body.strip():
        return ""
    lines = resolution_body.splitlines()
    target = f"### {sub}"
    start = None
    for i, line in enumerate(lines):
        if line.strip() == target:
            start = i + 1
            break
    if start is None:
        return ""
    buf: List[str] = []
    for line in lines[start:]:
        if line.startswith("### ") and line.strip() != target:
            break
        buf.append(line)
    return "\n".join(buf).strip()


def _parse_resolution_subsections(resolution_body: str) -> Tuple[str, str]:
    t = _parse_resolution_subsection(resolution_body, SUB_TEMP)
    p = _parse_resolution_subsection(resolution_body, SUB_PERM)
    if not t and not p and resolution_body.strip():
        # No ### subsections: treat whole block as temporary (legacy)
        return resolution_body.strip(), ""
    return t, p


def build_index_md(
    incident_summary: str,
    impact_and_severity: Dict[str, Any],
    root_cause: str,
    resolution: Dict[str, Any],
) -> str:
    """Build index.md from canonical dict fields."""
    impact_body = impact_and_severity.get("markdown") or _impact_from_legacy(impact_and_severity)
    temp_fix = resolution.get("temporary_fix") or ""
    perm_fix = resolution.get("permanent_fix") or ""

    parts = [
        f"## {H_SUMMARY}",
        incident_summary.strip(),
        "",
        f"## {H_IMPACT}",
        impact_body.strip(),
        "",
        f"## {H_ROOT}",
        root_cause.strip(),
        "",
        f"## {H_RESOLUTION}",
        "",
        f"### {SUB_TEMP}",
        temp_fix.strip(),
        "",
        f"### {SUB_PERM}",
        perm_fix.strip(),
        "",
    ]
    return "\n".join(parts).rstrip() + "\n"


def _impact_from_legacy(impact: Dict[str, Any]) -> str:
    a = (impact.get("affected_services") or "").strip()
    d = (impact.get("duration_of_outage") or "").strip()
    b = (impact.get("business_impact") or "").strip()
    if not a and not d and not b:
        return ""
    lines = []
    if a:
        lines.append(f"**Affected Services:** {a}")
    if d:
        lines.append(f"**Duration of Outage:** {d}")
    if b:
        lines.append(f"**Business Impact:** {b}")
    return "\n".join(lines)


def _impact_dict_from_markdown(impact_md: str, legacy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = {"affected_services": "", "duration_of_outage": "", "business_impact": ""}
    if legacy:
        base.update({k: legacy.get(k, "") for k in base})
    if impact_md.strip():
        base["markdown"] = impact_md.strip()
    return base


def load_postmortem(issue_id: str) -> Optional[Dict[str, Any]]:
    """Load incident bundle and return the canonical postmortem dict."""
    bundle = find_bundle_dir(issue_id)
    if bundle is None:
        return None

    meta = _read_meta(bundle)
    index_path = bundle / INDEX_FILENAME
    index_text = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""
    parsed = parse_index_md(index_text)

    timeline = _read_timeline(bundle)
    actions = _read_actions(bundle)

    participants = meta.get("participants", "")
    if isinstance(participants, list):
        participants_str = ", ".join(str(p) for p in participants)
    else:
        participants_str = str(participants or "")

    overview = {
        "incident_title": meta.get("title") or "",
        "date": meta.get("date") or "",
        "time": meta.get("time") or "",
        "status": meta.get("status") or "",
        "severity": meta.get("severity") or "",
    }

    impact = _impact_dict_from_markdown(parsed.get("impact_markdown") or "", None)

    data = DEFAULT_POSTMORTEM.copy()
    data["overview"] = overview
    data["incident_owner"] = meta.get("owner") or ""
    data["incident_participants"] = participants_str
    data["incident_summary"] = parsed.get("incident_summary") or ""
    data["impact_and_severity"] = impact
    data["root_cause"] = parsed.get("root_cause") or ""
    data["resolution"] = {
        "temporary_fix": parsed.get("resolution_temporary") or "",
        "permanent_fix": parsed.get("resolution_permanent") or "",
    }
    data["actions_and_follow_up"] = actions
    data["timeline"] = timeline
    return data


def save_postmortem(issue_id: str, data: Dict[str, Any]) -> None:
    """Persist canonical dict to the bundle directory."""
    bundle = find_bundle_dir(issue_id)
    if bundle is None:
        raise FileNotFoundError(f"No incident bundle for id: {issue_id}")

    data = dict(data)
    overview = data.get("overview") or {}
    impact = data.get("impact_and_severity") or {}
    resolution = data.get("resolution") or {}

    participants = data.get("incident_participants", "")
    if isinstance(participants, list):
        part_meta: Any = participants
    else:
        part_meta = participants

    existing = _read_meta(bundle)
    created_at = existing.get("created_at") or datetime.now().isoformat(timespec="seconds")

    meta = {
        "id": issue_id,
        "title": overview.get("incident_title") or "",
        "status": overview.get("status") or "",
        "severity": overview.get("severity") or "",
        "owner": data.get("incident_owner") or "",
        "created_at": created_at,
        "date": overview.get("date") or "",
        "time": overview.get("time") or "",
        "participants": part_meta,
    }

    index_md = build_index_md(
        data.get("incident_summary") or "",
        impact,
        data.get("root_cause") or "",
        resolution,
    )

    timeline = data.get("timeline") or []
    if not isinstance(timeline, list):
        timeline = []
    timeline_clean = [t for t in timeline if isinstance(t, dict)]

    actions = data.get("actions_and_follow_up") or []
    if not isinstance(actions, list):
        actions = []
    actions_clean = [a for a in actions if isinstance(a, dict)]

    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / ASSETS_DIRNAME).mkdir(exist_ok=True)

    _write_meta(bundle, meta)
    (bundle / INDEX_FILENAME).write_text(index_md, encoding="utf-8")
    _write_timeline(bundle, timeline_clean)
    _write_actions(bundle, actions_clean)


def create_bundle(issue_id: str, title: str, initial: Optional[Dict[str, Any]] = None) -> Path:
    """Create a new incident bundle directory with default files."""
    if find_bundle_dir(issue_id):
        raise ValueError(f"Postmortem '{issue_id}' already exists.")
    bundle = new_bundle_path(issue_id, title)
    if bundle.exists():
        raise ValueError(f"Directory already exists: {bundle}")

    data = DEFAULT_POSTMORTEM.copy()
    if initial:
        data.update(initial)
    data["overview"] = dict(data.get("overview") or {})
    data["overview"]["incident_title"] = title
    data["overview"].setdefault("date", str(datetime.now().date()))
    data["overview"].setdefault("time", str(datetime.now().time()))
    data["overview"].setdefault("status", "Unresolved")
    data["overview"].setdefault("severity", "")

    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / ASSETS_DIRNAME).mkdir(exist_ok=True)

    meta = {
        "id": issue_id,
        "title": title,
        "status": data["overview"].get("status") or "Unresolved",
        "severity": data["overview"].get("severity") or "",
        "owner": data.get("incident_owner") or "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "date": data["overview"].get("date") or "",
        "time": data["overview"].get("time") or "",
        "participants": data.get("incident_participants") or "",
    }
    _write_meta(bundle, meta)

    index_md = build_index_md(
        data.get("incident_summary") or "",
        data.get("impact_and_severity") or {},
        data.get("root_cause") or "",
        data.get("resolution") or {},
    )
    (bundle / INDEX_FILENAME).write_text(index_md, encoding="utf-8")
    _write_timeline(bundle, data.get("timeline") or [])
    _write_actions(bundle, data.get("actions_and_follow_up") or [])

    return bundle


def write_index_md_atomic(bundle: Path, content: str) -> None:
    """Write index.md atomically (temp file in bundle dir, then replace)."""
    path = bundle / INDEX_FILENAME
    tmp = bundle / f".{INDEX_FILENAME}.tmp"
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
