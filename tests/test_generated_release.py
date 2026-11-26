"""Exercise the offline release with a larger, independent synthetic cohort."""

import json
import hashlib
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GeneratedReleaseTest(unittest.TestCase):
    def test_independent_cohort_with_input_variation(self):
        generator = random.Random(1138)
        syllables = ("al", "bev", "cor", "dur", "eth", "fin", "gur", "har", "is", "jor")
        size = 240
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            source, out = root / "input", root / "output"
            source.mkdir()
            for index in range(size):
                name = f"{''.join(generator.choices(syllables, k=3)).title()} Loptan"
                phone = f"84{12673501 + index:08d}"
                hospital = ("arogya", "sanjeevani", "jeevanjyoti")[index % 3]
                name_label = ("PatientName", "Ｐａｔｉｅｎｔ Ｎａｍｅ", "Patient's Name")[index % 3]
                record = {"MRN": f"FCT-{index:04d}", name_label: name, "Phone": phone,
                          "age": 25 + index % 40, "District": f"District {index % 9}",
                          "State": "Synthetic Province", "dose": "Metformin 500 mg"}
                (source / f"{hospital}_record_{index:04d}.json").write_text(
                    json.dumps(record, ensure_ascii=False), encoding="utf-8",
                )
                fragment = f"Patient Name: {name}\nPhone: +91 {phone[:5]}-{phone[5:]}\nSpO2 98%\n"
                (source / f"notes_{index:04d}.txt").write_text(
                    fragment, encoding=("utf-8", "utf-8-sig", "utf-16")[index % 3],
                )
            run = subprocess.run(
                [sys.executable, "main.py", "--input", str(source), "--output", str(out)],
                cwd=ROOT, env={**os.environ, "RAKSHA_SECRET": "generated-cohort-secret"},
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            report = json.loads((out / "report.json").read_bytes())
            self.assertEqual(report["counts"]["files_total"], 2 * size)
            self.assertEqual(report["counts"]["files_quarantined"], 0)
            source_families = {hashlib.sha256(path.read_bytes()).hexdigest(): path.stem.rsplit("_", 1)[1]
                               for path in source.iterdir()}
            exported_families = {item["output"]: source_families[item["input_sha256"]]
                                 for item in report["files"]}
            groups = {}
            for line in (out / "records.jsonl").read_text().splitlines():
                record = json.loads(line)
                output = (out / record["file"]).read_text(encoding="utf-8")
                patient = record["patient"]
                self.assertTrue(patient and patient in output)
                self.assertNotIn("Loptan", output)
                self.assertNotIn("8412673", output)
                self.assertTrue("Metformin 500 mg" in output or "SpO2 98%" in output)
                family = exported_families[record["file"]]
                groups.setdefault(family, set()).add(patient)
            self.assertEqual(len(groups), size)
            self.assertTrue(all(len(group) == 1 for group in groups.values()))
            self.assertEqual(len({next(iter(group)) for group in groups.values()}), size)


if __name__ == "__main__":
    unittest.main()
