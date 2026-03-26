import sys
from typing import Literal, Optional, Union

from .bundle import list_incident_summaries
from .formatter import postmortem_to_markdown
from .statuses import normalize_status
from .utils import load_postmortem

RenderBackend = Literal["rich", "textual"]


def show_postmortem(
    issue_id=None,
    status_filter=None,
    date_filter=None,
    *,
    render: Optional[Union[bool, RenderBackend]] = None,
):
    """Display postmortems.

    ``render`` is ``None`` for plain Markdown, or ``\"rich\"`` / ``\"textual\"`` for terminal renderers.
    ``True`` is accepted for backward compatibility and treated as ``\"rich\"``.
    """
    if issue_id:
        data = load_postmortem(issue_id)
        if data is None:
            print(f"No postmortem found for issue: {issue_id}")
            return
        md = postmortem_to_markdown(data)
        if render:
            backend: RenderBackend
            if render is True:
                backend = "rich"
            else:
                backend = render
            if backend == "textual":
                if not (sys.stdout.isatty() and sys.stdin.isatty()):
                    print(
                        "The textual renderer needs an interactive terminal (stdin/stdout TTY). "
                        "Use `mortician show <id> --render rich` or plain output.",
                        file=sys.stderr,
                    )
                    print(md)
                    return
                try:
                    from .tui_show_render import run_show_markdown_render
                except ImportError:
                    print(
                        "Textual is not installed. Install with: pip install 'mortician[textual]' "
                        "or use `mortician show <id> --render rich`.",
                        file=sys.stderr,
                    )
                    print(md)
                    return
                run_show_markdown_render(issue_id, md)
                return
            if backend == "rich":
                try:
                    from rich.console import Console
                    from rich.markdown import Markdown
                except ImportError:
                    print(
                        "Rich is not installed. Use plain output (`mortician show --plain`) "
                        "or reinstall mortician (Rich is a required dependency).",
                        file=sys.stderr,
                    )
                    print(md)
                    return
                Console().print(Markdown(md))
                return
        print(md)
    else:
        all_postmortems = list_incident_summaries()
        if not all_postmortems:
            print("No postmortems available.")
            return

        if status_filter:
            wanted = normalize_status(status_filter) or status_filter.strip()
            all_postmortems = [
                pm for pm in all_postmortems
                if (normalize_status(pm["status"]) or pm["status"]).lower() == wanted.lower()
            ]
            if not all_postmortems:
                print(f"No postmortems found with status '{status_filter}'.")
                return

        if date_filter:
            all_postmortems = [
                pm for pm in all_postmortems if pm["date"] == date_filter
            ]
            if not all_postmortems:
                print(f"No postmortems found with date '{date_filter}'.")
                return

        # Pretty table in interactive terminals; TSV-style output for pipes/scripts.
        interactive = sys.stdout.isatty()
        if interactive:
            try:
                from rich.console import Console
                from rich.table import Table
            except ImportError:
                interactive = False

        if interactive:
            table = Table(title="Mortician Postmortems", show_lines=False)
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Title", style="white")
            table.add_column("Status", style="magenta", no_wrap=True)
            table.add_column("Date", style="green", no_wrap=True)
            for pm in all_postmortems:
                table.add_row(
                    str(pm.get("id") or ""),
                    str(pm.get("title") or ""),
                    str(pm.get("status") or ""),
                    str(pm.get("date") or ""),
                )
            Console().print(table)
            return

        # Fallback: stable, parseable output.
        print("Mortician Postmortems:")
        print("ID\tTitle\tStatus\tDate")
        for pm in all_postmortems:
            print(
                f"{str(pm.get('id') or '')}\t"
                f"{str(pm.get('title') or '')}\t"
                f"{str(pm.get('status') or '')}\t"
                f"{str(pm.get('date') or '')}"
            )
