"""Plan a bounded age-band revision from proposed released profile values."""

from collections import Counter, defaultdict
import csv
import io
import json
from pathlib import PurePosixPath

from raksha.detection import identifier_kind, is_coarse_location, is_lower_region


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
        return (), (), ()
    ages, places, parents = set(), set(), set()
    pending = [record]
    while pending:
        fields = pending.pop()
        for label, value in fields.items():
            if isinstance(value, dict):
                pending.append(value)
            elif identifier_kind(label) == "AGE" and (age := age_value(value)) is not None:
                ages.add(age // width * width)
            elif is_coarse_location(label) and isinstance(value, str) and value.strip():
                token = geography_token(" ".join(value.casefold().split()))
                (places if is_lower_region(label) else parents).add(token)
    return tuple(sorted(ages)), tuple(sorted(places)), tuple(sorted(parents))


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


def plan_release_fields(candidates, width, min_group_size):
    widened = plan_age_bands(
        ((patient, ages, tuple(sorted(set(places) | set(parents))))
         for patient, ages, places, parents in candidates), width, min_group_size,
    )
    profiles = defaultdict(lambda: (set(), set(), set()))
    for patient, ages, places, parents in candidates:
        profile = profiles[patient]
        for target, values in zip(profile, (ages, places, parents)):
            target.update(values)
    signatures = {}
    for patient, (ages, places, parents) in profiles.items():
        if ages:
            size = 2 * width if patient in widened else width
            signatures[patient] = (
                size, frozenset(age // size * size for age in ages), frozenset(places), frozenset(parents),
            )
    counts = Counter(signatures.values())
    options = defaultdict(set)
    for patient, signature in signatures.items():
        size, ages, places, parents = signature
        if places and parents and counts[signature] < min_group_size:
            options[size, ages, parents].add(patient)
    coarse = {
        patient for group in options.values() for patient in group
        if len(group) > counts[signatures[patient]]
    }

    # When no explicit broader region exists, withhold lower geography only if
    # the *resulting* age-band cohort meets the configured minimum.
    no_parent_options = defaultdict(set)
    for patient, (size, ages, places, parents) in signatures.items():
        if not parents and counts[signatures[patient]] < min_group_size:
            no_parent_options[size, ages].add(patient)
    for group in no_parent_options.values():
        if len(group) >= min_group_size:
            coarse.update(patient for patient in group if profiles[patient][1])

    revisions = {patient: (2 * width if patient in widened else None, patient in coarse)
                 for patient in widened | coarse}

    # Consider a wider age band only when a complete cohort can reach the
    # minimum without further changing its remaining geography.
    wider_options = defaultdict(set)
    final = {}
    for patient, (size, ages, places, parents) in signatures.items():
        if patient in coarse:
            places = frozenset()
        final[patient] = (size, ages, places, parents)
    final_counts = Counter(final.values())
    for patient, (size, ages, places, parents) in final.items():
        if final_counts[final[patient]] < min_group_size:
            max_width = 4 * width
            broader = frozenset(age // max_width * max_width for age in ages)
            wider_options[broader, places, parents].add(patient)
    for group in wider_options.values():
        if len(group) >= min_group_size:
            for patient in group:
                revisions[patient] = (4 * width, patient in coarse)

    # Try the combined revision last. It must form a full-sized group of
    # candidates with compatible published age bands and broader locations.
    combined = defaultdict(set)
    for patient, (size, ages, places, parents) in signatures.items():
        if final_counts[final[patient]] >= min_group_size:
            continue
        if revisions.get(patient, (None, False))[0] == 4 * width:
            continue
        broader = frozenset(age // (4 * width) * (4 * width) for age in ages)
        combined[broader, parents].add(patient)
    for group in combined.values():
        if len(group) >= min_group_size:
            for patient in group:
                revisions[patient] = (4 * width, bool(profiles[patient][1]))
    return revisions


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
