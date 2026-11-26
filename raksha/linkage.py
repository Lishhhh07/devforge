"""Conservative linkage using explicitly labelled, qualified hospital IDs."""

import re

from raksha.detection import identifier_kind


_ID = re.compile(r"[A-Z]{2,}[A-Z0-9]*(?:[-/][A-Z0-9]+)*[-/]?\d{3,}", re.ASCII)
_LABEL = re.compile(
    r"(?im)^([ \t]*(?:UHID|MRN|Patient[ _]ID|Reg(?:istration)?[ .]+No)"
    r"[ \t]*:[ \t]*)([A-Z0-9/-]+)"
)


def patient_key(record: dict | str) -> str | None:
    if isinstance(record, str):
        values = [match[2] for match in _LABEL.finditer(record)]
    else:
        values = [
            value for label, value in record.items()
            if identifier_kind(label) == "MRN" and isinstance(value, str)
        ]
        for label in ("patient", "demographics"):
            nested = record.get(label)
            if isinstance(nested, dict):
                values.extend(
                    value for field, value in nested.items()
                    if identifier_kind(field) == "MRN" and isinstance(value, str)
                )
    ids = {value.strip().upper() for value in values if _ID.fullmatch(value.strip().upper())}
    return f"hospital-id|{ids.pop()}" if len(ids) == 1 else None


def redact_labelled_ids(text: str) -> tuple[str, int]:
    return _LABEL.subn(r"\1[MRN]", text)


def shared_identity(record: dict | str) -> str | None:
    """Return one explicitly labelled, unmasked national identifier if present."""
    if isinstance(record, str):
        values = re.findall(r"(?im)^\s*aadhaar(?:\s+no)?[ \t]*:[ \t]*([0-9 -]+)", record)
    else:
        scopes = [record]
        for label in ("patient", "ids", "demographics"):
            if isinstance(record.get(label), dict):
                scopes.append(record[label])
        values = [
            str(value) for scope in scopes for label, value in scope.items()
            if identifier_kind(label) == "AADHAAR" and type(value) in (int, str)
        ]
    ids = {re.sub(r"[ -]", "", value) for value in values}
    if len(ids) == 1:
        identifier = next(iter(ids))
        if re.fullmatch(r"[0-9]{12}", identifier):
            return f"aadhaar|{identifier}"
    return None
