def json_to_markdown(data):
    """Convert a postmortem JSON structure into a formatted Markdown string."""
    lines = []

    # Overview
    lines.append(f"# {data['overview'].get('date', '')}: {data['overview'].get('incident_title', '')}")
    lines.append("## Overview")
    lines.append(f"**Time Created:** {data['overview'].get('time', '')}\\")
    lines.append(f"**Status:** {data['overview'].get('status', '')}")

    # Incident Owner & Participants
    lines.append("\n## Incident Owner")
    lines.append(data.get("incident_owner", ""))

    lines.append("\n## Incident Participants")
    participants = data.get("incident_participants", [])
    lines.append(", ".join(participants))

    # Summary
    lines.append("\n## Incident Summary")
    lines.append(data.get("incident_summary", ""))

    # Impact & Severity
    impact = data.get("impact_and_severity", {})
    lines.append("\n## Impact & Severity")
    lines.append(f"**Affected Services:** {impact.get('affected_services', '')}")
    lines.append(f"**Duration of Outage:** {impact.get('duration_of_outage', '')}")
    lines.append(f"**Business Impact:** {impact.get('business_impact', '')}")

    # Root Cause
    lines.append("\n## Root Cause")
    lines.append(data.get("root_cause", ""))

    # Resolution
    resolution = data.get("resolution", {})
    lines.append("\n## Resolution")
    lines.append("### Temporary Fix")
    lines.append(resolution.get("temporary_fix", ""))
    lines.append("\n### Permanent Fix")
    lines.append(resolution.get("permanent_fix", ""))

    # Actions & Follow-up
    lines.append("\n## Actions & Follow-Up")
    actions = data.get("actions_and_follow_up", [])
    if actions:
        for action_item in actions:
            lines.append(f"- {action_item}")
    else:
        lines.append("_No action items listed._")

    # Timeline
    timeline = data.get("timeline", [])
    lines.append("\n## Timeline")
    if timeline:
        for event in timeline:
            time_val = event.get('time', 'N/A')
            action_val = event.get('action', 'N/A')
            lines.append(f"- **{time_val}**: {action_val}")
    else:
        lines.append("_No timeline entries found._")

    # Join everything into a single markdown string
    return "\n".join(lines)