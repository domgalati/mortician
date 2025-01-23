import argparse
from .templates import DEFAULT_POSTMORTEM
from .utils import create_postmortem, edit_postmortem, smart_id_from_title, guided_input
from .ui import show_postmortem

def main():
    parser = argparse.ArgumentParser(
        description="Simple CLI for managing Postmortems"
    )

    subparsers = parser.add_subparsers(help="Available commands", dest="command")

    # create <issue_id>
    create_parser = subparsers.add_parser("create", help="Create a new postmortem")
    create_parser.add_argument("issue_id", help="Identifier for the postmortem")
    create_parser.add_argument("--guide", action="store_true", help="Use guided creation mode")


    # edit <issue_id> [--status --owner --summary --timeline --add-entry ...]
    edit_parser = subparsers.add_parser("edit", help="Edit an existing postmortem")
    edit_parser.add_argument("issue_id", help="Identifier for the postmortem")
    edit_parser.add_argument("--status", help="Update the status")
    edit_parser.add_argument("--owner", help="Update the incident owner")
    edit_parser.add_argument("--participants", help="Update the participants")
    edit_parser.add_argument("--summary", help="Update the incident summary")
    edit_parser.add_argument("--root_cause", help="Update the root cause")
    edit_parser.add_argument("--temp_fix", help="Update the temporary fix")
    edit_parser.add_argument("--perm_fix", help="Update the permanent fix")
    edit_parser.add_argument(
        "--timeline", 
        action="store_true", 
        help="Indicate that timeline entries are being edited"
    )
    edit_parser.add_argument(
        "--add-entry", 
        nargs="+", 
        metavar="KEY=VALUE", 
        help="Add a new timeline entry (e.g. time=12:00 action='alert triggered')"
    )

    # show [issue_id] [--status <status>]
    show_parser = subparsers.add_parser("show", help="Show details of a postmortem or list all postmortems")
    show_parser.add_argument("issue_id", nargs="?", help="Identifier for the postmortem (optional)")
    show_parser.add_argument("--status", help="Filter postmortems by status (e.g., resolved, unresolved)")

    args = parser.parse_args()

    if args.command == "create":
        issue_id = create_postmortem(args.issue_id, smart_id_from_title)
        if args.guide:
            data = guided_input()
            edit_postmortem(issue_id, data)
    elif args.command == "edit":
        edit_postmortem(args.issue_id, args)
    elif args.command == "show":
        show_postmortem(issue_id=args.issue_id, status_filter=args.status)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
