# Hour 1 baseline

The submission starts from the organizer's Secret Wards starter, distributed under the included MIT license. Run the checks with the organizer checkout next to this repository.

```powershell
$env:PYTHONUTF8 = '1'
$env:RAKSHA_SECRET = 'practice'
python -m pip install -r requirements.txt
python main.py --input ../Secret-Wards/dev/input --output out
python ../Secret-Wards/validate_output.py --input ../Secret-Wards/dev/input --output out
python ../Secret-Wards/check_dev.py --output out
```

The validator returned `CONTRACT OK`. The starter processed 200 files, wrote 195 files, quarantined 5 and indexed 823 records. The practice checker detected 2,718 of 3,230 annotated personal-data items and all 4 canaries in the output. It found all 4,855 medical probes, zero patient links and zero raw copies of broken or unsupported files. These are practice diagnostics.

Three direct CLI runs passed the validator and left the input byte-identical. The sanitized tree and record index were byte-identical with the same secret and also with a different secret. The starter still needs to apply its keyed helpers to the exported data.

## Practice data profile

There are 101 TXT, 78 JSON, 17 CSV, and one each of TSV, XML, JPG and PDF by extension. The toolkit includes extension mismatches, so parsers need to inspect content.

| Registration source | Encoding and dates | Fields |
| --- | --- | --- |
| Arogya legacy | Windows-1252 CSV, month-first slashes | PatientID, LastName, FirstName, Sex, DOB (MM/DD/YYYY), Guardian, Street, City, District, Zip, Phone, Email, Registered (MM/DD/YYYY), Notes |
| District Hospital Hardoi | UTF-8 JSON, ISO dates | uhid, name, gender, dob, age, guardian, contact, address, ids, registered_on |
| Jeevanjyoti | UTF-16 TSV, day-first hyphens | Reg No, Naam, Ling, Umar, Janm Tithi, Pita/Pati ka Naam, Pata, Gaon, Tehsil, Jila, Pin Code, Mobile No, Aadhar, Registration Date |
| Sanjeevani | UTF-8 CSV, day-first slashes, duplicate export present | UHID, Patient Name, Gender, Age, DOB, Relation, Relative Name, Address, Village/Mohalla, Tehsil, District, PIN, Mobile, Aadhaar No, ABHA No, Reg Date |

The truth set contains 48 patients and labels 771 units as required and 2 as ambiguous for linkage. Registration identifiers include hospital-scoped registration numbers and UHIDs, Aadhaar and ABHA fields, and nested ID objects. Use field context before interpreting identifier shapes. Inspection should also cover filenames, headers, JSON keys, metadata and attachments. The largest baseline gaps are patient names, hospital IDs, relatives and locations, especially in Devanagari and Hinglish.

## Privacy design targets

Remove direct identifiers across every output surface. Use keyed per-patient pseudonyms and per-patient date shifts so the same patient retains consistent date intervals. Generalize age and location while keeping clinical values verbatim. Leave the patient link unset when evidence is ambiguous, and quarantine files that cannot be processed safely.

## P0 linkage and date checkpoint

Using the organizer ZIP, the validator passed all three runs. The practice checker reported 794 of 3,230 personal-data items still visible, 3 of 4 canaries found, and all 4,855 medical probes retained. Exact qualified hospital IDs achieved 1.00 precision, 0.63 recall, and 0.89 F0.5, with zero false merges. The same secret produced identical sanitized files and record indexes. A different secret changed all linked pseudonyms in this run.

## Decentralised P0 checkpoint

Separate local worker processes own parsing and sanitisation. The coordinator receives keyed linkage tokens and the assembler receives sanitised files and manifests. Hospital IDs are scoped. Cross-hospital merges require agreement on a single eligible national identifier without conflicting claims. An unassigned qualified ID can join an existing group only when it maps to one known hospital scope.

Three runs on the original ZIP returned `CONTRACT OK`. Same-secret exports and record indexes were byte-identical, and changing the secret changed the release. The checker reported 795 of 3,230 personal-data items still visible, three canaries found, and 4,855 of 4,855 medical probes retained. Linkage had 1.00 precision, 0.53 recall, and 0.85 F0.5 with zero false merges. Hospital scoping and conservative handling of unassigned records reduced recall from the previous shared-namespace prototype.

## Format and leak-check checkpoint

All three runs returned `CONTRACT OK`. CSV and TSV linked rows kept their original column counts and carried their pseudonyms in existing fields. The 19 practice FHIR Bundles retained resolvable internal references. The practice checker found 516 of 3,230 annotated items still visible, no planted canaries, and all 4,855 medical probes. Linkage was 1.00 precision, 0.56 recall and 0.87 F0.5 with zero false merges. Same-secret exports and record indexes were byte-identical. A different secret changed the release. Reference checks on these bundles do not establish full R4 schema conformance.

The next contextual detection pass added labelled Hindi patient and guardian names and Hinglish honorific patterns with clinician and clinical-word guards. The contract passed, 415 of 3,230 annotated items remained visible and the checker found no planted canaries. All 4,855 medical probes survived, and the linkage metrics held. Remaining exposure was higher in Devanagari and Hinglish than in Latin text.

Worker-local exact name matching reduced the remaining count to 375 of 3,230 without exposing the name lists through IPC. The assembler now checks the exact output record associated with each indexed pseudonym. Two practice runs passed the contract and produced identical sanitised files and record indexes. All 4,855 medical probes survived, and the checker found no planted canaries.
