"""Plan a bounded age-band revision from proposed released profile values."""

from collections import Counter, defaultdict
import csv
import io
import json
from pathlib import PurePosixPath

from raksha.detection import identifier_kind, is_coarse_location


def age_value(value):
    if type(value) not in (str, int):
        return None
    text = str(value).strip()
    if 1 <= len(text) <= 3 and text.isdecimal() and int(text) <= 125:
        return int(text)
    return None


def proposed_profile_fields(record, width, geography_token):
    """Return only generalised ages and keys for equality on coarse locations."""
    if not isinstance(record, dict):
        return (), ()
    ages, places = set(), set()
    pending = [record]
    while pending:
        fields = pending.pop()
        for label, value in fields.items():
            if isinstance(value, dict):
                pending.append(value)
            elif identifier_kind(label) == "AGE" and (age := age_value(value)) is not None:
                ages.add(age // width * width)
            elif is_coarse_location(label) and isinstance(value, str) and value.strip():
                places.add(geography_token(" ".join(value.casefold().split())))
    return tuple(sorted(ages)), tuple(sorted(places))


def plan_age_bands(candidates, width, min_group_size):
    """Widen only when a group of small profiles gains comparison peers."""
    ages, places = defaultdict(set), defaultdict(set)
    for patient, bands, geography in candidates:
        ages[patient].update(bands)
        places[patient].update(geography)

    signatures = {
        patient: (tuple(sorted(bands)), tuple(sorted(places[patient])))
        for patient, bands in ages.items()
        if bands
    }
    counts = Counter(signatures.values())
    offered = defaultdict(list)
    for patient, (bands, geography) in signatures.items():
        if counts[(bands, geography)] < min_group_size:
            wider = tuple(sorted({band // (2 * width) * (2 * width) for band in bands}))
            offered[wider, geography].append(patient)

    return frozenset(
        patient
        for cohort in offered.values()
        for patient in cohort
        if len(cohort) > counts[signatures[patient]]
    )


def _contains_patient(value, patient):
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif item == patient:
            return True
    return False


def _pointer(data, pointer):
    for component in pointer.split("/")[1:]:
        key = component.replace("~1", "/").replace("~0", "~")
        if isinstance(data, list):
            if not key.isascii() or not key.isdecimal() or (len(key) > 1 and key[0] == "0"):
                raise ValueError("invalid_record_pointer")
            data = data[int(key)]
        elif isinstance(data, dict):
            data = data[key]
        else:
            raise ValueError("invalid_record_pointer")
    return data


def validate_record_index(name, payload, records):
    """Assert that each indexed output record exists and contains its claimed pseudonym."""
    if not records:
        return
    suffix = PurePosixPath(name).suffix.casefold()
    try:
        if suffix in {".csv", ".tsv"}:
            delimiter = "\t" if suffix == ".tsv" else ","
            rows = list(csv.reader(io.StringIO(payload.decode("utf-8"), newline=""), delimiter=delimiter))
            for record in records:
                locator = record.get("out", record["loc"])
                index = locator.removeprefix("row:")
                if not locator.startswith("row:") or not index.isascii() or not index.isdecimal():
                    raise ValueError("invalid_row_locator")
                row = rows[int(index) + 1]
                if record["patient"] is not None and record["patient"] not in row:
                    raise ValueError("missing_patient_pseudonym")
        elif suffix == ".json":
            document = json.loads(payload)
            for record in records:
                locator = record.get("out", record["loc"])
                if locator != "doc" and not locator.startswith("/"):
                    raise ValueError("invalid_json_locator")
                value = document if locator == "doc" else _pointer(document, locator)
                if record["patient"] is not None and not _contains_patient(value, record["patient"]):
                    raise ValueError("missing_patient_pseudonym")
        else:
            text = payload.decode("utf-8")
            for record in records:
                if record["loc"] != "doc":
                    raise ValueError("invalid_document_locator")
                if record["patient"] is not None and f"Patient: {record['patient']}" not in text.splitlines():
                    raise ValueError("missing_patient_pseudonym")
    except (ValueError, TypeError, IndexError, KeyError, csv.Error):
        raise RuntimeError("invalid_release_record_index") from None
