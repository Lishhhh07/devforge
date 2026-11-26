"""Contract regressions using new synthetic records, independent of the organizer data."""

import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from main import resolve
from raksha.distributed import identity_groups
from raksha.linkage import corroborating_identity
from raksha.release import plan_release_fields


ROOT = Path(__file__).resolve().parents[1]


def snapshot(root):
    return {path.relative_to(root): hashlib.sha256(path.read_bytes()).digest()
            for path in root.rglob("*") if path.is_file()}


class TrackThreeTest(unittest.TestCase):
    def test_combined_privacy_revision_requires_a_complete_comparison_cohort(self):
        candidates = [(str(i), (age,), (f"place-{i}",), ())
                      for i, age in enumerate((25, 30, 35, 25, 30))]
        self.assertEqual(plan_release_fields(candidates[:-1], 5, 5), {})
        self.assertEqual(plan_release_fields(candidates, 5, 5),
                         {str(i): (20, True) for i in range(5)})

    def test_cross_worker_fragment_and_geography_revision(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            workspace = Path(directory)
            inputs, output = workspace / "input", workspace / "release"
            inputs.mkdir()
            rows = [
                ("arogya_registration.csv", "AST-312", "Ravin Mehra", "8123450679", "West District"),
                ("sanjeevani_registration.csv", "SUN-893", "Tanuja Vyas", "8452739016", "East District"),
            ]
            for filename, identifier, name, phone, district in rows:
                (inputs / filename).write_text(
                    "UHID,Patient Name,Mobile,Age,District,State,Dose\n"
                    f"{identifier},{name},{phone},42,{district},Uttar Pradesh,5 mg\n",
                    encoding="utf-8",
                )
            (inputs / "notes.txt").write_text(
                "Patient Name: Ravin Mehra\nPhone: +91 81234-50679\n2026-03-01\n"
                "Ramipril 5 mg\n", encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "main.py"), "--input", str(inputs), "--output", str(output)],
                cwd=ROOT, env={**os.environ, "RAKSHA_SECRET": "privacy-fixture"},
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            exported = {}
            for filename, *_ in rows:
                path = output / "sanitized" / filename
                with path.open(encoding="utf-8", newline="") as stream:
                    exported[filename] = next(csv.DictReader(stream))
                self.assertEqual(exported[filename]["District"], "[REGION]")
                self.assertEqual(exported[filename]["State"], "Uttar Pradesh")
                self.assertEqual(exported[filename]["Dose"], "5 mg")
            first = exported[rows[0][0]]["UHID"]
            second = exported[rows[1][0]]["UHID"]
            self.assertNotEqual(first, second)
            note = (output / "sanitized/notes.txt").read_text(encoding="utf-8")
            self.assertIn(f"Patient: {first}\n", note)
            self.assertNotIn("Ravin Mehra", note)
            self.assertNotIn("2026-03-01", note)

    def test_name_and_phone_only_attach_to_unambiguous_anchored_groups(self):
        name = "Ravin Mehra"
        support = corroborating_identity({"Patient Name": name, "Mobile": "+91 (81234) 50679"})
        self.assertEqual(support, corroborating_identity(f"Name: {name}\nPhone: 81234-50679"))
        self.assertIsNone(corroborating_identity({"Patient Name": name, "UHID": "TST-999",
                                                  "MRN": "TST-888", "Phone": "81234-50679"}))
        anchor = ("hospital-a", {("local-a", "qualified-a", "", support)})
        fragment = ("unassigned", {("fragment", "", "", support)})
        self.assertIn(("unassigned", "fragment", "local-a"), list(identity_groups([anchor, fragment])))
        conflict = ("hospital-b", {("local-b", "qualified-b", "", support)})
        self.assertNotIn(("unassigned", "fragment", "local-a"),
                         list(identity_groups([anchor, conflict, fragment])))

    def test_distinct_groups_with_colliding_pseudonyms(self):
        groups = [("first", "local-a", "group-a"), ("second", "local-b", "group-b")]
        with patch("main.identity_groups", return_value=iter(reversed(groups))), patch(
            "main.pseudonym", side_effect=lambda _group, attempt=0: f"PSN-{attempt:06d}",
        ):
            decisions = resolve([])
        self.assertEqual(decisions["first"]["local-a"][0], "PSN-000000")
        self.assertEqual(decisions["second"]["local-b"][0], "PSN-000001")

    def test_offline_release_on_unseen_records(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            workspace = Path(directory)
            inputs = workspace / "input files"
            inputs.mkdir()
            guard = workspace / "network guard"
            guard.mkdir()
            (guard / "sitecustomize.py").write_text(
                "import sys\n"
                "def reject_network(event, arguments):\n"
                "    if event.startswith('socket.'):\n"
                "        raise RuntimeError('network blocked in Track 3 test')\n"
                "sys.addaudithook(reject_network)\n",
                encoding="utf-8",
            )
            (inputs / "arogya_registration.tsv").write_text(
                "ＵＨＩＤ\tＰａｔｉｅｎｔ Ｎａｍｅ\tAdmissionDate\tDischargeDate\tDose\n"
                "QXR-4193\tSamar Vyomkul\t01/25/2026\t02/03/2026\tRamipril 5 mg\n",
                encoding="utf-16",
            )
            (inputs / "sanjeevani_notes.txt").write_text(
                "Encounter ID: ENC-818\n2026-02-10\nSpO2 98%\n", encoding="utf-8",
            )
            (inputs / "sanjeevani_discharge.txt").write_text(
                "Encounter ID: ENC-818\n2026-02-14\nGlucose 93 mg/dL\n", encoding="utf-8",
            )
            (inputs / "records.json").write_text('{"value":NaN}', encoding="utf-8")
            (inputs / "visit.json").write_text('{"result":1e999}', encoding="utf-8")
            (inputs / "report.json").write_text('{"result":1,"result":2}', encoding="utf-8")
            (inputs / "results.json").write_text(
                '{"patient-contact@example.invalid":[{"value":"5 mg"}]}', encoding="utf-8",
            )
            before = snapshot(inputs)
            same_secret = []
            linked_values = []

            for run, secret in enumerate(("synthetic-a", "synthetic-a", "synthetic-b")):
                out = workspace / f"release {run}"
                process = subprocess.run(
                    [sys.executable, str(ROOT / "main.py"), "--input", str(inputs), "--output", str(out)],
                    cwd=ROOT, env={**os.environ, "RAKSHA_SECRET": secret, "PYTHONPATH": str(guard)},
                    capture_output=True, text=True, timeout=120,
                )
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(process.stderr, "")
                self.assertNotIn(secret, process.stdout)
                files = json.loads((out / "report.json").read_bytes())["files"]
                reasons = sorted(item["reason"] for item in files if item["status"] == "quarantined")
                self.assertEqual(reasons, ["duplicate_json_field", "invalid_json_number",
                                           "invalid_json_number", "sensitive_record_locator"])
                with (out / "sanitized/arogya_registration.tsv").open(encoding="utf-8", newline="") as stream:
                    header, row = csv.reader(stream, delimiter="\t")
                self.assertEqual(len(header), len(row))
                self.assertEqual(row[1], "[NAME]")
                self.assertEqual(row[4], "Ramipril 5 mg")
                admission, discharge = (datetime.strptime(value, "%m/%d/%Y") for value in row[2:4])
                self.assertEqual((discharge - admission).days, 9)
                linked_values.append((row[0], admission))
                published = (out / "records.jsonl").read_text(encoding="utf-8")
                self.assertNotIn("patient-contact@example.invalid", published)
                records = [json.loads(line) for line in published.splitlines()]
                self.assertEqual(sum(record["patient"] is None for record in records), 2)
                texts = [(out / record["file"]).read_text(encoding="utf-8")
                         for record in records if record["patient"] is None]
                self.assertTrue(all("ENC-818" not in text for text in texts))
                dates = sorted(datetime.fromisoformat(text.splitlines()[1]) for text in texts)
                self.assertEqual((dates[1] - dates[0]).days, 4)
                if run < 2:
                    same_secret.append((snapshot(out / "sanitized"), published))

            self.assertEqual(before, snapshot(inputs))
            self.assertEqual(same_secret[0], same_secret[1])
            self.assertNotEqual(linked_values[0][0], linked_values[-1][0])
            self.assertNotEqual(linked_values[0][1], linked_values[-1][1])


if __name__ == "__main__":
    unittest.main()
