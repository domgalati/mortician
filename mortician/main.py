# PYTHON_ARGCOMPLETE_OK
import argparse
import os
import sys
from typing import List, Optional

from .bundle import delete_bundle_path, list_incident_summaries
from .state import (
    clear_active_issue_id_if_matches,
    get_active_issue_id,
    require_active_issue_id,
    set_active_issue_id,
)
from .statuses import all_status_labels

try:
    import argcomplete  # type: ignore
except ImportError:  # pragma: no cover
    argcomplete = None

from .utils import (
    add_timeline_entry_interactive,
    append_action_item_interactive,
    append_timeline_entry,
    create_postmortem,
    edit_postmortem_stateful,
    guided_input,
    list_action_items,
    merge_and_save_postmortem,
    print_create_followup,
    set_action_item_done,
    smart_id_from_title,
)
from .ui import show_postmortem


def _incident_id_completer(prefix: str, **_kwargs) -> List[str]:
    """Complete existing incident ids from bundle metadata."""
    p = (prefix or "").strip()
    ids = [row.get("id", "") for row in list_incident_summaries()]
    if not p:
        return [i for i in ids if i]
    return [i for i in ids if i and i.startswith(p)]


def _status_completer(prefix: str, **_kwargs) -> List[str]:
    """Complete common status values."""
    p = (prefix or "").strip().lower()
    statuses = all_status_labels()
    if not p:
        return statuses
    return [s for s in statuses if s.lower().startswith(p)]


def _add_entry_key_completer(prefix: str, **_kwargs) -> List[str]:
    """Suggest timeline entry keys in KEY=VALUE pairs."""
    # We only complete the "key=" part; users still type the value.
    p = (prefix or "").strip()
    if "=" in p:
        return []
    candidates = ["time=", "action="]
    if not p:
        return candidates
    return [c for c in candidates if c.startswith(p)]


