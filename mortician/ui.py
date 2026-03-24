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

        print("Mortician Postmortems:")
        print(f"{'ID':<15} {'Title':<30} {'Status':<15} {'Date':<15}")
        print("-" * 75)
        for pm in all_postmortems:
            truncated_title = pm['title'][:28] + ".." if len(pm['title']) > 30 else pm['title']
            truncated_status = pm['status'][:13] + ".." if len(pm['status']) > 15 else pm['status']
            print(f"{pm['id']:<15} {truncated_title:<30} {truncated_status:<15} {pm['date']:<15}")
