#!/usr/bin/env python3
"""Secret Wards starter: a correct *skeleton*, not a solution.

It already does the boring, contract-critical parts right:
  * walks every input file in a fixed order (deterministic output),
  * decodes UTF-8 / UTF-8-BOM / UTF-16 / cp1252 and writes UTF-8,
  * keeps CSV as CSV (same delimiter, same header), JSON as JSON (same structure),
  * quarantines anything it cannot parse instead of copying it,
  * writes report.json (SHA-256 per input file, honest counts, timing, memory),
  * writes records.jsonl with the right locators (row:N, /json/pointer, doc),
  * gives you keyed HMAC pseudonyms and per-patient date shifting helpers,
  * never prints, logs or stores personal data or RAKSHA_SECRET.

What it does NOT do is the actual challenge. Search for "TODO(team)".
As shipped it is roughly the "naive regex" level: it passes CONTRACT OK and scores low.

Usage: python main.py --input <input dir> --output <empty output dir>
Standard library only, Python 3.10+.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import datetime as dt
import hashlib
import hmac
import io
import json
import os
import re
import sys
import time
from pathlib import Path

from raksha.dates import infer_date_order, shift_dates
from raksha.detection import (
    identifier_kind, is_coarse_location, known_name_keys, redact_contextual_names,
    redact_known_names, village_region,
)
from raksha.distributed import coordinate, identity_groups, linkage_token, partition
from raksha.fhir import patient_evidence, rewrite_bundle
from raksha.ingestion import Quarantine, parse
from raksha.linkage import patient_key, redact_labelled_ids, shared_identity
from raksha.release import age_value, plan_age_bands, proposed_profile_fields, validate_record_index
from raksha.timeline import encounter_key, encounter_offsets, redact_encounter

ATTACHMENT_FIELDS = {"attachment", "attachments"}

# --------------------------------------------------------------------------- policy
def load_policy(path: Path) -> dict:
    """Tiny `key: value` reader for config/policy.yaml (no PyYAML needed)."""
    policy = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" in line:
                k, v = (x.strip() for x in line.split(":", 1))
                policy[k] = int(v) if v.lstrip("-").isdigit() else v
    return policy


HERE = Path(__file__).resolve().parent
POLICY = load_policy(HERE / "config" / "policy.yaml")
SECRET = os.environ.get("RAKSHA_SECRET", "").encode()  # never print or write this


def release_key(purpose: bytes) -> bytes:
    return hmac.digest(SECRET, b"raksha/release/" + purpose, "sha256")


# --------------------------------------------------------------------------- pseudonyms & dates
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U


def pseudonym(patient_key: str) -> str:
    """Stable, non-reversible ID: HMAC-SHA256 keyed with RAKSHA_SECRET (never a plain hash).

    Same key + same secret -> same ID in every file. A different secret -> a different ID.
    patient_key should be YOUR canonical identity for a cluster of records (see link_records).
    """
    digest = hmac.digest(release_key(b"patient"), patient_key.encode("utf-8"), "sha256")
    n = int.from_bytes(digest[:5], "big")
    code = "".join(_ALPHABET[(n >> (5 * i)) & 31] for i in range(6))
    return f"PSN-{code}"


def date_shift_days(patient_key: str) -> int:
    """Per-patient shift in [-max, +max], never 0. Shift every date of one patient by the
    SAME amount and a 9-day stay stays 9 days."""
    m = int(POLICY.get("date_shift_max_days", 180))
    d = hmac.digest(release_key(b"date"), patient_key.encode("utf-8"), "sha256")
    v = int.from_bytes(d[:4], "big") % (2 * m) - m
    return v if v != 0 else 1


def shift_date(value: dt.date, patient_key: str) -> dt.date:
    return value + dt.timedelta(days=date_shift_days(patient_key))


def age_band(age: int, width: int | None = None) -> str:
    """5-year bands by default; the band must CONTAIN the true age."""
    w = width if width is not None else int(POLICY.get("age_band_years", 5))
    lo = (age // w) * w
    return f"{lo}-{lo + w - 1}"


# --------------------------------------------------------------------------- detection
# TODO(team): this is the part that wins or loses the event. Ideas, in rough order of value:
#   * column-aware rules: a column named like a name/phone/address is PII whatever it contains
#     (but expect renamed columns on hidden data: "Patient's Name", "Gram/Mohalla", ...);
#   * a name gazetteer in Latin AND Devanagari, transliteration (Mohammad/Mohd/Md./मोहम्मद),
#     honorifics (ji, sahab, didi, श्री), relatives (S/o, D/o, W/o, C/O <name>);
#   * the meaning traps: "C/O fever" is a complaint, "Dr. Ramesh" stays, "Dolo 650", "5 mg",
#     "1-0-1" are doses, "Parkinson's disease" is not a person;
#   * JSON keys, CSV headers, file names and base64 attachments can all hold PII.
PATTERNS = [
    ("PHONE", re.compile(r"(?<!\d)(?:\+?(?:91|९१)[ \t-]?)?[6-9६-९]\d{4}[ \t-]?\d{5}(?!\d)")),
    ("AADHAAR", re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")),
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("AADHAAR", re.compile(r"(?i)\b[x*]{4}[ -]?[x*]{4}[ -]?\d{4}\b")),
    ("NAME", re.compile(
        r"(?im)(?<=^)([ \t]*(?:patient[ \t]+name|relative[ \t]+name|"
        r"guardian[ \t]+name|naam|नाम|name)[ \t]*:[ \t]*)[^\r\n,;|]+"
    )),
    ("NAME", re.compile(
        r"(?m)^([ \t]*(?:[01]\d|2[0-3]):[0-5]\d[ \t]*[-–][ \t]*)"
        r"[A-Z][\w.'’-]*(?:[ \t]+[A-Z][\w.'’-]*){0,3}"
        r"(?=[ \t]*\((?i:attendant|visitor|guardian|relative)\b)"
    )),
    ("NAME", re.compile(
        r"(\b(?i:called by)[ \t]+)[A-Z][\w.'’-]*(?:[ \t]+[A-Z][\w.'’-]*){0,3}"
        r"(?=[ \t]+(?:\[PHONE\]|\+?\d))"
    )),
    ("RELATIVE", re.compile(
        r"(?m)(\b(?:[SDWsdw]/[Oo]|पुत्र|पुत्री|पत्नी)[ \t]+)"
        r"[^\W\d_][\w\u0900-\u097f.'’-]*(?:[ \t]+"
        r"(?:[A-Z][\w.'’-]*|[\u0900-\u097f]+)){1,3}"
    )),
]


class Stats:
    identifiers = 0
    records = 0
    linked = 0
    generalized = 0
    suppressed = 0
    transformations = 0
    known_ids = frozenset()
    known_names = frozenset()


_ID_WORD = re.compile(r"(?<![\w/-])[A-Z]{2,}[A-Z0-9/-]*\d{3,}(?![\w/-])", re.IGNORECASE)


def clean_text(text: str) -> str:
    """Replace detected identifiers with typed placeholders. TODO(team): much more than regex."""
    for kind, rx in PATTERNS:
        replacement = rf"\1[{kind}]" if kind in {"NAME", "RELATIVE"} else f"[{kind}]"
        text, n = rx.subn(replacement, text)
        Stats.identifiers += n
    text, contextual_count = redact_contextual_names(text)
    Stats.identifiers += contextual_count
    text, known_count = redact_known_names(text, Stats.known_names)
    Stats.identifiers += known_count
    def redact_known_id(match):
        if match[0].upper() in Stats.known_ids:
            Stats.identifiers += 1
            return "[MRN]"
        return match[0]

    if Stats.known_ids:
        text = _ID_WORD.sub(redact_known_id, text)
    return text


def clean_value(v, kind=None, *, fhir=False, days=0, month_first=None, age_width=None,
                region=None, attachment=False):
    if kind == "VILLAGE" and isinstance(v, str) and v.strip():
        Stats.transformations += 1
        return clean_text(region) if region and region.casefold() != v.strip().casefold() else "[VILLAGE]"
    if kind in {"AGE", "PIN"} and (isinstance(v, str) or type(v) is int):
        value = str(v).strip()
        if kind == "AGE" and (age := age_value(v)) is not None:
            Stats.transformations += 1
            return age_band(age, age_width)
        if kind == "PIN" and re.fullmatch(r"\d{6}", value):
            Stats.transformations += 1
            return f"{int(value[:3]):03d}***"
        # Keep existing age bands and PIN prefixes.
        if re.fullmatch(r"\d{1,3}[-–]\d{1,3}|\d{1,3}\+|\d{3}\*{3}", value):
            return v
    if isinstance(v, str):
        if kind == "DOB" and days:
            shifted = shift_dates(v, days, month_first=month_first)
            if shifted != v:
                return shifted
        if kind and v.strip():
            Stats.identifiers += 1
            return f"[{kind}]"
        return clean_text(shift_dates(v, days, month_first=month_first) if days else v)
    if kind and type(v) in (int, float):
        Stats.identifiers += 1
        return type(v)(0)
    if isinstance(v, list):
        return [
            clean_value(x, kind, fhir=fhir, days=days, month_first=month_first,
                        age_width=age_width, region=region, attachment=attachment)
            for x in v
        ]
    if isinstance(v, dict):
        result = {}
        local_region = village_region(v.items()) if not fhir else None
        content_type = v.get("contentType", v.get("content_type"))
        inline_payload = attachment and isinstance(content_type, str)
        for label, value in v.items():
            key = clean_text(label)
            if key in result:
                stem = key
                index = 2
                while key in result or key in v:
                    key = f"{stem}_{index}"
                    index += 1
            field_kind = None if fhir else identifier_kind(label)
            inherited_kind = None if kind == "ADDRESS" and is_coarse_location(label) else kind
            if inline_payload and label.casefold() == "data" and isinstance(value, str) and value:
                result[key] = ""
                Stats.transformations += 1
                continue
            result[key] = clean_value(
                value, field_kind or inherited_kind, fhir=fhir, days=days,
                month_first=month_first, age_width=age_width, region=local_region,
                attachment=not fhir and label.casefold() in ATTACHMENT_FIELDS,
            )
        return result
    return v  # numbers, booleans, null keep their type


# --------------------------------------------------------------------------- linkage
# --------------------------------------------------------------------------- I/O
def process_csv(rows: list[list[str]], delimiter: str, rel: str, records: list, lookup) -> str:
    if not rows:
        return ""
    header, body = rows[0], rows[1:]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    kinds = [identifier_kind(label) for label in header]
    decisions = [lookup(dict(zip(header, row))) for row in body]
    orders = [
        True if "mm/dd" in label.casefold() else
        False if "dd/mm" in label.casefold() else
        infer_date_order(row[index] for row in body if index < len(row))
        for index, label in enumerate(header)
    ]
    w.writerow([clean_text(label) for label in header])
    for i, (row, (pid, days, age_width)) in enumerate(zip(body, decisions)):
        before = Stats.transformations
        region = village_region(zip(header, row))
        cleaned = [
            clean_value(cell, kinds[index] if index < len(kinds) else None, days=days, age_width=age_width,
                        month_first=orders[index] if index < len(orders) else None, region=region)
            for index, cell in enumerate(row)
        ]
        if pid:
            slot = next((index for index, (kind, cell) in enumerate(zip(kinds, row))
                         if kind == "MRN" and cell.strip()), None)
            if slot is None:
                pid = None
            else:
                cleaned[slot] = pid
        w.writerow(cleaned)
        Stats.generalized += Stats.transformations > before
        records.append({"file": f"sanitized/{rel}", "loc": f"row:{i}", "patient": pid})
        Stats.records += 1
        Stats.linked += pid is not None
    return buf.getvalue()


def process_json(data, is_fhir: bool, rel: str, records: list, lookup) -> str:
    if is_fhir:
        pid, days, _ = lookup(patient_evidence(data))
        key = hmac.digest(release_key(b"fhir"), rel.encode("utf-8"), "sha256")
        cleaned = rewrite_bundle(
            data, key, clean_text, pid, lambda value: shift_dates(value, days) if days else value,
        )
        records.append({"file": f"sanitized/{rel}", "loc": "doc", "patient": pid})
        return json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n"
    is_doc = is_fhir or not isinstance(data, dict) or not any(
        is_record_list(label, value) for label, value in data.items()
    )
    if is_doc:  # FHIR Bundle or single object: one record for the whole file
        cleaned, pid = clean_json_record(data, lookup, fhir=is_fhir)
        records.append({"file": f"sanitized/{rel}", "loc": "doc", "patient": pid})
        Stats.records += 1
    else:
        cleaned = {}
        for source_key, values in data.items():
            output_key = clean_text(source_key)
            stem, index = output_key, 2
            while output_key in cleaned:
                output_key = f"{stem}_{index}"
                index += 1
            if is_record_list(source_key, values):
                cleaned[output_key] = []
                pointer_key = source_key.replace("~", "~0").replace("/", "~1")
                output_pointer = output_key.replace("~", "~0").replace("/", "~1")
                for i, value in enumerate(values):
                    cleaned_record, pid = clean_json_record(value, lookup)
                    cleaned[output_key].append(cleaned_record)
                    loc = f"/{pointer_key}/{i}"
                    record = {"file": f"sanitized/{rel}", "loc": loc, "patient": pid}
                    if output_pointer != pointer_key:
                        record["out"] = f"/{output_pointer}/{i}"
                    records.append(record)
                    Stats.records += 1
            else:
                cleaned[output_key] = clean_value(
                    values, identifier_kind(source_key),
                    attachment=source_key.casefold() in ATTACHMENT_FIELDS,
                )
    return json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n"


def clean_json_record(data, lookup, *, fhir=False):
    pid, days, age_width = lookup(data) if not fhir and isinstance(data, dict) else (None, 0, None)
    before = Stats.transformations
    cleaned = clean_value(data, fhir=fhir, days=days, age_width=age_width)
    Stats.generalized += Stats.transformations > before
    if pid:
        cleaned["raksha_patient"] = pid
    return cleaned, pid


def process_text(text: str, rel: str, records: list, lookup) -> str:
    pid, days, _ = lookup(text)
    records.append({"file": f"sanitized/{rel}", "loc": "doc", "patient": pid})
    Stats.records += 1
    text, removed = redact_labelled_ids(text)
    Stats.identifiers += removed
    text, removed = redact_encounter(text)
    Stats.identifiers += removed
    if days:
        text = shift_dates(text, days, month_first=infer_date_order([text]))
    cleaned = clean_text(text)
    return f"Patient: {pid}\n{cleaned}" if pid else cleaned


_SAFE_PATH_WORDS = set("""
    admission arogya billing bundle census claims clean discharge dhh dhhardoi
    distribution drug encounter export fhir formulary hardoi hospital input jeevanjyoti
    lab legacy misc note notes nursing opd outpatient patient patients prescription
    prescriptions protocol range ranges records reference registration report results
    rx sanjeevani summary visit visits ward