def main():
    EDITOR_SENTINEL = "__MORTICIAN_EDIT_IN_EDITOR__"
    # Normalize deprecated/alternate option spellings into canonical dash-case
    # before argparse runs. This lets users type `--temp_fix` while keeping
    # tab completion clean (only canonical flags are registered with argparse).
    alias_to_canonical = {
        "--root_cause": "--root-cause",
        "--temp_fix": "--temp-fix",
        "--perm_fix": "--perm-fix",
        "--affected_services": "--affected-services",
        "--business_impact": "--business-impact",
    }
    argv = sys.argv[1:]
    normalized: List[str] = []
    for tok in argv:
        new_tok = tok
        for alias, canonical in alias_to_canonical.items():
            if tok == alias:
                new_tok = canonical
                break
            if tok.startswith(alias + "="):
                new_tok = canonical + "=" + tok[len(alias) + 1 :]
                break
        normalized.append(new_tok)
    sys.argv = [sys.argv[0]] + normalized

    parser = argparse.ArgumentParser(
        description="CLI for incident bundles (postmortems) under incidents/"
    )

    subparsers = parser.add_subparsers(help="Available commands", dest="command")

    create_parser = subparsers.add_parser("create", help="Create a new incident bundle")
    create_parser.add_argument(
        "title",
        help="Incident title (a short id is derived from this; it is not your custom id)",
    )
    create_parser.add_argument(
        "--guide",
        action="store_true",
        help="Interactive wizard after create",
    )

    edit_parser = subparsers.add_parser("edit", help="Edit an existing incident")
    edit_issue_id = edit_parser.add_argument(
        "issue_id",
        nargs="?",
        help="Incident id (omit to edit the active incident selected via `mortician select`)",
    )
    edit_issue_id.completer = _incident_id_completer  # type: ignore[attr-defined]
    edit_status_arg = edit_parser.add_argument(
        "--status",
        help="Update status (e.g. Resolved, Unresolved)",
        # Keep argparse permissive; completion handles common values.
        nargs="?",
        const=EDITOR_SENTINEL,
        default=None,
    )
    edit_status_arg.completer = _status_completer  # type: ignore[attr-defined]
    edit_parser.add_argument(
        "--severity",
        nargs="?",
        const=EDITOR_SENTINEL,
        default=None,
        help="Severity label (e.g. P1, SEV-2)",
    )
    edit_parser.add_argument(
        "--owner",
        nargs="?",
        const=EDITOR_SENTINEL,
        default=None,
        help="Update the incident owner",
    )
    edit_parser.add_argument(
        "--participants",
        nargs="?",
        const=EDITOR_SENTINEL,
        default=None,
        help="Update participants (string)",
    )
    edit_parser.add_argument(
        "--summary",
        nargs="?",
        const=EDITOR_SENTINEL,
        default=None,
        help="Update incident summary (Markdown); omit value to edit in $EDITOR",
    )
    edit_parser.add_argument(
        "--root-cause",
        dest="root_cause",
        nargs="?",
        const=EDITOR_SENTINEL,
        default=None,
        help="Update root cause (Markdown); omit value to edit in $EDITOR",
    )
    edit_parser.add_argument(
        "--temp-fix",
        dest="temp_fix",
        nargs="?",
        const=EDITOR_SENTINEL,
        default=None,
        help="Update temporary fix (Markdown); omit value to edit in $EDITOR",
    )
    edit_parser.add_argument(
        "--perm-fix",
        dest="perm_fix",
        nargs="?",
        const=EDITOR_SENTINEL,
        default=None,
        help="Update permanent fix (Markdown); omit value to edit in $EDITOR",
    )
    edit_parser.add_argument(
        "--affected-services",
        dest="affected_services",
        nargs="?",
        const=EDITOR_SENTINEL,
        default=None,
        help="Update affected services; omit value to edit in $EDITOR",
    )
    edit_parser.add_argument(
        "--duration",
        dest="duration_of_outage",
        nargs="?",
        const=EDITOR_SENTINEL,
        default=None,
        help="Update duration of outage; omit value to edit in $EDITOR",
    )
    edit_parser.add_argument(
        "--business-impact",
        dest="business_impact",
        nargs="?",
        const=EDITOR_SENTINEL,
        default=None,
        help="Update business impact; omit value to edit in $EDITOR",
    )
    edit_parser.add_argument(
        "--no-input",
        action="store_true",
        help="Do not prompt for missing fields (for scripts; use --perm-fix/--temp-fix with --status)",
    )
    add_entry_arg = edit_parser.add_argument(
        "--add-entry",
        nargs="+",
        metavar="KEY=VALUE",
        help="Append one timeline row (e.g. time='2025-03-14 12:00 UTC' action='Sev-1 declared'). "
        "Values can contain '=' after the first '=' in each pair.",
    )
    add_entry_arg.completer = _add_entry_key_completer  # type: ignore[attr-defined]

    show_parser = subparsers.add_parser(
        "show",
        help="Show one incident as Markdown (active incident when issue_id is omitted)",
    )
    show_issue_id = show_parser.add_argument(
        "issue_id",
        nargs="?",
        help="Incident id (omit to list all)",
    )
    show_issue_id.completer = _incident_id_completer  # type: ignore[attr-defined]
    show_status_arg = show_parser.add_argument(
        "--status",
        help="When listing: filter by status (case-insensitive)",
    )
    show_status_arg.completer = _status_completer  # type: ignore[attr-defined]
    show_parser.add_argument(
        "--date",
        help="When listing: filter by date (YYYY-MM-DD)",
    )
    show_out = show_parser.add_mutually_exclusive_group()
    show_out.add_argument(
        "--plain",
        action="store_true",
        help="Print raw Markdown (default; overrides MORTICIAN_SHOW_RENDER)",
    )
    show_out.add_argument(
        "--render",
        nargs="?",
        const="rich",
        default=None,
        choices=("rich", "textual"),
        metavar="BACKEND",
        help="Render Markdown in the terminal: rich (Rich; default when --render is used alone) "
        "or textual (Textual fullscreen). Textual requires: pip install 'mortician[textual]'.",
    )

    list_parser = subparsers.add_parser(
        "list",
        help="List incidents (same filters as mortician show)",
    )
    list_status_arg = list_parser.add_argument(
        "--status",
        help="Filter by status (case-insensitive)",
    )
    list_status_arg.completer = _status_completer  # type: ignore[attr-defined]
    list_parser.add_argument(
        "--date",
        help="Filter by date (YYYY-MM-DD)",
    )

    timeline_parser = subparsers.add_parser(
        "timeline",
        help="Add or manage timeline events",
    )
    timeline_sub = timeline_parser.add_subparsers(
        dest="timeline_command",
        required=True,
        help="Timeline subcommand",
    )
    tl_add = timeline_sub.add_parser(
        "add",
        help="Append a timeline event; use --action for one line, or omit it to read body from stdin",
    )
    tl_issue_id = tl_add.add_argument("issue_id", help="Incident id")
    tl_issue_id.completer = _incident_id_completer  # type: ignore[attr-defined]
    tl_add.add_argument(
        "--time",
        default=None,
        help="Timestamp string (default: current time UTC)",
    )
    tl_add.add_argument(
        "--action",
        default=None,
        help="Event description (Markdown). If omitted, stdin is read until EOF",
    )

    serve_parser = subparsers.add_parser(
        "serve",
        help="Run local dashboard (incident bundles + live updates)",
    )
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port (default: 8765)",
    )

    add_parser = subparsers.add_parser(
        "add",
        help="Add one timeline entry to the active incident selected via `mortician select`",
    )
    add_parser.add_argument(
        "--time",
        default=None,
        help="Timestamp string (default: prompt; falls back to current UTC)",
    )
    add_parser.add_argument(
        "--action",
        default=None,
        help="Event description (Markdown). If omitted, an interactive prompt is shown.",
    )
    add_parser.add_argument(
        "-c",
        "--cmd",
        dest="piped_cmd",
        default=None,
        help="When stdin is piped, prepend ``$ <cmd>`` before the captured output. "
        "The shell does not pass the left-hand command to Mortician; use this flag (or "
        "MORTICIAN_ADD_CMD) to record it.",
    )

    select_parser = subparsers.add_parser(
        "select",
        help="Select an active incident id for subsequent edit/add commands",
    )
    select_issue_id = select_parser.add_argument(
        "issue_id",
        help="Incident id (sets the active incident used by `mortician edit`/`mortician add`/`mortician action`)",
        nargs="?",
    )
    select_issue_id.completer = _incident_id_completer  # type: ignore[attr-defined]

    action_parser = subparsers.add_parser(
        "action",
        help="Manage checklist items in actions.yaml for the active incident",
    )
    action_sub = action_parser.add_subparsers(
        dest="action_command",
        required=True,
        help="Action subcommand",
    )
    act_add = action_sub.add_parser(
        "add",
        help="Append a follow-up item (done=false). Use --task or pipe stdin for the description.",
    )
    act_add.add_argument(
        "--task",
        default=None,
        help="Task description (omit to type interactively or pipe stdin)",
    )
    act_add.add_argument("--owner", default=None, help="Owner (optional; empty if omitted with --task)")
    act_add.add_argument("--due", default=None, help="Due date (optional)")
    action_sub.add_parser("list", help="List action items with [ ] / [x] checkboxes")
    act_done = action_sub.add_parser("done", help="Mark item at 1-based index as done")
    act_done.add_argument("index", type=int, help="Item number from `mortician action list`")
    act_undo = action_sub.add_parser("undo", help="Mark item at 1-based index as not done")
    act_undo.add_argument("index", type=int, help="Item number from `mortician action list`")

    # Enable shell completions (bash/zsh/fish, and PowerShell if registered).
    if argcomplete is not None:
        argcomplete.autocomplete(parser)

    args = parser.parse_args()

    if args.command == "create":
        issue_id, bundle_path = create_postmortem(args.title, smart_id_from_title)
        set_active_issue_id(issue_id)
        if args.guide:
            try:
                data = guided_input()
                merge_and_save_postmortem(issue_id, data)
            except KeyboardInterrupt:
                # Use the path from create (not find_bundle_dir) so cleanup works on
                # Windows and whenever meta lookup would not match the new folder.
                removed = delete_bundle_path(bundle_path)
                clear_active_issue_id_if_matches(issue_id)
                if removed:
                    print(
                        "\nInterrupted; removed unfinished incident bundle.",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "\nInterrupted; could not remove the bundle directory. "
                        f"Delete it manually if needed:\n  {bundle_path}",
                        file=sys.stderr,
                    )
                sys.exit(130)
        print_create_followup(issue_id)
    elif args.command == "select":
        if args.issue_id:
            set_active_issue_id(args.issue_id)
            print(f"Active incident selected: {args.issue_id}")
        else:
            active = get_active_issue_id()
            if not active:
                print("No active incident selected. Run `mortician select <issue_id>` first.")
            else:
                title = ""
                for row in list_incident_summaries():
                    if row.get("id") == active:
                        title = row.get("title") or ""
                        break
                if title.strip():
                    print(f"Active incident: {active} - {title.strip()}")
                else:
                    print(f"Active incident: {active}")
    elif args.command == "edit":
        issue_id = args.issue_id or require_active_issue_id()
        if args.issue_id:
            set_active_issue_id(args.issue_id)
        edit_postmortem_stateful(issue_id, args, EDITOR_SENTINEL=EDITOR_SENTINEL)
    elif args.command == "add":
        issue_id = require_active_issue_id()
        code = add_timeline_entry_interactive(
            issue_id,
            time_str=args.time,
            action=args.action,
            piped_command=args.piped_cmd,
        )
        sys.exit(code)
    elif args.command == "action":
        issue_id = require_active_issue_id()
        if args.action_command == "add":
            code = append_action_item_interactive(
                issue_id,
                task=args.task,
                owner=args.owner,
                due=args.due,
            )
            sys.exit(code)
        if args.action_command == "list":
            code = list_action_items(issue_id)
            sys.exit(code)
        if args.action_command == "done":
            sys.exit(set_action_item_done(issue_id, args.index, done=True))
        if args.action_command == "undo":
            sys.exit(set_action_item_done(issue_id, args.index, done=False))
    elif args.command == "show":
        env_render = os.environ.get("MORTICIAN_SHOW_RENDER", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        render_backend: Optional[str] = args.render
        if args.plain:
            render_backend = None
        elif render_backend is None and env_render:
            render_backend = "rich"
        issue_id = args.issue_id or require_active_issue_id()
        show_postmortem(
            issue_id=issue_id,
            status_filter=args.status,
            date_filter=args.date,
            render=render_backend,
        )
    elif args.command == "list":
        show_postmortem(
            issue_id=None,
            status_filter=args.status,
            date_filter=args.date,
        )
    elif args.command == "timeline":
        if args.timeline_command == "add":
            code = append_timeline_entry(
                args.issue_id,
                time_str=args.time,
                action=args.action,
            )
            sys.exit(code)
    elif args.command == "serve":
        import uvicorn
        from .serve import app as dashboard_app

        uvicorn.run(dashboard_app, host=args.host, port=args.port, log_level="info")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
