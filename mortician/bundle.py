"""Incident bundle storage: YAML + Markdown on disk, canonical dict in memory."""

from __future__ import annotations

import os
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .templates import DEFAULT_POSTMORTEM
from .statuses import DEFAULT_STATUS

_INCIDENTS_DIR_ENV = "MORTICIAN_INCIDENTS_DIR"


def _require_incidents_dir_env() -> Path:
    """
    Require an explicit incidents directory for write operations.

    We intentionally do *not* allow creates to fall back to a repo-relative path,
    because in installed environments that can resolve under site-packages.
    """
    raw = (os.environ.get(_INCIDENTS_DIR_ENV) or "").strip()
    if not raw:
        raise RuntimeError(
            f"{_INCIDENTS_DIR_ENV} is not set.\n"
            f"Set it to the folder where incident bundles should be created, e.g.:\n"
            f"  export {_INCIDENTS_DIR_ENV}=/path/to/incidents   # bash/zsh\n"
            f"  setx {_INCIDENTS_DIR_ENV} \"C:\\path\\to\\incidents\"  # Windows\n"
        )
    return Path(raw)


def _resolve_incidents_dir() -> Path:
    """
    Resolve the incidents root in a shell-agnostic way.

    - Prefer env override: `MORTICIAN_INCIDENTS_DIR`
    - Search upward from CWD for an `incidents/` folder
    - Fallback to repo-relative (useful during development)
    """
    override = os.environ.get("MORTICIAN_INCIDENTS_DIR")
    if override:
        return Path(override)

    cur = Path.cwd()
    for _ in range(12):
        cand = cur / "incidents"
        if cand.is_dir():
            return cand
        if cur.parent == cur:
            break
        cur = cur.parent

    # Repo-relative fallback (dev/editable installs)
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "incidents"


INCIDENTS_DIR = _resolve_incidents_dir()
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

    candidate_meta_paths: List[Path] = []
    # Incidents stored directly under `incidents/<id>-<slug>/meta.yaml`
    candidate_meta_paths.extend(INCIDENTS_DIR.glob(f"*/{META_FILENAME}"))
    # Archived incidents under `incidents/old/<id>-<slug>/meta.yaml`
    candidate_meta_paths.extend(INCIDENTS_DIR.glob(f"old/*/{META_FILENAME}"))

    for meta_path in sorted(candidate_meta_paths):
        try:
            meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if meta.get("id") == issue_id:
            return meta_path.parent
    return None


def _bundle_path_is_under_incidents(bundle_path: Path) -> bool:
    """True if ``bundle_path`` resolves to a directory under ``INCIDENTS_DIR``."""
    try:
        child = bundle_path.resolve()
        root = INCIDENTS_DIR.resolve()
    except OSError:
        return False
    try:
        child.relative_to(root)
        return True
    except ValueError:
        pass
    # Windows: resolve() can differ (e.g. casing, symlinks) so relative_to fails.
    try:
        return os.path.commonpath([str(child), str(root)]) == str(root)
    except ValueError:
        return False


def delete_bundle_path(bundle_path: Path) -> bool:
    """
    Remove a bundle directory by explicit path (e.g. path returned from ``create_bundle``).

    Only deletes when the path resolves under ``INCIDENTS_DIR``. Returns True if removed.
    """
    if not bundle_path.is_dir():
        return False
    if not _bundle_path_is_under_incidents(bundle_path):
        return False
    shutil.rmtree(bundle_path)
    return True


def delete_incident_bundle(issue_id: str) -> bool:
    """
    Remove the on-disk bundle directory for ``issue_id``.

    Only deletes paths resolved under ``INCIDENTS_DIR`` (including ``old/``).
    Returns True if a directory was removed.
    """
    bundle = find_bundle_dir(issue_id)
    if bundle is None:
        return False
    return delete_bundle_path(bundle)


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
    # Require explicit env to avoid surprising writes under site-packages.
    env_dir = _require_incidents_dir_env()
    env_dir.mkdir(parents=True, exist_ok=True)
    name = _next_collision_suffix(issue_id, title)
    return env_dir / name


def list_bundle_dirs() -> List[Path]:
    if not INCIDENTS_DIR.is_dir():
        return []
    out_set = set()

    # Direct bundles: incidents/<bundle>/meta.yaml
    for meta_path in INCIDENTS_DIR.glob(f"*/{META_FILENAME}"):
        out_set.add(meta_path.parent)

    # Archived bundles: incidents/old/<bundle>/meta.yaml
    for meta_path in INCIDENTS_DIR.glob(f"old/*/{META_FILENAME}"):
        out_set.add(meta_path.parent)

    return sorted(out_set)