""".split())


def safe_path_stem(stem: str) -> bool:
    words = re.split(r"[_-]", stem.casefold())
    return bool(words) and all(word in _SAFE_PATH_WORDS or re.fullmatch(r"[0-9]{1,4}", word)
                               for word in words) and any(word in _SAFE_PATH_WORDS for word in words)


def release_path(relative: Path, suffix: str) -> str:
    parts = []
    for index, part in enumerate(relative.parts):
        is_file = index == len(relative.parts) - 1
        stem = Path(part).stem if is_file else part
        if safe_path_stem(stem) and (not is_file or Path(part).suffix.lower() == suffix):
            parts.append(part)
            continue
        source = "/".join(relative.parts[:index + 1]).encode("utf-8")
        token = hmac.digest(release_key(b"path"), source, "sha256").hex()[:24]
        parts.append(token + (suffix if is_file else ""))
    return "/".join(parts)


def peak_rss_mb() -> float:
    try:
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(r / 1024 if sys.platform != "darwin" else r / 1048576, 1)
    except Exception:  # noqa: BLE001 - not available on every OS
        return 0.0


def is_record_list(label, value):
    return (label.casefold() not in ATTACHMENT_FIELDS and isinstance(value, list)
            and bool(value) and all(isinstance(item, dict) for item in value))


def evidence_records(doc):
    data = doc.content
    if doc.kind == "delimited" and data:
        for row in data[1:]:
            yield dict(zip(data[0], row))
    elif doc.kind == "json" and isinstance(data, dict):
        lists = [value for label, value in data.items() if is_record_list(label, value)]
        if lists:
            for values in lists:
                yield from values
        else:
            yield data
    elif doc.kind == "text":
        yield data
    elif doc.kind == "fhir":
        yield patient_evidence(data)


def resolve(batches):
    decisions = defaultdict(dict)
    for namespace, local, group in identity_groups(batches):
        decisions[namespace][local] = (pseudonym(group), date_shift_days(group))
    return decisions


def release_revisions(candidates):
    return plan_age_bands(candidates, int(POLICY.get("age_band_years", 5)),
                          int(POLICY.get("min_group_size", 5)))


def hospital_worker(connection, namespace, paths):
    try:
        evidence, documents = set(), []
        known_ids = set()
        known_names = set()
        for index, path, relative in paths:
            raw = path.read_bytes()
            entry = {"input_sha256": hashlib.sha256(raw).hexdigest()}
            try:
                doc = parse(raw, path.suffix.lower())
            except Quarantine as exc:
                doc = None
                entry.update(output=None, status="quarantined", reason=str(exc))
            documents.append((index, relative, entry, doc))
            if doc is not None:
                for record in evidence_records(doc):
                    known_names.update(known_name_keys(record))
                    key = patient_key(record)
                    if key:
                        known_ids.add(key.split("|", 1)[1])
                        shared = shared_identity(record) if namespace != "unassigned" else None
                        evidence.add((linkage_token(SECRET, namespace, key),
                                      linkage_token(SECRET, "qualified", key),
                                      linkage_token(SECRET, "shared", shared) if shared else ""))
        connection.send(("evidence", evidence))
        Stats.known_ids = frozenset(known_ids)
        Stats.known_names = frozenset(known_names)
        decisions = connection.recv()

        def identity(record):
            key = patient_key(record)
            if key:
                return decisions.get(linkage_token(SECRET, namespace, key), (None, 0))
            return None, 0

        width = int(POLICY.get("age_band_years", 5))
        candidates = set()
        for _, _, _, doc in documents:
            if doc is None:
                continue
            for record in evidence_records(doc):
                patient, _ = identity(record)
                if patient:
                    bands, geography = proposed_profile_fields(
                        record, width, lambda value: linkage_token(SECRET, "release-geography", value),
                    )
                    if bands or geography:
                        candidates.add((patient, bands, geography))
        connection.send(("candidates", candidates))
        revisions = connection.recv()

        offsets = {}
        if namespace != "unassigned":
            offsets = encounter_offsets(
                (record for _, _, _, doc in documents if doc is not None
                 for record in evidence_records(doc)),
                identity,
                lambda encounter: date_shift_days(f"encounter|{namespace}|{encounter}"),
            )

        def lookup(record):
            pid, days = identity(record)
            encounter = encounter_key(record)
            return pid, offsets.get(encounter, days), 2 * width if pid in revisions else None

        results = []
        for index, relative, entry, doc in documents:
            result = None
            records = []
            if doc is not None:
                suffix = ".json" if doc.kind in ("json", "fhir") else relative.suffix.lower()
                rel = release_path(relative, suffix)
                try:
                    if doc.kind == "delimited":
                        text = process_csv(doc.content, doc.delimiter, rel, records, lookup)
                    elif doc.kind in ("json", "fhir"):
                        text = process_json(doc.content, doc.kind == "fhir", rel, records, lookup)
                    else:
                        text = process_text(doc.content, rel, records, lookup)
                    if any(match[0].upper() in Stats.known_ids for match in _ID_WORD.finditer(text)):
                        raise Quarantine("residual_hospital_id")
                    result = text.encode("utf-8")
                    entry.update(output=f"sanitized/{rel}", status="sanitized")
                except UnicodeError:
                    records.clear()
                    entry.update(output=None, status="quarantined", reason="unencodable_output")
                except Quarantine as exc:
                    records.clear()
                    entry.update(output=None, status="quarantined", reason=str(exc))
            results.append((index, entry, result, records))
        connection.send(("release", (results, Stats.identifiers, Stats.generalized, peak_rss_mb())))
    except Exception:
        connection.send(("error", None))
    finally:
        connection.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Secret Wards starter pipeline")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    if not SECRET:
        print("RAKSHA_SECRET is required", file=sys.stderr)
        return 2
    t0 = time.monotonic()
    inp, out = Path(a.input).resolve(), Path(a.output).resolve()
    if not inp.is_dir() or out == inp or inp in out.parents:
        print("invalid_input_or_output", file=sys.stderr)
        return 2
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        print("output_must_be_empty", file=sys.stderr)
        return 2
    jobs = defaultdict(list)
    paths = sorted(p for p in inp.rglob("*") if p.is_file())
    for index, path in enumerate(paths):
        relative = path.relative_to(inp)
        jobs[partition(relative)].append((index, path, relative))

    staged = []
    identifiers = generalized = 0
    worker_memory = 0.0
    try:
        for results, batch_identifiers, batch_generalized, memory in coordinate(
            jobs, hospital_worker, resolve, release_revisions
        ):
            identifiers += batch_identifiers
            generalized += batch_generalized
            worker_memory = max(worker_memory, memory)
            staged.extend(results)
        staged.sort(key=lambda item: item[0])
        if [index for index, _, _, _ in staged] != list(range(len(paths))):
            raise RuntimeError("invalid_file_accounting")
        output_paths = set()
        for _, entry, result, entries in staged:
            if result is None:
                if entry["output"] is not None or entries:
                    raise RuntimeError("invalid_quarantine")
                continue
            name = entry["output"]
            if name in output_paths or any(record["file"] != name for record in entries):
                raise RuntimeError("invalid_output_mapping")
            validate_record_index(name, result, entries)
            output_paths.add(name)
        (out / "sanitized").mkdir(parents=True, exist_ok=True)
        for _, entry, result, _ in staged:
            if result is not None:
                dest = out / entry["output"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(result)
    except (EOFError, OSError, RuntimeError):
        print("release_failed", file=sys.stderr)
        return 1
    records = [record for _, _, _, entries in staged for record in entries]
    files = [entry for _, entry, _, _ in staged]

    with open(out / "records.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    n_san = sum(e["status"] == "sanitized" for e in files)
    report = {
        "schema": "raksha-report/1",
        "files": files,
        "counts": {
            "files_total": len(files), "files_sanitized": n_san, "files_quarantined": len(files) - n_san,
            "records_processed": len(records), "identifiers_detected": identifiers,
            "records_linked": sum(r["patient"] is not None for r in records),
            "records_generalized": generalized, "records_suppressed": Stats.suppressed,
            "records_quarantined": 0,
        },
        "timing": {"seconds": round(time.monotonic() - t0, 2)},
        "resources": {"peak_rss_mb": max(peak_rss_mb(), worker_memory)},
    }
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    # Only counts go to stdout: stdout and stderr are scanned for PII.
    print(f"files {len(files)} sanitized {n_san} quarantined {len(files) - n_san} records {len(records)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
