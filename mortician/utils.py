from __future__ import annotations

import copy
import re
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from .bundle import (
    INCIDENTS_DIR,
    create_bundle,
    find_bundle_dir,
    load_postmortem as _load_postmortem_bundle,
    save_postmortem as _save_postmortem_bundle,
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
        f"  mortician timeline add {issue_id} --action \"…\"   (or pipe / omit --action for stdin)\n"
        f"  mortician edit {issue_id} --summary \"…\" --status …\n"
        f"  mortician serve   # dashboard\n"
        f"  Or edit index.md / timeline.yaml under the bundle folder.\n"
    )


def create_postmortem(title, smart_id_generator):
    """Create a new incident bundle."""
    issue_id = smart_id_generator(title)
    if find_bundle_dir(issue_id):
        raise ValueError(f"Postmortem '{issue_id}' already exists.")

    create_bundle(issue_id, title)
    print(f"Incident created with id: '{issue_id}' (from title).")
    return issue_id


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


def _questionary_module():
    try:
        import questionary  # type: ignore[import-untyped]
    except ImportError:
        return None
    return questionary


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


def guided_input():
    """Interactive prompt for postmortem creation (live-incident friendly order)."""
    data = copy.deepcopy(DEFAULT_POSTMORTEM)
    q = _questionary_module()

    print("\n=== Guided incident setup ===")

    data["incident_owner"] = input("Incident owner: ").strip()
    raw_parts = input("Participants (comma-separated, optional): ").strip()
    data["incident_participants"] = [p.strip() for p in raw_parts.split(",") if p.strip()]

    print()
    data["incident_summary"] = _read_multiline_block("Incident summary (Markdown ok):")
    incident_ongoing = _prompt_yes_no("Is the incident still ongoing? (y/n): ")

    print("\n=== Impact & severity (optional; blank lines skip) ===")
    data["impact_and_severity"]["affected_services"] = input("Affected services: ").strip()
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


def edit_postmortem(issue_id, args):
    """Edit specific fields of a postmortem based on CLI arguments or dict."""
    data = load_postmortem(issue_id)
    if data is None:
        print(f"No postmortem found for issue: {issue_id}")
        return

    if isinstance(args, dict):
        _merge_postmortem_dict(data, args)
        save_postmortem(issue_id, data)
        print(f"Postmortem '{issue_id}' updated successfully.")
        return

    no_input = getattr(args, "no_input", False)

    if args.status:
        data["overview"]["status"] = args.status
        st = args.status.lower()
        if st == "resolved":
            if args.perm_fix:
                data["resolution"]["permanent_fix"] = args.perm_fix
            elif not no_input:
                fix = input("Enter permanent fix (Enter to leave unchanged): ").strip()
                if fix:
                    data["resolution"]["permanent_fix"] = fix
        elif st == "temporary resolution":
            if args.temp_fix:
                data["resolution"]["temporary_fix"] = args.temp_fix
            elif not no_input:
                fix = input("Enter temporary fix (Enter to leave unchanged): ").strip()
                if fix:
                    data["resolution"]["temporary_fix"] = fix

    if args.owner:
        data["incident_owner"] = args.owner
    if args.participants:
        data["incident_participants"] = args.participants
    if args.summary:
        data["incident_summary"] = args.summary
    if args.root_cause:
        data["root_cause"] = args.root_cause
    if args.temp_fix:
        data["resolution"]["temporary_fix"] = args.temp_fix
    if args.perm_fix:
        data["resolution"]["permanent_fix"] = args.perm_fix

    if getattr(args, "severity", None) is not None:
        data.setdefault("overview", {})["severity"] = args.severity

    # --timeline is optional; --add-entry alone appends (fixes silent no-op).
    if args.add_entry:
        entry = {}
        for kv in args.add_entry:
            if "=" not in kv:
                print(f"Warning: skipping timeline fragment (expected KEY=VALUE): {kv!r}")
                continue
            k, v = kv.split("=", 1)
            entry[k.strip()] = v
        if entry:
            data["timeline"].append(entry)

    save_postmortem(issue_id, data)
    print(f"Postmortem '{issue_id}' updated successfully.")


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