def list_incident_summaries() -> List[Dict[str, Any]]:
    """Lightweight rows for CLI list / dashboard."""
    rows: List[Dict[str, Any]] = []
    for bundle in list_bundle_dirs():
        meta = _read_meta(bundle)
        iid = meta.get("id")
        if not iid:
            continue
        # Absolute path for CLI list output / scripts.
        bundle_dir = str(bundle.resolve())
        unresolved_actions = _count_unresolved_actions(bundle)
        rows.append(
            {
                "id": iid,
                "title": meta.get("title", ""),
                "status": meta.get("status", ""),
                "date": meta.get("date", ""),
                "unresolved_actions": unresolved_actions,
                "bundle_dir": bundle_dir,
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


def _list_assets(bundle: Path) -> List[str]:
    assets_dir = bundle / ASSETS_DIRNAME
    if not assets_dir.is_dir():
        return []
    out: List[str] = []
    for path in sorted(assets_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(assets_dir)
        except ValueError:
            continue
        out.append(rel.as_posix())
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
SUB_IMPACT_AFFECTED = "Affected Services"
SUB_IMPACT_DURATION = "Duration of Outage"
SUB_IMPACT_BUSINESS = "Business Impact"


def default_impact_index_placeholder() -> str:
    """Impact section template for new incidents (### subsections, empty bodies)."""
    parts = [
        _md_h3_block(SUB_IMPACT_AFFECTED, ""),
        _md_h3_block(SUB_IMPACT_DURATION, ""),
        _md_h3_block(SUB_IMPACT_BUSINESS, ""),
    ]
    return "\n\n".join(parts)


def _md_h2_block(title: str, body: str) -> str:
    """Single ## section: one blank line after heading when body is non-empty."""
    b = (body or "").strip()
    if b:
        return f"## {title}\n\n{b}"
    return f"## {title}"


def _md_h3_block(subtitle: str, body: str) -> str:
    """Single ### section under Resolution or Impact."""
    b = (body or "").strip()
    if b:
        return f"### {subtitle}\n\n{b}"
    return f"### {subtitle}"


def _md_resolution_block(resolution: Dict[str, Any]) -> str:
    temp_fix = (resolution.get("temporary_fix") or "").strip()
    perm_fix = (resolution.get("permanent_fix") or "").strip()
    inner = "\n\n".join(
        [
            _md_h3_block(SUB_TEMP, temp_fix),
            _md_h3_block(SUB_PERM, perm_fix),
        ]
    )
    return f"## {H_RESOLUTION}\n\n{inner}"


def _parse_h3_subsection(body: str, subtitle: str) -> str:
    """Extract ### subtitle body until next ### heading or EOF."""
    if not body.strip():
        return ""
    lines = body.splitlines()
    target = f"### {subtitle}"
    start = None
    for i, line in enumerate(lines):
        if line.strip() == target:
            start = i + 1
            break
    if start is None:
        return ""
    out: List[str] = []
    for line in lines[start:]:
        if line.startswith("### "):
            break
        out.append(line)
    return "\n".join(out).strip()


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
    return _parse_h3_subsection(resolution_body, sub)


def _parse_resolution_subsections(resolution_body: str) -> Tuple[str, str]:
    # Determine whether the headings exist; we only apply the legacy
    # fallback when *neither* "### Temporary" nor "### Permanent" is present.
    lines = resolution_body.splitlines()
    has_temp = any(line.strip() == f"### {SUB_TEMP}" for line in lines)
    has_perm = any(line.strip() == f"### {SUB_PERM}" for line in lines)

    t = _parse_resolution_subsection(resolution_body, SUB_TEMP)
    p = _parse_resolution_subsection(resolution_body, SUB_PERM)

    if not has_temp and not has_perm and resolution_body.strip():
        # No ### subsections at all: treat whole block as temporary (legacy).
        return resolution_body.strip(), ""

    # Headings exist (even if their bodies are empty): keep them empty.
    return t, p


def build_index_md(
    incident_summary: str,
    impact_and_severity: Dict[str, Any],
    root_cause: str,
    resolution: Dict[str, Any],
    *,
    use_impact_placeholder: bool = False,
) -> str:
    """Build index.md from canonical dict fields."""
    if use_impact_placeholder:
        impact_body = default_impact_index_placeholder()
    else:
        impact_body = impact_and_severity.get("markdown") or _impact_from_legacy(
            impact_and_severity
        )
    impact_body = (impact_body or "").strip()

    blocks = [
        _md_h2_block(H_SUMMARY, incident_summary),
        _md_h2_block(H_IMPACT, impact_body),
        _md_h2_block(H_ROOT, root_cause),
        _md_resolution_block(resolution),
    ]
    return "\n\n".join(blocks).rstrip() + "\n"


def _impact_from_legacy(impact: Dict[str, Any]) -> str:
    a = (impact.get("affected_services") or "").strip()
    d = (impact.get("duration_of_outage") or "").strip()
    b = (impact.get("business_impact") or "").strip()
    if not a and not d and not b:
        return ""
    parts: List[str] = []
    if a:
        parts.append(_md_h3_block(SUB_IMPACT_AFFECTED, a))
    if d:
        parts.append(_md_h3_block(SUB_IMPACT_DURATION, d))
    if b:
        parts.append(_md_h3_block(SUB_IMPACT_BUSINESS, b))
    return "\n\n".join(parts)


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
    assets = _list_assets(bundle)

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
    data["assets"] = assets
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
        use_impact_placeholder=False,
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
    _require_incidents_dir_env()
    bundle = new_bundle_path(issue_id, title)
    if bundle.exists():
        raise ValueError(f"Directory already exists: {bundle}")

    data = DEFAULT_POSTMORTEM.copy()
    if initial:
        data.update(initial)
    data["overview"] = dict(data.get("overview") or {})
    data["overview"]["incident_title"] = title
    # `DEFAULT_POSTMORTEM` sets these to empty strings; `setdefault()` would not overwrite.
    # If the fields are empty, populate them for newly-created incidents.
    if not str(data["overview"].get("date") or "").strip():
        data["overview"]["date"] = str(datetime.now().date())
    if not str(data["overview"].get("time") or "").strip():
        data["overview"]["time"] = str(datetime.now().time())
    data["overview"].setdefault("status", DEFAULT_STATUS)
    data["overview"].setdefault("severity", "")

    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / ASSETS_DIRNAME).mkdir(exist_ok=True)

    meta = {
        "id": issue_id,
        "title": title,
        "status": data["overview"].get("status") or DEFAULT_STATUS,
        "severity": data["overview"].get("severity") or "",
        "owner": data.get("incident_owner") or "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "date": data["overview"].get("date") or "",
        "time": data["overview"].get("time") or "",
        "participants": data.get("incident_participants") or "",
    }
    _write_meta(bundle, meta)

    imp = data.get("impact_and_severity") or {}
    use_impact_ph = not (str(imp.get("markdown") or "").strip()) and not any(
        [
            (str(imp.get("affected_services") or "").strip()),
            (str(imp.get("duration_of_outage") or "").strip()),
            (str(imp.get("business_impact") or "").strip()),
        ]
    )
    index_md = build_index_md(
        data.get("incident_summary") or "",
        data.get("impact_and_severity") or {},
        data.get("root_cause") or "",
        data.get("resolution") or {},
        use_impact_placeholder=use_impact_ph,
    )
    (bundle / INDEX_FILENAME).write_text(index_md, encoding="utf-8")

    # Start with no timeline/action entries.
    # Guided mode overwrites these with user-provided entries; non-guide mode
    # should not persist placeholders in new bundles.
    _write_timeline(bundle, [])
    _write_actions(bundle, [])

    return bundle


def write_index_md_atomic(bundle: Path, content: str) -> None:
    """Write index.md atomically (temp file in bundle dir, then replace)."""
    write_text_atomic(bundle / INDEX_FILENAME, content)


def write_text_atomic(path: Path, content: str) -> None:
    """Write text atomically (temp file in the same directory, then replace)."""
    tmp = path.parent / f".{path.name}.tmp"
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


# URL slug -> single-field update for patch_index_md_section (dashboard API).
INDEX_SECTION_SLUGS = frozenset(
    {
        "summary",
        "impact",
        "impact_affected",
        "impact_duration",
        "impact_business",
        "root_cause",
        "resolution_temporary",
        "resolution_permanent",
    }
)


def patch_index_md_section(bundle: Path, section: str, body: str) -> None:
    """
    Replace one logical section of index.md and rewrite the file atomically.

    ``section`` must be a member of ``INDEX_SECTION_SLUGS``. Other YAML files
    in the bundle are not modified.
    """
    if section not in INDEX_SECTION_SLUGS:
        raise ValueError(f"unknown section: {section!r}")

    index_path = bundle / INDEX_FILENAME
    text = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""
    parsed = parse_index_md(text)
    body_str = body if isinstance(body, str) else str(body)

    if section == "summary":
        parsed["incident_summary"] = body_str
    elif section == "impact":
        parsed["impact_markdown"] = body_str
    elif section == "impact_affected":
        im = _parse_impact_subsections(parsed.get("impact_markdown") or "")
        im["affected_services"] = body_str
        parsed["impact_markdown"] = _build_impact_markdown(im)
    elif section == "impact_duration":
        im = _parse_impact_subsections(parsed.get("impact_markdown") or "")
        im["duration_of_outage"] = body_str
        parsed["impact_markdown"] = _build_impact_markdown(im)
    elif section == "impact_business":
        im = _parse_impact_subsections(parsed.get("impact_markdown") or "")
        im["business_impact"] = body_str
        parsed["impact_markdown"] = _build_impact_markdown(im)
    elif section == "root_cause":
        parsed["root_cause"] = body_str
    elif section == "resolution_temporary":
        parsed["resolution_temporary"] = body_str
    else:
        parsed["resolution_permanent"] = body_str

    impact = _impact_dict_from_markdown(parsed.get("impact_markdown") or "", None)
    resolution = {
        "temporary_fix": parsed.get("resolution_temporary") or "",
        "permanent_fix": parsed.get("resolution_permanent") or "",
    }
    new_md = build_index_md(
        parsed.get("incident_summary") or "",
        impact,
        parsed.get("root_cause") or "",
        resolution,
        use_impact_placeholder=False,
    )
    write_index_md_atomic(bundle, new_md)


def _parse_markdown_subsection(body: str, subtitle: str) -> str:
    return _parse_h3_subsection(body, subtitle)


def action_item_is_done(item: Dict[str, Any]) -> bool:
    return item.get("done") is True or item.get("completed") is True


def set_action_done_fields(item: Dict[str, Any], done: bool, *, preserve_completed: bool) -> None:
    item["done"] = bool(done)
    if preserve_completed:
        if "completed" in item:
            item["completed"] = bool(done)
    else:
        if "completed" in item:
            del item["completed"]


def _parse_impact_subsections(impact_md: str) -> Dict[str, str]:
    return {
        "affected_services": _parse_markdown_subsection(impact_md, SUB_IMPACT_AFFECTED),
        "duration_of_outage": _parse_markdown_subsection(impact_md, SUB_IMPACT_DURATION),
        "business_impact": _parse_markdown_subsection(impact_md, SUB_IMPACT_BUSINESS),
    }


def _build_impact_markdown(impact_fields: Dict[str, str]) -> str:
    return "\n\n".join(
        [
            _md_h3_block(SUB_IMPACT_AFFECTED, impact_fields.get("affected_services", "")),
            _md_h3_block(SUB_IMPACT_DURATION, impact_fields.get("duration_of_outage", "")),
            _md_h3_block(SUB_IMPACT_BUSINESS, impact_fields.get("business_impact", "")),
        ]
    )


# JSON merge keys for PATCH .../actions/{index} (dashboard API).
ACTION_ITEM_PATCH_KEYS = frozenset({"done", "completed", "task", "title", "owner", "due"})


def patch_action_item(bundle: Path, index: int, updates: Dict[str, Any]) -> None:
    """
    Merge ``updates`` into ``items[index]`` in actions.yaml and write the file.

    Raises ``ValueError`` for out-of-range index, unknown keys, or non-dict items.
    No-op if ``updates`` is empty.
    """
    if not updates:
        return
    bad = [k for k in updates if k not in ACTION_ITEM_PATCH_KEYS]
    if bad:
        raise ValueError("unknown field: " + ", ".join(repr(k) for k in bad))

    items = _read_actions(bundle)
    if index < 0 or index >= len(items):
        raise ValueError("action index out of range")
    item = items[index]
    if not isinstance(item, dict):
        raise ValueError("action item is not a mapping")

    for k, v in updates.items():
        if k == "done":
            set_action_done_fields(item, bool(v) if v is not None else False, preserve_completed=True)
        elif k == "completed":
            item["completed"] = bool(v) if v is not None else False
        else:
            item[k] = _coerce_simple(v)

    items[index] = {str(kk): _coerce_simple(vv) for kk, vv in item.items()}
    _write_actions(bundle, items)


def bulk_set_action_done(bundle: Path, done: bool) -> int:
    """Set done/completed state for all action rows. Returns updated count."""
    items = _read_actions(bundle)
    if not items:
        return 0
    updated = 0
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        set_action_done_fields(item, done, preserve_completed=True)
        items[i] = {str(kk): _coerce_simple(vv) for kk, vv in item.items()}
        updated += 1
    _write_actions(bundle, items)
    return updated


def reorder_action_item(bundle: Path, from_index: int, to_index: int) -> None:
    """Move one action row within actions.yaml."""
    items = _read_actions(bundle)
    if from_index < 0 or from_index >= len(items):
        raise ValueError("action index out of range")
    if to_index < 0 or to_index >= len(items):
        raise ValueError("target index out of range")
    if from_index == to_index:
        return
    row = items.pop(from_index)
    items.insert(to_index, row)
    _write_actions(bundle, items)


TIMELINE_ITEM_PATCH_KEYS = frozenset({"time", "action"})


def patch_timeline_item(bundle: Path, index: int, updates: Dict[str, Any]) -> None:
    """
    Merge ``updates`` into ``events[index]`` in timeline.yaml and write the file.

    Raises ``ValueError`` for out-of-range index, unknown keys, or non-dict items.
    No-op if ``updates`` is empty.
    """
    if not updates:
        return
    bad = [k for k in updates if k not in TIMELINE_ITEM_PATCH_KEYS]
    if bad:
        raise ValueError("unknown field: " + ", ".join(repr(k) for k in bad))

    events = _read_timeline(bundle)
    if index < 0 or index >= len(events):
        raise ValueError("timeline index out of range")
    event = events[index]
    if not isinstance(event, dict):
        raise ValueError("timeline event is not a mapping")

    for k, v in updates.items():
        event[k] = _coerce_simple(v)

    events[index] = {str(kk): _coerce_simple(vv) for kk, vv in event.items()}
    _write_timeline(bundle, events)


def reorder_timeline_item(bundle: Path, from_index: int, to_index: int) -> None:
    """Move one timeline row within timeline.yaml."""
    events = _read_timeline(bundle)
    if from_index < 0 or from_index >= len(events):
        raise ValueError("timeline index out of range")
    if to_index < 0 or to_index >= len(events):
        raise ValueError("target index out of range")
    if from_index == to_index:
        return
    row = events.pop(from_index)
    events.insert(to_index, row)
    _write_timeline(bundle, events)


def sort_timeline_by_time(bundle: Path) -> int:
    """
    Sort timeline events by parsed timestamp, preserving relative order for ties.

    Unparseable timestamps are placed after parseable entries and preserve
    their original relative order.
    """
    events = _read_timeline(bundle)
    if len(events) < 2:
        return 0

    def _parse_event_time(value: Any) -> Optional[datetime]:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%d %H:%M:%S UTC"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    indexed = list(enumerate(events))
    sorted_rows = sorted(
        indexed,
        key=lambda pair: (
            0 if _parse_event_time(pair[1].get("time")) is not None else 1,
            _parse_event_time(pair[1].get("time")) or datetime.max.replace(tzinfo=timezone.utc),
            pair[0],
        ),
    )
    new_events = [row for _, row in sorted_rows]
    if new_events == events:
        return 0
    _write_timeline(bundle, new_events)
    return len(new_events)


def _count_unresolved_actions(bundle: Path) -> int:
    items = _read_actions(bundle)
    total = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        if not action_item_is_done(item):
            total += 1
    return total


def append_action_row(
    bundle: Path,
    *,
    task: str,
    owner: str = "",
    due: str = "",
) -> None:
    """Append one checklist item to ``actions.yaml`` (same shape as CLI ``append_action_item``)."""
    t = (task or "").strip()
    if not t:
        raise ValueError("task is empty")
    items = _read_actions(bundle)
    item: Dict[str, Any] = {
        "task": t,
        "done": False,
        "owner": (owner or "").strip(),
        "due": (due or "").strip(),
    }
    items.append({str(k): _coerce_simple(v) for k, v in item.items()})
    _write_actions(bundle, items)


def append_timeline_row(
    bundle: Path,
    *,
    time: str,
    action: str,
) -> None:
    """Append one event row to ``timeline.yaml``."""
    t = (time or "").strip()
    a = (action or "").strip()
    if not t:
        raise ValueError("time is required")
    if not a:
        raise ValueError("action is required")
    events = _read_timeline(bundle)
    row: Dict[str, Any] = {
        "time": t,
        "action": a,
    }
    events.append({str(k): _coerce_simple(v) for k, v in row.items()})
    _write_timeline(bundle, events)
