import json
from .utils import load_postmortem
from .formatter import json_to_markdown

def show_postmortem(issue_id=None, status_filter=None, date_filter=None):
    """Display postmortems."""
    from .utils import POSTMORTEMS_DIR
    postmortem_files = list(POSTMORTEMS_DIR.glob("*.json"))

    if issue_id:
        data = load_postmortem(issue_id)
        if data is None:
            print(f"No postmortem found for issue: {issue_id}")
            return
        print(json_to_markdown(data))
    else:  # List all postmortems or filter by status
        if not postmortem_files:
            print("No postmortems available.")
            return

        all_postmortems = []
        for file in postmortem_files:
            with open(file, "r") as f:
                data = json.load(f)
                all_postmortems.append({
                    "id": file.stem,
                    "title": data["overview"].get("incident_title", ""),
                    "status": data["overview"].get("status", "Unknown"),
                    "date": data["overview"].get("date", "Unknown")
                })

        # Filter by status if requested
        if status_filter:
            all_postmortems = [
                pm for pm in all_postmortems if pm["status"].lower() == status_filter.lower()
            ]
            if not all_postmortems:
                print(f"No postmortems found with status '{status_filter}'.")
                return
            
        # Filter by date if requested
        if date_filter:
            all_postmortems = [
                pm for pm in all_postmortems if pm["date"] == date_filter
            ]
            if not all_postmortems:
                print(f"No postmortems found with date '{date_filter}'.")
                return

        # Display all matching postmortems
        print("Mortician Postmortems:")
        print(f"{'ID':<15} {'Title':<30} {'Status':<15} {'Date':<15}")
        print("-" * 75)
        for pm in all_postmortems:
            truncated_title = pm['title'][:28] + ".." if len(pm['title']) > 30 else pm['title']
            truncated_status = pm['status'][:13] + ".." if len(pm['status']) > 15 else pm['status']
            print(f"{pm['id']:<15} {truncated_title:<30} {truncated_status:<15} {pm['date']:<15}")