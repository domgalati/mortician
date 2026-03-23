import sys

from .bundle import list_incident_summaries
from .formatter import postmortem_to_markdown
from .utils import load_postmortem


def show_postmortem(issue_id=None, status_filter=None, date_filter=None, *, render=False):
    """Display postmortems."""
    if issue_id:
        data = load_postmortem(issue_id)
        if data is None:
            print(f"No postmortem found for issue: {issue_id}")
            return
        md = postmortem_to_markdown(data)
        if render:
            try:
                from rich.console import Console
                from rich.markdown import Markdown
            except ImportError:
                print(
                    "Rich is not installed. Use plain output (`mortician show --plain`) "
                    "or install extras: pip install 'mortician[rich]'",
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
            all_postmortems = [
                pm for pm in all_postmortems
                if pm["status"].lower() == status_filter.lower()
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
