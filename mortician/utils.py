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

def guided_input():
    """Interactive prompt for postmortem creation"""
    data = DEFAULT_POSTMORTEM.copy()
    
    print("\n=== Guided Postmortem Creation ===")
    
    data["incident_owner"] = input("Incident Owner: ")
    data["incident_participants"] = input("Incident Participants (comma separated): ").split(",")
    data["incident_summary"] = input("Incident Summary: ")
    
    print("\n=== Impact & Severity ===")
    data["impact_and_severity"]["affected_services"] = input("Affected Services: ")
    data["impact_and_severity"]["duration_of_outage"] = input("Duration of Outage: ")
    data["impact_and_severity"]["business_impact"] = input("Business Impact: ")
    
    data["root_cause"] = input("\nRoot Cause: ")

    while True:
        tl_choice = input("Do you want to add items to the timeline? (y/n): ")
        if tl_choice.lower() == "y":
            while True:
                time = input("Time (HH:MM): ")
                action = input("Action/Event: ")
                
                timeline_entry = {
                    "time": time,
                    "action": action
                }
                data["timeline"].append(timeline_entry)
                
                another = input("Add another timeline entry? (y/n): ")
                if another.lower() != "y":
                    break
            break
        elif tl_choice.lower() == "n":
            break
        print("Invalid choice. Please enter y or n.")
    
    while True:
        print("\n=== Resolution ===")
        print("\nSelect status:")
        print("1. Unresolved")
        print("2. Temporary Resolution")
        print("3. Resolved")
        status_choice = input("Enter choice (1-3): ")
        if status_choice == "1":
            data["overview"]["status"] = "Unresolved"
            break
        elif status_choice == "2":
            data["overview"]["status"] = "Temporary Resolution"
            data["resolution"]["temporary_fix"] = input("Temporary Fix: ")
            break
        elif status_choice == "3":
            data["overview"]["status"] = "Resolved"
            data["resolution"]["permanent_fix"] = input("Permanent Fix: ")
            break
        print("Invalid choice. Please select 1, 2, or 3.")

    return data

def edit_postmortem(issue_id, args):
    """Edit specific fields of a postmortem based on CLI arguments."""
    data = load_postmortem(issue_id)
    if data is None:
        print(f"No postmortem found for issue: {issue_id}")
        return

    # Handle direct dictionary updates
    if isinstance(args, dict):
        data.update(args)
        save_postmortem(issue_id, data)
        print(f"Postmortem '{issue_id}' updated successfully.")
        return

    if args.status:
        data["overview"]["status"] = args.status
        if args.status.lower() == "resolved":
            data["resolution"]["permanent_fix"] = input("Enter permanent fix: ")
        elif args.status.lower() == "temporary resolution":
            data["resolution"]["temporary_fix"] = input("Enter temporary fix: ")
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
