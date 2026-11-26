"""Measure structured profile uniqueness on a completed synthetic release."""

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re

from raksha.detection import identifier_kind
from raksha.release import _pointer


def field_pairs(record):
    if isinstance(record, dict):
        for label, value in record.items():
            yield label, value
            yield from field_pairs(value)
    elif isinstance(record, list):
        for value in record:
            yield from field_pairs(value)


def profile_uniqueness(output):
    """Return aggregate counts for indexed profiles with age bands and district."""
    by_file = defaultdict(list)
    index = (output / "records.jsonl").read_text(encoding="utf-8")
    for line in index.splitlines():
        item = json.loads(line)
        if item["patient"]:
            by_file[item["file"]].append(item)

    ages, districts = defaultdict(set), defaultdict(set)
    patients = set()
    sanitized = (output / "sanitized").resolve()
    for name, items in by_file.items():
        path = (output / name).resolve()
        if not path.is_relative_to(sanitized):
            raise ValueError("invalid_index_path")
        patients.update(item["patient"] for item in items)
        suffix = path.suffix.lower()
        if suffix in {".csv", ".tsv"}:
            with path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream, delimiter="\t" if suffix == ".tsv" else ","))
        elif suffix == ".json":
            document = json.loads(path.read_bytes())
        else:
            continue
        for item in items:
            loc = item.get("out", item["loc"])
            if suffix in {".csv", ".tsv"}:
                record = rows[int(loc.removeprefix("row:"))]
            else:
                record = document if loc == "doc" else _pointer(document, loc)
            for label, value in field_pairs(record):
                if not isinstance(value, str):
                    continue
                value = " ".join(value.casefold().split())
                if identifier_kind(label) == "AGE" and re.fullmatch(r"\d{1,3}(?:-\d{1,3}|\+)", value):
                    ages[item["patient"]].add(value)
                elif label.casefold() in {"district", "jila", "जिला"} and value and "[" not in value:
                    districts[item["patient"]].add(value)

    signatures = Counter(
        (frozenset(ages[patient]), frozenset(districts[patient]))
        for patient in ages.keys() & districts.keys()
    )
    return {
        "linked_profiles": len(patients),
        "profiles_with_age_band_and_district": sum(signatures.values()),
        "unique_profiles_in_covered_subset": sum(size == 1 for size in signatures.values()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(profile_uniqueness(args.output), sort_keys=True))


if __name__ == "__main__":
    main()
