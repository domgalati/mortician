import re
import json
from datetime import datetime
from pathlib import Path
from .templates import DEFAULT_POSTMORTEM


POSTMORTEMS_DIR = Path("postmortems")
POSTMORTEMS_DIR.mkdir(exist_ok=True)

def create_postmortem(title, smart_id_generator):
    """Create a new postmortem file."""
    issue_id = smart_id_generator(title)
    if load_postmortem(issue_id):
        raise ValueError(f"Postmortem '{issue_id}' already exists.")
    
    data = DEFAULT_POSTMORTEM.copy()
    data["overview"]["incident_title"] = title
    data["overview"]["date"] = str(datetime.now().date())
    data["overview"]["time"] = str(datetime.now().time())
    data["overview"]["status"] = "Unresolved"
    save_postmortem(issue_id, data)
    print(f"Postmortem created with id: '{issue_id}'")
    return issue_id    

def edit_postmortem(issue_id, args):
    """Edit specific fields of a postmortem based on CLI arguments."""
    data = load_postmortem(issue_id)
    if data is None:
        print(f"No postmortem found for issue: {issue_id}")
        return

    if args.status:
        data["overview"]["status"] = args.status
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
    if args.timeline and args.add_entry:
        entry = {}
        for kv in args.add_entry:
            k, v = kv.split("=", 1)
            entry[k] = v
        data["timeline"].append(entry)

    save_postmortem(issue_id, data)
    print(f"Postmortem '{issue_id}' updated successfully.")

def load_postmortem(issue_id):
    """Load a postmortem from disk as a Python dict."""
    file_path = POSTMORTEMS_DIR / f"{issue_id}.json"
    if not file_path.exists():
        return None
    with open(file_path, "r") as f:
        return json.load(f)

def save_postmortem(issue_id, data):
    """Save a Python dict to disk as JSON for a given issue."""
    file_path = POSTMORTEMS_DIR / f"{issue_id}.json"
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)

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
