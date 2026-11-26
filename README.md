# Secret Wards

Ghee Khatam's submission for Yugaantar DevForge Track 3 builds on the organizer's MIT-licensed starter. It uses only the Python standard library and runs offline on CPU. See [the baseline notes](docs/dev-baseline.md) for setup, practice results and known privacy gaps.

## Setup and run

Use Python 3.10 or later. Run from the repository root. The input must be a directory, and the output must be empty or absent and outside the input tree.

```bash
python -m pip install -r requirements.txt
RAKSHA_SECRET=practice python main.py --input ../Secret-Wards/dev/input --output out
```

PowerShell users can set the secret with `$env:RAKSHA_SECRET = 'practice'` before invoking Python. The example secret is for synthetic practice data. The evaluator supplies its own secret. No models or network calls are used at runtime.

The pipeline writes UTF-8 exports under `out/sanitized/`, a per-file SHA-256 manifest in `out/report.json`, and the record index in `out/records.jsonl`. Quarantined files appear in the manifest with a fixed reason code and no export.

```bash
python ../Secret-Wards/validate_output.py --input ../Secret-Wards/dev/input --output out
python ../Secret-Wards/check_dev.py --output out
python -m raksha.audit --output out
```

For scoring, use input unpacked directly from the organizer ZIP. Checkout line-ending conversions can change the truth hashes used to locate renamed files. The audit reports age-band and district uniqueness among indexed profiles with both fields. It emits aggregate counts only.

## Current privacy pipeline

The CLI routes known sources to hospital workers and sends other sources to an unassigned worker. Each worker parses and sanitises its own records in a separate local process. The workers exchange keyed linkage tokens and decisions with the coordinator through local pipes. The coordinator sees scoped hospital ID tokens and eligible shared national ID tokens, then returns pseudonyms and date offsets. The release assembler receives sanitised bytes and manifests.

Structured labels and free-text patterns drive redaction. File paths use keyed tokens. Linked records carry the same pseudonym in the output and the record index, and their recognized dates use a consistent per-patient offset. Explicit age and PIN fields become age bands and PIN prefixes.

Workers generalise structured village fields to an explicit tehsil or district from the record, and withhold the village when neither is reliable. For recognised non-FHIR JSON attachments, they clear opaque inline payloads and retain the surrounding record. The FHIR writer regenerates Bundle entry URLs and resource IDs together, rewrites local references and withholds attachment payloads. It quarantines unresolved references and unsupported contained resources. CSV exports preserve the column count and put a linked pseudonym in an existing identifier column. Recognised safe path components are retained and uncertain path components are keyed.

The worker checks rendered exports against the explicitly identified hospital IDs it extracted locally. Work remains on broader residual-PII checks, multilingual free-text coverage, full FHIR R4 conformance testing and routing for unfamiliar layouts. Run the toolkit's practice checker against the original ZIP data so its truth hashes match renamed outputs.

## P0 architecture workflow

1. Keep the published identity graph separate from the hospital-local timeline graph. An exact qualified encounter ID can preserve an interval across files without assigning a patient pseudonym. Conflicting patient evidence blocks encounter-level inheritance.
2. Plan the release from proposed profile values. The first pass combines linked profiles' proposed age bands and keyed coarse-geography values, then widens eligible age bands only when they gain comparison peers. Workers apply the revision before rendering. The assembler stages their outputs in memory and verifies file accounting and output mappings before writing. Profile-level geography escalation and broader disclosure checks remain planned.
3. Verify each change with a targeted fixture, the toolkit contract validator and the practice privacy, utility and linkage checks. Verify deterministic output before expanding the planner to more generalisation rules.

`config/policy.yaml` holds your privacy settings (age band width, date shift range, minimum group size).


## Security and limitations

The coordinator receives keyed linkage tokens. Hospital workers keep input records and matching evidence in process memory, and the assembler keeps candidate exports in memory until its structural checks pass. Raw input is opened read-only, and the CLI writes aggregate counts or fixed error codes. Evaluation uses synthetic inputs. At-rest protection for source and output files on real deployments belongs to the host or storage layer and is outside this implementation.

The workers share an OS account in the competition runtime, so the local process boundary limits normal data exchange. It supplies no protection against a compromised host. The practice audit covers structured age and district fields only. Hidden formats, unindexed records and other quasi-identifiers can expose additional risk. See the [two-page project brief](docs/project-brief.pdf) and [practice verification](docs/dev-baseline.md).
