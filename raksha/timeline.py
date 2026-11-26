"""Hospital-local encounter constraints for consistent date shifting."""

from collections import defaultdict
import re

from raksha.detection import identifier_kind
from raksha.linkage import patient_key

_LABEL = re.compile(r"(?im)^([ \t]*encounter[ _-]+(?:id|ref)[ \t]*:[ \t]*)([^\s,;|]+)")
_QUALIFIED = re.compile(r"[A-Z]{2,}[A-Z0-9/-]*\d{3,}", re.ASCII)


def encounter_key(record):
    if isinstance(record, str):
        values = [match[2] for match in _LABEL.finditer(record)]
    else:
        values = [
            value for label, value in record.items()
            if identifier_kind(label) == "ENCOUNTER" and isinstance(value, str)
        ]
    keys = {value.strip().upper() for value in values if value.strip()}
    if len(keys) == 1:
        key = next(iter(keys))
        if _QUALIFIED.fullmatch(key):
            return key
    return None


def encounter_offsets(records, identity, shift):
    """Agree on an episode offset without assigning new patient pseudonyms."""
    groups = defaultdict(list)
    for record in records:
        encounter = encounter_key(record)
        if encounter:
            groups[encounter].append(record)

    offsets = {}
    for encounter, members in groups.items():
        if len(members) < 2:
            continue
        decisions = {decision for record in members if (decision := identity(record))[0]}
        observed_ids = {key for record in members if (key := patient_key(record))}
        if len(decisions) > 1 or len(observed_ids) > 1:
            continue
        elif decisions:
            offsets[encounter] = next(iter(decisions))[1]
        else:
            offsets[encounter] = shift(encounter)
    return offsets


def redact_encounter(text: str) -> tuple[str, int]:
    return _LABEL.subn(r"\1[ENCOUNTER]", text)
