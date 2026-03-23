def postmortem_to_markdown(data):
    """Convert a postmortem dict into a formatted Markdown string."""
    lines = []

    # Overview
    ov = data.get("overview") or {}
    lines.append(f"# {ov.get('date', '')}: {ov.get('incident_title', '')}")
    lines.append("## Overview")
    lines.append(f"**Time Created:** {ov.get('time', '')}\\")
    lines.append(f"**Status:** {ov.get('status', '')}")
    if ov.get("severity"):
        lines.append(f"**Severity:** {ov.get('severity')}")

    # Incident Owner & Participants
    lines.append("\n## Incident Owner")
    lines.append(data.get("incident_owner", ""))

    lines.append("\n## Incident Participants")
    participants = data.get("incident_participants", [])
    if isinstance(participants, str):
        lines.append(participants)
    else:
        lines.append(", ".join(participants))

    # Summary
    lines.append("\n## Incident Summary")
    lines.append(data.get("incident_summary", ""))

    # Impact & Severity
    impact = data.get("impact_and_severity", {})
    lines.append("\n## Impact & Severity")
    if impact.get("markdown"):
        lines.append(impact["markdown"])
    else:
        a = (impact.get("affected_services") or "").strip()
        d = (impact.get("duration_of_outage") or "").strip()
        b = (impact.get("business_impact") or "").strip()
        if a:
            lines.append(f"### Affected Services\n\n{a}")
        if d:
            lines.append(f"### Duration of Outage\n\n{d}")
        if b:
            lines.append(f"### Business Impact\n\n{b}")
        if not a and not d and not b:
            lines.append("_No impact details filled in._")

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
            if isinstance(action_item, dict):
                done = action_item.get("done") is True or action_item.get("completed") is True
                mark = "[x]" if done else "[ ]"
                title = (action_item.get("task") or action_item.get("title") or "").strip()
                rest = {
                    k: v
                    for k, v in action_item.items()
                    if k not in ("done", "completed", "task", "title")
                }
                if title:
                    extra = [f"{k}: {v}" for k, v in rest.items() if str(v).strip()]
                    suffix = f" ({'; '.join(extra)})" if extra else ""
                    lines.append(f"- {mark} {title}{suffix}")
                else:
                    parts = [f"{k}: {v}" for k, v in action_item.items()]
                    lines.append("- " + "; ".join(parts))
            else:
                lines.append(f"- {action_item}")
    else:
        lines.append("_No action items listed._")

    # Timeline
    timeline = data.get("timeline", [])
    lines.append("\n## Timeline")
    if timeline:
        for event in timeline:
            time_val = event.get("time", "N/A")
            action_val = event.get("action")
            if action_val is None or (isinstance(action_val, str) and not str(action_val).strip()):
                rest_keys = [k for k in event.keys() if k != "time"]
                if rest_keys:
                    bits = [f"{k}: {event[k]}" for k in rest_keys]
                    action_val = " · ".join(bits)
                else:
                    action_val = "N/A"
            if isinstance(action_val, str) and "\n" in action_val:
                lines.append(f"- **{time_val}**:")
                lines.append(action_val)
            else:
                lines.append(f"- **{time_val}**: {action_val}")
    else:
        lines.append("_No timeline entries found._")

    # Join everything into a single markdown string
    return "\n".join(lines)