from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence


@dataclass(frozen=True)
class IncidentStatus:
    key: str
    label: str
    aliases: Sequence[str]
    bucket: str
    badge_class: str
    label_class: str
    chip_label: str


STATUS_DEFINITIONS: Sequence[IncidentStatus] = (
    IncidentStatus(
        key="unresolved",
        label="Unresolved",
        aliases=("open", "ongoing"),
        bucket="unresolved",
        badge_class="unresolved",
        label_class="label-unresolved",
        chip_label="Unresolved",
    ),
    IncidentStatus(
        key="temporary",
        label="Temporary Resolution",
        aliases=("temporary_resolution", "temporary-resolution", "mitigated"),
        bucket="temporary",
        badge_class="unresolved",
        label_class="label-temporary",
        chip_label="Temporary",
    ),
    IncidentStatus(
        key="pending",
        label="Pending Action Items",
        aliases=("pending"),
        bucket="pending",
        badge_class="pending",
        label_class="pending",
        chip_label="Pending",
    ),
    IncidentStatus(
        key="resolved",
        label="Resolved",
        aliases=("closed", "done"),
        bucket="resolved",
        badge_class="resolved",
        label_class="label-resolved",
        chip_label="Resolved",
    ),
)

DEFAULT_STATUS = STATUS_DEFINITIONS[0].label
TEMPORARY_STATUS = STATUS_DEFINITIONS[1].label
RESOLVED_STATUS = "Resolved"

_BY_KEY: Dict[str, IncidentStatus] = {s.key: s for s in STATUS_DEFINITIONS}
_NORMALIZED_TO_LABEL: Dict[str, str] = {}

for _status in STATUS_DEFINITIONS:
    _NORMALIZED_TO_LABEL[_status.label.lower()] = _status.label
    _NORMALIZED_TO_LABEL[_status.key.lower()] = _status.label
    for _alias in _status.aliases:
        _NORMALIZED_TO_LABEL[_alias.lower()] = _status.label


def all_status_labels() -> List[str]:
    return [s.label for s in STATUS_DEFINITIONS]


def normalize_status(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return _NORMALIZED_TO_LABEL.get(text.lower())


def status_bucket(raw: Optional[str]) -> str:
    normalized = normalize_status(raw)
    if not normalized:
        return "other"
    for status in STATUS_DEFINITIONS:
        if status.label == normalized:
            return status.bucket
    return "other"


def status_badge_class(raw: Optional[str]) -> str:
    normalized = normalize_status(raw)
    if not normalized:
        return ""
    for status in STATUS_DEFINITIONS:
        if status.label == normalized:
            return status.badge_class
    return ""


def status_config_payload() -> Dict[str, object]:
    buckets: List[Dict[str, str]] = []
    seen_buckets = set()
    for status in STATUS_DEFINITIONS:
        if status.bucket in seen_buckets:
            continue
        seen_buckets.add(status.bucket)
        buckets.append(
            {
                "key": status.bucket,
                "label": status.chip_label if status.bucket != "temporary" else "Temporary Resolution",
                "labelClass": status.label_class,
            }
        )
    buckets.append({"key": "other", "label": "Other", "labelClass": "label-other"})
    return {
        "default_status": DEFAULT_STATUS,
        "resolved_status": RESOLVED_STATUS,
        "labels": all_status_labels(),
        "statuses": [
            {
                "key": s.key,
                "label": s.label,
                "aliases": list(s.aliases),
                "bucket": s.bucket,
                "badgeClass": s.badge_class,
                "labelClass": s.label_class,
                "chipLabel": s.chip_label,
            }
            for s in STATUS_DEFINITIONS
        ],
        "buckets": buckets,
    }
