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


ROOT = Path(__file__).resolve().parents[1]


def snapshot(root):
    return {path.relative_to(root): hashlib.sha256(path.read_bytes()).digest()
            for path in root.rglob("*") if path.is_file()}


class TrackThreeTest(unittest.TestCase):
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
                self.assertEqual(reasons, ["duplicate_json_field", "invalid_json_number", "invalid_json_number"])
                with (out / "sanitized/arogya_registration.tsv").open(encoding="utf-8", newline="") as stream:
                    header, row = csv.reader(stream, delimiter="\t")
                self.assertEqual(len(header), len(row))
                self.assertEqual(row[1], "[NAME]")
                self.assertEqual(row[4], "Ramipril 5 mg")
                admission, discharge = (datetime.strptime(value, "%m/%d/%Y") for value in row[2:4])
                self.assertEqual((discharge - admission).days, 9)
                linked_values.append((row[0], admission))
                published = (out / "records.jsonl").read_text(encoding="utf-8")
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
