from __future__ import annotations

import copy
import os
import re
import socket
import shlex
import sys
import subprocess
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .bundle import (
    INCIDENTS_DIR,
    create_bundle,
    find_bundle_dir,
    load_postmortem as _load_postmortem_bundle,
    save_postmortem as _save_postmortem_bundle,
    write_index_md_atomic,
)
from .templates import DEFAULT_POSTMORTEM

INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)


def default_timeline_timestamp() -> str:
    """Default timeline event time (UTC, human-readable)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _merge_postmortem_dict(base, incoming):
    """Merge incoming dict into base (nested dicts merge; lists and scalars replace)."""
    for k, v in incoming.items():
        if (
            k in base
            and isinstance(base[k], dict)
            and isinstance(v, dict)
        ):
            _merge_postmortem_dict(base[k], v)
        else:
            base[k] = v


def load_postmortem(issue_id):
    """Load a postmortem from an incident bundle."""
    return _load_postmortem_bundle(issue_id)


def save_postmortem(issue_id, data):
    """Persist a postmortem dict to the incident bundle."""
    _save_postmortem_bundle(issue_id, data)


def print_create_followup(issue_id: str) -> None:
    """After create, suggest next steps."""
    bundle = find_bundle_dir(issue_id)
    path_hint = f"\n  Bundle: {bundle}" if bundle else ""
    print(
        f"\nNext steps:{path_hint}\n"
        f"  mortician select {issue_id}  # set active incident\n"
        f"  mortician add --action \"…\"   # timeline (or pipe / omit --action for editor)\n"
        f"  mortician action add --task \"…\"   # checklist item in actions.yaml\n"
        f"  mortician edit --summary \"…\" --status …\n"
        f"  mortician serve   # launch browser dashboard\n"
        f"  Or edit index.md / timeline.yaml / actions.yaml under the bundle folder.\n"
    )


def create_postmortem(title, smart_id_generator) -> Tuple[str, Path]:
    """Create a new incident bundle. Returns ``(issue_id, bundle_dir_path)``."""
    issue_id = smart_id_generator(title)
    if find_bundle_dir(issue_id):
        raise ValueError(f"Postmortem '{issue_id}' already exists.")

    bundle_path = create_bundle(issue_id, title)
    print(f"Incident created with id: '{issue_id}' (from title).")
    return issue_id, bundle_path


def _read_multiline_block(heading: str) -> str:
    """Read lines until a blank line; strip trailing newlines."""
    print(heading)
    print("(Enter a blank line when finished.)")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _read_multiline_block_default(heading: str, default_value: Optional[str]) -> str:
    """Read lines until a blank line; return default if first line is blank."""
    print(heading)
    if default_value is not None and str(default_value).strip():
        print("(Press Enter on an empty first line to accept the default.)")
        print("Default:")
        print(default_value)
    else:
        print("(Enter a blank line when finished.)")

    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "":
            break
        lines.append(line)

    user_text = "\n".join(lines).strip()
    if not user_text and default_value is not None:
        return str(default_value).strip()
    return user_text


def _inject_variable_tokens(text: str, token_values: Dict[str, str]) -> str:
    """Replace $date/$utc/$host tokens with computed values."""
    out = text or ""
    for token, value in token_values.items():
        out = out.replace(token, value)
    return out


def _questionary_module():
    try:
        import questionary  # type: ignore[import-untyped]
    except ImportError:
        return None
    return questionary


def _get_editor_command() -> Sequence[str]:
    """Resolve $EDITOR/$VISUAL into an argv list, with a safe fallback."""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if editor:
        # Allow things like: code --wait
        return shlex.split(editor)

    for candidate in ("vi", "nano"):
        if shutil.which(candidate):
            return [candidate]
    raise RuntimeError(
        "No editor configured. Set $EDITOR (preferred) or install `vi`/`nano`."
    )


def _edit_text_in_editor(initial_text: str, *, field_label: str) -> str:
    """Open $EDITOR for a single text value and return the edited content."""
    editor_cmd = list(_get_editor_command())

    # Use a temp file so arbitrary editors work consistently.
    tmp_path = None
    tty_in = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            tmp_path = f.name
            f.write(initial_text or "")
            f.flush()

        # If this CLI is being driven via a pipe (e.g. `echo ... | mortician add`),
        # the editor's stdin may be the closed/EOF'd pipe, which can make vim
        # fall back to non-interactive/Ex behavior. Prefer the real terminal
        # input when available.
        # Subprocess inherits the parent's file descriptor 0, not Python's
        # current `sys.stdin` object. So we check fd 0 specifically.
        if not os.isatty(0):
            tty_path = "/dev/tty" if os.name != "nt" else "CONIN$"
            try:
                tty_in = open(tty_path, "r", encoding="utf-8")
                subprocess.check_call(editor_cmd + [tmp_path], stdin=tty_in)
            except Exception:
                subprocess.check_call(editor_cmd + [tmp_path])
        else:
            subprocess.check_call(editor_cmd + [tmp_path])
        edited = Path(tmp_path).read_text(encoding="utf-8")
        return edited
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass
        if tty_in is not None:
            try:
                tty_in.close()
            except Exception:
                pass


def _get_nested(d: Dict[str, Any], path: Sequence[str]) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _set_nested(d: Dict[str, Any], path: Sequence[str], value: Any) -> None:
    cur: Any = d
    for key in path[:-1]:
        if key not in cur or not isinstance(cur[key], dict):
            cur[key] = {}
        cur = cur[key]
    cur[path[-1]] = value


def _write_text_atomic(path: Path, content: str) -> None:
    """Write text atomically via tmp+replace (best-effort cross-platform)."""
    tmp = path.parent / f".{path.name}.tmp"
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _combine_bundle_files_for_editor(
    file_texts: Dict[str, str], file_order: Sequence[str]
) -> str:
    """
    Combine multiple bundle files into one editable document.

    We only roundtrip canonical bundle files (not arbitrary extras).
    """
    start = "MORTICIAN_BUNDLE_FILE_START:"
    end = "MORTICIAN_BUNDLE_FILE_END:"

    parts: List[str] = []
    parts.append(
        "# Mortician bundle editor (one file per marker block)\n"
        "# Edit the content between START/END markers. Markers must remain unchanged.\n"
    )
    for fname in file_order:
        parts.append(f"{start}{fname}")
        parts.append(file_texts.get(fname, ""))
        parts.append(f"{end}{fname}")
        parts.append("")  # spacer line between blocks
    return "\n".join(parts).rstrip() + "\n"


def _parse_combined_bundle_editor_text(
    text: str, file_order: Sequence[str]
) -> Dict[str, str]:
    """Parse combined editor doc back into canonical bundle files by markers."""
    start = "MORTICIAN_BUNDLE_FILE_START:"
    end = "MORTICIAN_BUNDLE_FILE_END:"

    lines = text.splitlines()
    out: Dict[str, str] = {}

    scan_from = 0
    for fname in file_order:
        start_marker = f"{start}{fname}"
        end_marker = f"{end}{fname}"

        try:
            start_idx = next(
                i for i in range(scan_from, len(lines)) if lines[i].strip() == start_marker
            )
        except StopIteration:
            raise ValueError(f"Missing start marker for {fname!r}: {start_marker!r}")

        try:
            end_idx = next(
                i
                for i in range(start_idx + 1, len(lines))
                if lines[i].strip() == end_marker
            )
        except StopIteration:
            raise ValueError(f"Missing end marker for {fname!r}: {end_marker!r}")

        if end_idx < start_idx:
            raise ValueError(f"Invalid marker ordering for {fname!r}")

        content_lines = lines[start_idx + 1 : end_idx]
        out[fname] = "\n".join(content_lines)

        scan_from = end_idx + 1

    return out


def _extract_impact_legacy_fields_from_markdown(
    impact_markdown: str,
) -> Dict[str, str]:
    """
    Best-effort extraction of legacy impact fields from `impact_and_severity.markdown`.

    The UI/dashboard renders `markdown` verbatim, but our CLI required-field logic
    works on legacy fields. This helper lets us derive:
      - affected_services
      - duration_of_outage
      - business_impact

    Expected (by `build_index_md()`):
      - **Affected Services:** <text> (legacy one-line)
      - ### Affected Services / ### Duration of Outage / ### Business Impact
    """
    md = (impact_markdown or "").strip()
    out = {
        "affected_services": "",
        "duration_of_outage": "",
        "business_impact": "",
    }
    if not md:
        return out

    # section capture (until next ### heading)
    def extract_section(heading: str) -> str:
        pattern = (
            r"^###\s*"
            + re.escape(heading)
            + r"\s*$"  # exact heading line
            + r"(?P<body>.*?)(?=^###\s*|\Z)"
        )
        m2 = re.search(pattern, md, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
        if not m2:
            return ""
        body = (m2.group("body") or "").strip()
        return body

    # affected services: "**Affected Services:** <line>"
    m = re.search(
        r"\*\*Affected Services:\*\*\s*(?P<v>[^\n\r]+)",
        md,
        flags=re.IGNORECASE,
    )
    if m:
        out["affected_services"] = (m.group("v") or "").strip()

    aff_heading = extract_section("Affected Services")
    if aff_heading:
        out["affected_services"] = aff_heading

    out["duration_of_outage"] = extract_section("Duration of Outage")
    out["business_impact"] = extract_section("Business Impact")
    return out


def coalesce_impact_fields(data: Dict[str, Any]) -> None:
    """
    If legacy impact fields are populated, drop markdown so save uses legacy path.

    Avoids stale create-time placeholder markdown after guided merge fills legacy keys.
    """
    imp = data.get("impact_and_severity")
    if not isinstance(imp, dict):
        return
    md = imp.get("markdown")
    if not isinstance(md, str) or not md.strip():
        return
    a = (imp.get("affected_services") or "").strip()
    d = (imp.get("duration_of_outage") or "").strip()
    b = (imp.get("business_impact") or "").strip()
    if a or d or b:
        imp.pop("markdown", None)


def merge_and_save_postmortem(issue_id: str, patch: Dict[str, Any]) -> None:
    """Deep-merge a patch dict into the incident and persist (e.g. create --guide)."""
    data = load_postmortem(issue_id)
    if data is None:
        print(f"No postmortem found for issue: {issue_id}")
        return
    _merge_postmortem_dict(data, patch)
    coalesce_impact_fields(data)
    save_postmortem(issue_id, data)
    print(f"Postmortem '{issue_id}' updated successfully.")


def edit_postmortem_stateful(issue_id: str, args: Any, *, EDITOR_SENTINEL: str) -> None:
    """
    Stateful/editor-driven edit operation.

    For each supported flag:
      - not provided => unchanged
      - provided with no value (argparser const) => open $EDITOR to update value
      - provided with a value => overwrite value
    """
    data = load_postmortem(issue_id)
    if data is None:
        print(f"No postmortem found for issue: {issue_id}")
        return

    no_input = bool(getattr(args, "no_input", False))

    # If the user ran `mortician edit` with no edit flags, open the entire incident bundle.
    edit_field_values = [
        getattr(args, "status", None),
        getattr(args, "severity", None),
        getattr(args, "owner", None),
        getattr(args, "participants", None),
        getattr(args, "summary", None),
        getattr(args, "root_cause", None),
        getattr(args, "affected_services", None),
        getattr(args, "duration_of_outage", None),
        getattr(args, "business_impact", None),
        getattr(args, "temp_fix", None),
        getattr(args, "perm_fix", None),
    ]
    add_entry_value = getattr(args, "add_entry", None)
    if (not any(v is not None for v in edit_field_values)) and not add_entry_value:
        bundle_dir = find_bundle_dir(issue_id)
        if bundle_dir is None:
            print(f"No incident bundle found for id: {issue_id}")
            return

        bundle_files = ["meta.yaml", "index.md", "timeline.yaml", "actions.yaml"]
        file_texts: Dict[str, str] = {}
        for fname in bundle_files:
            p = bundle_dir / fname
            file_texts[fname] = p.read_text(encoding="utf-8") if p.is_file() else ""

        combined = _combine_bundle_files_for_editor(file_texts, bundle_files)
        edited = _edit_text_in_editor(combined, field_label="incident bundle")

        parsed: Dict[str, str]
        try:
            parsed = _parse_combined_bundle_editor_text(edited, bundle_files)
        except ValueError as e:
            raise RuntimeError(str(e))

        # Write back canonical files (unknown extra files remain untouched).
        write_index_md_atomic(bundle_dir, parsed["index.md"])
        for yaml_name in ("meta.yaml", "timeline.yaml", "actions.yaml"):
            _write_text_atomic(bundle_dir / yaml_name, parsed[yaml_name])

        print(f"Postmortem '{issue_id}' updated successfully.")
        return

    updates: Dict[str, Any] = {}

    # When updating legacy impact subfields, clear markdown so `save_postmortem()` uses
    # `affected_services`/`duration_of_outage`/`business_impact` instead of `impact_and_severity.markdown`.
    legacy_impact_fields = {"affected_services", "duration_of_outage", "business_impact"}

    # If impact is stored as markdown, derive legacy fields so we don't lose them when
    # switching to legacy serialization (i.e., when we clear `impact_and_severity.markdown`).
    impact_markdown_data = _get_nested(data, ["impact_and_severity", "markdown"])
    impact_markdown_data_has = (
        isinstance(impact_markdown_data, str) and impact_markdown_data.strip()
    )
    derived_impact_data: Dict[str, str] = {}
    if impact_markdown_data_has:
        derived_impact_data = _extract_impact_legacy_fields_from_markdown(
            str(impact_markdown_data)
        )

    def maybe_update(flag_value: Optional[str], path: Sequence[str], *, label: str) -> None:
        if flag_value is None:
            return
        if flag_value == EDITOR_SENTINEL:
            if no_input:
                raise RuntimeError(f"{label}: editor mode disabled with --no-input; pass a value.")
            current = _get_nested(data, path)
            edited = _edit_text_in_editor(str(current or ""), field_label=label)
            _set_nested(updates, path, edited.strip())
            if (
                len(path) == 2
                and path[0] == "impact_and_severity"
                and path[1] in legacy_impact_fields
            ):
                # Preserve other impact fields from markdown when switching serialization.
                if derived_impact_data:
                    for k in legacy_impact_fields:
                        if _get_nested(updates, ["impact_and_severity", k]) is None:
                            _set_nested(
                                updates,
                                ["impact_and_severity", k],
                                derived_impact_data.get(k, ""),
                            )
                _set_nested(updates, ["impact_and_severity", "markdown"], "")
            return

        # Normal value overwrite
        _set_nested(updates, path, str(flag_value).strip())
        if (
            len(path) == 2
            and path[0] == "impact_and_severity"
            and path[1] in legacy_impact_fields
        ):
            # Preserve other impact fields from markdown when switching serialization.
            if derived_impact_data:
                for k in legacy_impact_fields:
                    if _get_nested(updates, ["impact_and_severity", k]) is None:
                        _set_nested(
                            updates,
                            ["impact_and_severity", k],
                            derived_impact_data.get(k, ""),
                        )
            _set_nested(updates, ["impact_and_severity", "markdown"], "")

    # Overview fields
    status_value: Optional[str] = None
    status_was_set = False
    if getattr(args, "status", None) is not None:
        status_raw = getattr(args, "status")
        status_was_set = True
        if status_raw == EDITOR_SENTINEL:
            if no_input:
                raise RuntimeError("status: editor mode disabled with --no-input; pass a value.")
            current = _get_nested(data, ["overview", "status"]) or ""
            edited = _edit_text_in_editor(str(current), field_label="status")
            status_candidate = edited.strip()
        else:
            status_candidate = str(status_raw).strip()

        normalized = status_candidate.lower()
        status_map = {
            "unresolved": "Unresolved",
            "temporary resolution": "Temporary Resolution",
            "temporary_resolution": "Temporary Resolution",
            "temporary-resolution": "Temporary Resolution",
            "resolved": "Resolved",
        }
        if normalized in status_map:
            status_value = status_map[normalized]
        else:
            raise ValueError("status must be one of: Unresolved, Temporary Resolution, Resolved")
        _set_nested(updates, ["overview", "status"], status_value)

    maybe_update(getattr(args, "severity", None), ["overview", "severity"], label="severity")

    # Identity fields
    maybe_update(getattr(args, "owner", None), ["incident_owner"], label="owner")
    maybe_update(
        getattr(args, "participants", None), ["incident_participants"], label="participants"
    )
    maybe_update(getattr(args, "summary", None), ["incident_summary"], label="summary")
    maybe_update(getattr(args, "root_cause", None), ["root_cause"], label="root cause")

    # Impact fields
    maybe_update(
        getattr(args, "affected_services", None),
        ["impact_and_severity", "affected_services"],
        label="affected services",
    )
    maybe_update(
        getattr(args, "duration_of_outage", None),
        ["impact_and_severity", "duration_of_outage"],
        label="duration",
    )
    maybe_update(
        getattr(args, "business_impact", None),
        ["impact_and_severity", "business_impact"],
        label="business impact",
    )

    # Resolution fields
    maybe_update(
        getattr(args, "temp_fix", None), ["resolution", "temporary_fix"], label="temp fix"
    )
    maybe_update(
        getattr(args, "perm_fix", None), ["resolution", "permanent_fix"], label="perm fix"
    )

    # If the user transitions to "Resolved", ensure required fields are present.
    if status_was_set and status_value == "Resolved":
        # TODO: once mortician has a config file, make the "Resolved required fields"
        # list configurable per deployment/teams.
        required_candidates: List[tuple[Sequence[str], str]] = [
            (["root_cause"], "root cause"),
            (["resolution", "permanent_fix"], "permanent fix"),
            (["impact_and_severity", "affected_services"], "affected services"),
            (["impact_and_severity", "duration_of_outage"], "duration of outage"),
            (["impact_and_severity", "business_impact"], "business impact"),
        ]

        preview = copy.deepcopy(data)
        if updates:
            _merge_postmortem_dict(preview, updates)

        impact_markdown = _get_nested(preview, ["impact_and_severity", "markdown"])
        impact_markdown_has = isinstance(impact_markdown, str) and impact_markdown.strip()
        derived_impact: Dict[str, str] = {}

        def _value_is_empty(v: Any) -> bool:
            if v is None:
                return True
            if isinstance(v, str):
                return not v.strip()
            return False

        if impact_markdown_has:
            # Derive legacy impact fields from markdown so missing duration/business
            # still count as empty for required-field prompting.
            derived_impact = _extract_impact_legacy_fields_from_markdown(
                str(impact_markdown)
            )
            for k in legacy_impact_fields:
                _set_nested(preview, ["impact_and_severity", k], derived_impact.get(k, ""))

        def _candidate_is_empty(path: Sequence[str]) -> bool:
            return _value_is_empty(_get_nested(preview, path))

        empty_candidates = [
            (path, label)
            for path, label in required_candidates
            if _candidate_is_empty(path)
        ]

        if no_input:
            missing_labels = [label for _path, label in empty_candidates]
            if missing_labels:
                raise RuntimeError(
                    "When setting status to 'Resolved', these fields must be non-empty "
                    f"(missing: {', '.join(missing_labels)})."
                )
        else:
            selected_required: List[tuple[Sequence[str], str]] = []
            for path, label in empty_candidates:
                require_it = _prompt_yes_no_default(
                    f"'{label}' is empty. Require it for Resolved?",
                    default_yes=True,
                )
                if require_it:
                    selected_required.append((path, label))

            for path, label in selected_required:
                current = _get_nested(preview, path) or ""
                edited = _edit_text_in_editor(str(current), field_label=label).strip()
                if not edited:
                    raise RuntimeError(f"'{label}' is required for Resolved and cannot be empty.")

                _set_nested(updates, path, edited)
                if (
                    len(path) == 2
                    and path[0] == "impact_and_severity"
                    and path[1] in legacy_impact_fields
                ):
                    # Preserve other impact fields from markdown when switching serialization.
                    if derived_impact:
                        for k in legacy_impact_fields:
                            if _get_nested(updates, ["impact_and_severity", k]) is None:
                                _set_nested(
                                    updates,
                                    ["impact_and_severity", k],
                                    derived_impact.get(k, ""),
                                )
                    _set_nested(updates, ["impact_and_severity", "markdown"], "")
                _set_nested(preview, path, edited)

    # Timeline append (back-compat)
    if getattr(args, "add_entry", None):
        entry: Dict[str, Any] = {}
        for kv in args.add_entry:
            if "=" not in kv:
                print(f"Warning: skipping timeline fragment (expected KEY=VALUE): {kv!r}")
                continue
            k, v = kv.split("=", 1)
            entry[k.strip()] = v
        if entry:
            data.setdefault("timeline", [])
            data["timeline"].append(entry)

    # Merge and persist
    if updates:
        _merge_postmortem_dict(data, updates)
    save_postmortem(issue_id, data)
    print(f"Postmortem '{issue_id}' updated successfully.")


def _prompt_duration_of_outage(q: Any) -> str:
    """Duration: questionary presets or plain input."""
    if q is not None:
        try:
            choice = q.select(
                "Duration of outage:",
                choices=[
                    "15m",
                    "1h",
                    "4h",
                    "Custom (type below)",
                    "Skip (leave blank)",
                ],
            ).ask()
            if choice is None or choice == "Skip (leave blank)":
                return ""
            if choice == "Custom (type below)":
                custom = q.text("Duration (free text):").ask()
                return (custom or "").strip()
            return choice
        except (EOFError, KeyboardInterrupt):
            print()
            return ""
    return input("Duration of outage: ").strip()


def _prompt_timeline_time(q: Any, default_ts: str) -> str:
    if q is not None:
        try:
            now_label = f"Now ({default_ts})"
            choice = q.select(
                "Time for this entry:",
                choices=[now_label, "Enter manually"],
            ).ask()
            if choice is None or choice == now_label:
                return default_ts
            manual = q.text("Time:", default=default_ts).ask()
            return (manual or default_ts).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return default_ts
    t_in = input(f"Time [{default_ts}]: ").strip()
    return t_in if t_in else default_ts


def _prompt_yes_no(prompt: str) -> bool:
    while True:
        val = input(prompt).strip().lower()
        if val in ("y", "yes"):
            return True
        if val in ("n", "no"):
            return False
        print("Please enter y or n.")


def _prompt_yes_no_default(prompt: str, *, default_yes: bool) -> bool:
    """
    Prompt yes/no with an implicit default on empty input.

    Used for "field is empty; require it?" decisions.
    """
    hint = "Y/n" if default_yes else "y/N"
    while True:
        val = input(f"{prompt} [{hint}]: ").strip().lower()
        if not val:
            return default_yes
        if val in ("y", "yes"):
            return True
        if val in ("n", "no"):
            return False
        print("Please enter y or n.")


def guided_input():
    """Interactive prompt for postmortem creation (live-incident friendly order)."""
    data = copy.deepcopy(DEFAULT_POSTMORTEM)
    q = _questionary_module()

    # Stable token values for this guided session.
    host = socket.gethostname()
    local_date = datetime.now().date().isoformat()
    utc_iso = datetime.now(timezone.utc).isoformat()
    token_values = {
        "$date": local_date,
        "$utc": utc_iso,
        "$host": host,
    }

    print("\n=== Guided incident setup ===")

    data["incident_owner"] = input("Incident owner: ").strip()
    raw_parts = input("Participants (comma-separated, optional): ").strip()
    data["incident_participants"] = [p.strip() for p in raw_parts.split(",") if p.strip()]

    print()
    print("--- Incident summary ---")
    print(
        "Short narrative of what is going on (saved as Markdown in the bundle). "
        "You can use placeholders $date, $utc, and $host; they are replaced when saved with: "
        f"{local_date}, {utc_iso}, {host}."
    )
    summary_template = "Investigating issue on $host which started on $date (UTC: $utc)."
    summary_default = _inject_variable_tokens(summary_template, token_values)
    summary_raw = _read_multiline_block_default(
        "Incident summary (Markdown ok):",
        default_value=summary_default,
    )
    data["incident_summary"] = _inject_variable_tokens(summary_raw, token_values)
    incident_ongoing = _prompt_yes_no("Is the incident still ongoing? (y/n): ")

    print("\n=== Impact & severity (optional; blank lines skip) ===")
    data["impact_and_severity"]["affected_services"] = input("Affected services: ").strip()
    if incident_ongoing:
        # During a live incident, don't force duration/business impact answers.
        data["impact_and_severity"]["duration_of_outage"] = ""
        data["impact_and_severity"]["business_impact"] = ""
    else:
        data["impact_and_severity"]["duration_of_outage"] = _prompt_duration_of_outage(q)
        data["impact_and_severity"]["business_impact"] = input("Business impact: ").strip()

    sev = input("Severity label (e.g. P1, SEV-2; optional): ").strip()
    if sev:
        data["overview"]["severity"] = sev

    print("\n=== Timeline (while the incident is unfolding) ===")
    while True:
        tl_choice = input("Add a timeline entry now? (y/n): ").strip().lower()
        if tl_choice == "y":
            t_default = default_timeline_timestamp()
            time_val = _prompt_timeline_time(q, t_default)
            action = _read_multiline_block("What happened? (Markdown ok):")
            if action:
                data["timeline"].append({"time": time_val, "action": action})
            another = input("Add another timeline entry? (y/n): ").strip().lower()
            if another != "y":
                break
        elif tl_choice == "n":
            break
        else:
            print("Please enter y or n.")

    if incident_ongoing:
        data["overview"]["status"] = "Unresolved"
        print("\nIncident marked as Unresolved (ongoing). Skipping resolution prompts for now.")
    else:
        print("\n=== Analysis (optional during live response) ===")
        rc = input("Root cause (optional; Enter to skip for now): ").strip()
        data["root_cause"] = rc

        while True:
            print("\n=== Status ===")
            print("1. Unresolved")
            print("2. Temporary resolution")
            print("3. Resolved")
            status_choice = input("Enter choice (1-3): ").strip()
            if status_choice == "1":
                data["overview"]["status"] = "Unresolved"
                break
            if status_choice == "2":
                data["overview"]["status"] = "Temporary Resolution"
                data["resolution"]["temporary_fix"] = input("Temporary fix / mitigation: ").strip()
                break
            if status_choice == "3":
                data["overview"]["status"] = "Resolved"
                data["resolution"]["permanent_fix"] = input("Permanent fix: ").strip()
                break
            print("Invalid choice. Please select 1, 2, or 3.")

    # Minimal overview so merge does not clobber title/date/time from the bundle.
    overview_out = {}
    st = (data.get("overview") or {}).get("status", "")
    if isinstance(st, str) and st.strip():
        overview_out["status"] = st.strip()
    sev = (data.get("overview") or {}).get("severity", "")
    if isinstance(sev, str) and sev.strip():
        overview_out["severity"] = sev.strip()
    data["overview"] = overview_out

    return data


def _action_item_is_done(item: Dict[str, Any]) -> bool:
    if item.get("done") is True:
        return True
    if item.get("completed") is True:
        return True
    return False


def append_action_item(
    issue_id: str,
    *,
    task: str,
    owner: str = "",
    due: str = "",
) -> int:
    """Append one checklist item to actions.yaml. Returns 0 on success."""
    data = load_postmortem(issue_id)
    if data is None:
        print(f"No postmortem found for issue: {issue_id}", file=sys.stderr)
        return 1
    t = (task or "").strip()
    if not t:
        print("Error: task text is empty (use --task or pipe stdin).", file=sys.stderr)
        return 1
    item: Dict[str, Any] = {
        "task": t,
        "done": False,
        "owner": (owner or "").strip(),
        "due": (due or "").strip(),
    }
    data.setdefault("actions_and_follow_up", [])
    data["actions_and_follow_up"].append(item)
    save_postmortem(issue_id, data)
    print(f"Action item added to '{issue_id}'.")
    return 0


def append_action_item_interactive(
    issue_id: str,
    *,
    task: Optional[str] = None,
    owner: Optional[str] = None,
    due: Optional[str] = None,
) -> int:
    """Add follow-up item; read task from stdin when piped and ``--task`` omitted."""
    piped = (task is None) and (not sys.stdin.isatty())
    stdin_text = ""
    if piped:
        stdin_text = (sys.stdin.read() or "").strip()

    orig_stdin = sys.stdin
    tty_in = None
    try:
        if piped:
            tty_path = "/dev/tty" if os.name != "nt" else "CONIN$"
            try:
                tty_in = open(tty_path, "r", encoding="utf-8")
                sys.stdin = tty_in
            except Exception:
                sys.stdin = orig_stdin

        if task is not None:
            t_val = task.strip()
        elif piped:
            t_val = stdin_text
        else:
            t_val = input("Task description: ").strip()

        if not t_val:
            print("Error: task text is empty (use --task or pipe stdin).", file=sys.stderr)
            return 1

        # With explicit --task or piped task, default owner/due to empty unless flags set.
        if owner is not None:
            o_val = owner.strip()
        elif piped or task is not None:
            o_val = ""
        else:
            o_val = input("Owner (optional): ").strip()

        if due is not None:
            d_val = due.strip()
        elif piped or task is not None:
            d_val = ""
        else:
            d_val = input("Due date (optional): ").strip()
    finally:
        sys.stdin = orig_stdin
        if tty_in is not None:
            try:
                tty_in.close()
            except Exception:
                pass

    return append_action_item(issue_id, task=t_val, owner=o_val, due=d_val)


def list_action_items(issue_id: str) -> int:
    data = load_postmortem(issue_id)
    if data is None:
        print(f"No postmortem found for issue: {issue_id}", file=sys.stderr)
        return 1
    items = data.get("actions_and_follow_up") or []
    if not items:
        print("(No action items.)")
        return 0
    for i, raw in enumerate(items, start=1):
        if not isinstance(raw, dict):
            print(f"  {i}. {raw!r}")
            continue
        mark = "[x]" if _action_item_is_done(raw) else "[ ]"
        title = (raw.get("task") or raw.get("title") or "").strip() or "(no description)"
        extra = []
        if (raw.get("owner") or "").strip():
            extra.append(f"owner={raw['owner']}")
        if (raw.get("due") or "").strip():
            extra.append(f"due={raw['due']}")
        suffix = f"  ({'; '.join(extra)})" if extra else ""
        print(f"  {i}. {mark} {title}{suffix}")
    return 0


def set_action_item_done(issue_id: str, index: int, *, done: bool) -> int:
    """1-based index. Returns 0 on success."""
    data = load_postmortem(issue_id)
    if data is None:
        print(f"No postmortem found for issue: {issue_id}", file=sys.stderr)
        return 1
    items = data.get("actions_and_follow_up") or []
    if index < 1 or index > len(items):
        print(
            f"Error: no action item at index {index} (1..{len(items)}).",
            file=sys.stderr,
        )
        return 1
    item = items[index - 1]
    if not isinstance(item, dict):
        print("Error: item is not a dict; edit actions.yaml manually.", file=sys.stderr)
        return 1
    item["done"] = bool(done)
    if "completed" in item:
        del item["completed"]
    save_postmortem(issue_id, data)
    state = "done" if done else "not done"
    print(f"Action item {index} marked {state} on '{issue_id}'.")
    return 0


def _format_piped_capture(command: Optional[str], output: str) -> str:
    """
    Minimal timeline text: optional ``$ <command>``, blank line, then captured stdout.

    No synthetic hostname or cwd; used when stdin was piped and the user supplied
    a command string (CLI flag, env, or prompt).
    """
    out = output or ""
    cmd = (command or "").strip()
    if not cmd:
        return out
    return f"$ {cmd}\n\n{out}"


def append_timeline_entry(
    issue_id: str,
    *,
    time_str: Optional[str],
    action: Optional[str],
) -> int:
    """
    Append one timeline event (time + action). Action from ``action`` or stdin if None/empty.
    Returns 0 on success, 1 on error.
    """
    data = load_postmortem(issue_id)
    if data is None:
        print(f"No postmortem found for issue: {issue_id}", file=sys.stderr)
        return 1

    body = action if action is not None else sys.stdin.read()
    body = (body or "").strip()
    if not body:
        print("Error: no action text (use --action or pipe stdin).", file=sys.stderr)
        return 1

    t = (time_str or "").strip() or default_timeline_timestamp()
    data.setdefault("timeline", [])
    data["timeline"].append({"time": t, "action": body})
    save_postmortem(issue_id, data)
    print(f"Timeline entry added to '{issue_id}' at {t!r}.")
    return 0


def add_timeline_entry_interactive(
    issue_id: str,
    *,
    time_str: Optional[str] = None,
    action: Optional[str] = None,
    piped_command: Optional[str] = None,
) -> int:
    """
    Interactive prompt for appending one timeline entry to an incident.

    Used by `mortician add` (stateful) to avoid forcing `issue_id` each time.
    """
    q = _questionary_module()
    now_iso_ms = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    if now_iso_ms.endswith("+00:00"):
        now_iso_ms = now_iso_ms[: -len("+00:00")]

    # Only consume piped stdin when the caller did not provide --action.
    piped_stdin = (action is None) and (not sys.stdin.isatty())
    stdin_text: Optional[str] = None
    stamp_ts: Optional[str] = None

    # If stdin is piped, we still want interactive prompts to read from the TTY.
    orig_stdin = sys.stdin
    tty_in = None
    try:
        if piped_stdin:
            stdin_text = (orig_stdin.read() or "").strip()
            stamp_ts = _extract_stamp_from_text(stdin_text) if stdin_text else None

            # Swap stdin to TTY for subsequent interactive prompts.
            tty_path = "/dev/tty" if os.name != "nt" else "CONIN$"
            try:
                tty_in = open(tty_path, "r", encoding="utf-8")
                sys.stdin = tty_in
            except Exception:
                # Fallback to existing stdin; prompts may not behave as expected.
                sys.stdin = orig_stdin

        if time_str is not None:
            t_val = time_str
        else:
            t_val = _prompt_timeline_time_with_stamp(q, default_ts=now_iso_ms, stamp_ts=stamp_ts)

        if action is not None:
            a_val = action
        else:
            seed = ""
            if piped_stdin:
                cmd_resolved = (piped_command or "").strip()
                if not cmd_resolved:
                    cmd_resolved = (os.environ.get("MORTICIAN_ADD_CMD") or "").strip()
                if not cmd_resolved and tty_in is not None:
                    try:
                        cmd_resolved = input("Command (optional, Enter to skip): ").strip()
                    except EOFError:
                        cmd_resolved = ""
                seed = _format_piped_capture(cmd_resolved, stdin_text or "")
            else:
                seed = stdin_text or ""
            edited = _edit_text_in_editor(seed, field_label="action")
            a_val = (edited or "").strip()

        return append_timeline_entry(issue_id, time_str=t_val, action=a_val)
    finally:
        sys.stdin = orig_stdin
        if tty_in is not None:
            try:
                tty_in.close()
            except Exception:
                pass


def _extract_stamp_from_text(text: str) -> Optional[str]:
    """
    Extract a timestamp from arbitrary log text.

    Supports:
    - ISO8601/RFC3339 anywhere in the line (optionally wrapped in brackets)
    - Unix epoch (seconds or milliseconds) anywhere in the line
    - `YYYY-MM-DD HH:MM:SS(.mmm)` anywhere in the line
    """
    if not text:
        return None

    # ISO8601 with optional fractional seconds + optional timezone.
    iso_re = re.compile(
        r"(?P<iso>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)"
    )
    m = iso_re.search(text)
    if m:
        iso = m.group("iso")
        s = iso.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return iso
        if dt.tzinfo is None:
            # Naive ISO timestamps in logs typically imply UTC.
            dt = dt.replace(tzinfo=timezone.utc)
        dt_utc = dt.astimezone(timezone.utc)
        out = dt_utc.isoformat(timespec="milliseconds")
        if out.endswith("+00:00"):
            out = out[: -len("+00:00")]
        return out

    # Unix epoch seconds or milliseconds.
    epoch_re = re.compile(r"\b(?P<epoch>\d{10}(?:\.\d+)?|\d{13}(?:\.\d+)?)\b")
    m = epoch_re.search(text)
    if m:
        epoch_raw = m.group("epoch")
        try:
            epoch_val = float(epoch_raw)
            # 13-digit epochs are usually milliseconds.
            if epoch_val > 1e12:
                epoch_val = epoch_val / 1000.0
            dt = datetime.fromtimestamp(epoch_val, tz=timezone.utc)
            out = dt.isoformat(timespec="milliseconds")
            if out.endswith("+00:00"):
                out = out[: -len("+00:00")]
            return out
        except Exception:
            return None

    # `YYYY-MM-DD HH:MM:SS(.mmm)` (assume UTC).
    space_re = re.compile(
        r"(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)"
    )
    m = space_re.search(text)
    if m:
        stamp = m.group("stamp").strip()
        frac = ""
        if "." in stamp:
            stamp, frac = stamp.split(".", 1)
        try:
            dt = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if frac:
                # Convert fractional seconds to microseconds (pad/truncate to 6).
                frac_us = (frac[:6]).ljust(6, "0")
                dt = dt.replace(microsecond=int(frac_us))
            out = dt.isoformat(timespec="milliseconds")
            if out.endswith("+00:00"):
                out = out[: -len("+00:00")]
            return out
        except Exception:
            return None

    return None


def _prompt_timeline_time_with_stamp(
    q: Any,
    *,
    default_ts: str,
    stamp_ts: Optional[str],
) -> str:
    """
    Time prompt that supports Stamp/Now/Enter-manually when `questionary` is available.
    """
    if q is not None:
        choices: List[str] = []
        if stamp_ts:
            choices.append(f"Stamp ({stamp_ts})")
        choices.append(f"Now ({default_ts})")
        choices.append("Enter manually")

        try:
            choice = q.select(
                "Time for this entry:",
                choices=choices,
            ).ask()
        except (EOFError, KeyboardInterrupt):
            return default_ts

        if choice is None:
            return default_ts
        if stamp_ts and choice.startswith("Stamp ("):
            return stamp_ts
        if choice.startswith("Now ("):
            return default_ts

        manual = q.text("Time:", default=default_ts).ask()
        return (manual or default_ts).strip()

    # No questionary: follow plan's behavior.
    if stamp_ts:
        return stamp_ts
    return default_ts


def slugify(text):
    """Convert a string to a slug (lowercase, no special characters)."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def smart_id_from_title(title):
    """Generate a short, unique ID based on the title."""
    words = slugify(title).split("-")
    if len(words) == 1:
        return words[0][:8]  # Single word, truncate to 8 characters
    elif len(words) == 2:
        return words[0][:4] + words[1][:4]  # Two words, 4+4 characters
    elif len(words) >= 3:
        return words[0][0] + words[1][0] + words[2][:4]
    return "untitled"
