# Secret Wards

Ghee Khatam's submission for Yugaantar DevForge Track 3 builds on the organizer's MIT-licensed starter. It uses only the Python standard library and runs offline on CPU. See [the baseline notes](docs/dev-baseline.md) for setup, practice results and known privacy gaps.

Copy this folder's contents to the root of **your own** repository and build from there.

```bash
RAKSHA_SECRET=practice python3 main.py --input ../dev/input --output ../my_output
```

## What it already does right

| ✅ | Done for you |
|---|---|
| reads every file in a fixed order | deterministic output |
| decodes UTF-8, UTF-8-BOM, UTF-16 and cp1252 | writes UTF-8 |
| keeps CSV as CSV and JSON as JSON | same delimiter, header and structure |
| quarantines PDF, images, XML, empty and broken JSON files | never copies them raw |
| writes `report.json` | SHA-256 per file, honest counts, timing, memory |
| writes `records.jsonl` | correct `row:N`, `/json/pointer` and `doc` locators |
| `pseudonym()` | keyed HMAC fake IDs (`PSN-XXXXXX`) from `RAKSHA_SECRET` |
| `date_shift_days()`, `shift_date()`, `age_band()` | per-patient date shifting and age bands |
| prints only counts | stdout, stderr and logs are scanned for PII |

## Current privacy pipeline

The CLI routes known sources to hospital workers and sends other sources to an unassigned worker. Each worker parses and sanitises its own records in a separate local process. The workers exchange keyed linkage tokens and decisions with the coordinator through local pipes. The coordinator sees scoped hospital ID tokens and eligible shared national ID tokens, then returns pseudonyms and date offsets. The release assembler receives sanitised bytes and manifests.

Structured labels and free-text patterns drive redaction. File paths use keyed tokens. Linked records carry the same pseudonym in the output and the record index, and their recognized dates use a consistent per-patient offset. Explicit age and PIN fields become age bands and PIN prefixes.

Workers generalise structured village fields to an explicit tehsil or district from the record, and withhold the village when neither is reliable. For recognised non-FHIR JSON attachments, they clear opaque inline payloads and retain the surrounding record. Work remains on hospital routing for unfamiliar layouts, multilingual free-text coverage, FHIR references and attachments, and a release-wide leak gate. Run the toolkit's practice checker against the original ZIP data so its truth hashes match renamed outputs.

## P0 architecture workflow

1. Keep the published identity graph separate from the hospital-local timeline graph. An exact qualified encounter ID can preserve an interval across files without assigning a patient pseudonym. Conflicting patient evidence blocks encounter-level inheritance.
2. Plan the release from proposed profile values. The first pass combines linked profiles' proposed age bands and keyed coarse-geography values, then widens eligible age bands only when they gain comparison peers. Workers apply the revision before rendering. The assembler stages their outputs in memory and verifies file accounting and output mappings before writing. Profile-level geography escalation and broader disclosure checks remain planned.
3. Verify each change with a targeted fixture, the toolkit contract validator and the practice privacy, utility and linkage checks. Verify deterministic output before expanding the planner to more generalisation rules.

`config/policy.yaml` holds your privacy settings (age band width, date shift range, minimum group size).
