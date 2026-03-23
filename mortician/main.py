import argparse
import os
import sys

from .utils import (
    append_timeline_entry,
    create_postmortem,
    edit_postmortem,
    guided_input,
    print_create_followup,
    smart_id_from_title,
)
from .ui import show_postmortem


def main():
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
    edit_parser.add_argument("issue_id", help="Incident id (see mortician list)")
    edit_parser.add_argument("--status", help="Update status (e.g. Resolved, Unresolved)")
    edit_parser.add_argument("--severity", help="Severity label (e.g. P1, SEV-2)")
    edit_parser.add_argument("--owner", help="Update the incident owner")
    edit_parser.add_argument("--participants", help="Update participants (string)")
    edit_parser.add_argument("--summary", help="Update incident summary (Markdown)")
    edit_parser.add_argument("--root_cause", help="Update root cause (Markdown)")
    edit_parser.add_argument("--temp_fix", help="Update temporary fix (Markdown)")
    edit_parser.add_argument("--perm_fix", help="Update permanent fix (Markdown)")
    edit_parser.add_argument(
        "--no-input",
        action="store_true",
        help="Do not prompt for missing fields (for scripts; use --perm_fix/--temp_fix with --status)",
    )
    edit_parser.add_argument(
        "--add-entry",
        nargs="+",
        metavar="KEY=VALUE",
        help="Append one timeline row (e.g. time='2025-03-14 12:00 UTC' action='Sev-1 declared'). "
        "Values can contain '=' after the first '=' in each pair.",
    )

    show_parser = subparsers.add_parser(
        "show",
        help="Show one incident as Markdown, or list all when issue_id is omitted",
    )
    show_parser.add_argument(
        "issue_id",
        nargs="?",
        help="Incident id (omit to list all)",
    )
    show_parser.add_argument(
        "--status",
        help="When listing: filter by status (case-insensitive)",
    )
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
        action="store_true",
        help="Render Markdown in the terminal (install mortician[rich])",
    )

    list_parser = subparsers.add_parser(
        "list",
        help="List incidents (same filters as mortician show)",
    )
    list_parser.add_argument(
        "--status",
        help="Filter by status (case-insensitive)",
    )
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
    tl_add.add_argument("issue_id", help="Incident id")
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

    args = parser.parse_args()

    if args.command == "create":
        issue_id = create_postmortem(args.title, smart_id_from_title)
        if args.guide:
            data = guided_input()
            edit_postmortem(issue_id, data)
        print_create_followup(issue_id)
    elif args.command == "edit":
        edit_postmortem(args.issue_id, args)
    elif args.command == "show":
        want_render = bool(args.render) or (
            os.environ.get("MORTICIAN_SHOW_RENDER", "").strip().lower()
            in ("1", "true", "yes")
        )
        if args.plain:
            want_render = False
        show_postmortem(
            issue_id=args.issue_id,
            status_filter=args.status,
            date_filter=args.date,
            render=want_render and bool(args.issue_id),
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
