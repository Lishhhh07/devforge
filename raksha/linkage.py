"""Conservative linkage using explicitly labelled, qualified hospital IDs."""

import re
import unicodedata

from raksha.detection import _normalize, identifier_kind


_ID = re.compile(r"[A-Z]{2,}[A-Z0-9]*(?:[-/][A-Z0-9]+)*[-/]?\d{3,}", re.ASCII)
_LABEL = re.compile(
    r"(?im)^([ \t]*(?:UHID|MRN|Patient[ _]ID|Reg(?:istration)?[ .]+No)"
    r"[ \t]*:[ \t]*)([A-Z0-9/-]+)"
)


def _hospital_ids(record: dict | str) -> set[str]:
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
    return {value.strip().upper() for value in values if _ID.fullmatch(value.strip().upper())}


def patient_key(record: dict | str) -> str | None:
    ids = _hospital_ids(record)
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


_PERSON_LABELS = {"name", "patient name", "patients name", "full name", "naam",
                  "नाम", "मरीज का नाम", "मरीज़ का नाम", "रोगी का नाम"}
_TEXT_EVIDENCE = re.compile(
    r"(?im)^[ \t]*(patient[ \t]+name|full[ \t]+name|name|नाम|"
    r"mobile(?:[ \t]+no)?|phone(?:[ \t]+no)?|मोबाइल|फोन)[ \t]*:[ \t]*([^\r\n,;|]+)"
)


def is_patient_name(label: str) -> bool:
    return _normalize(label) in _PERSON_LABELS


def _phone_key(value: str) -> str | None:
    if not re.fullmatch(r"[+\d(). \t-]+", value):
        return None
    digits = "".join(str(unicodedata.decimal(char)) for char in value if char.isdecimal())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if re.fullmatch(r"[6-9][0-9]{9}", digits) and len(set(digits)) > 2 else None


def corroborating_identity(record: dict | str) -> str | None:
    """Exact complete patient name plus an explicit phone, for attaching fragments."""
    if len(_hospital_ids(record)) > 1:
        return None
    if isinstance(record, str):
        scopes = [_TEXT_EVIDENCE.findall(record)]
    else:
        scopes = [record.items()]
        for label in ("patient", "demographics", "contact"):
            if isinstance(record.get(label), dict):
                scopes.append(record[label].items())
    names, phones = set(), set()
    for scope in scopes:
        for label, value in scope:
            if type(value) not in (str, int):
                continue
            value = str(value).strip()
            if is_patient_name(label):
                parts = unicodedata.normalize("NFC", value).casefold().split()
                if 2 <= len(parts) <= 4 and all(
                    part and all(char.isalpha() or unicodedata.category(char).startswith("M")
                                 or char in "'’-" for char in part)
                    for part in parts
                ):
                    names.add(" ".join(parts))
            elif identifier_kind(label) == "PHONE":
                phone = _phone_key(value)
                if phone:
                    phones.add(phone)
    if len(names) == len(phones) == 1:
        return f"name-phone|{names.pop()}|{phones.pop()}"
    return None
