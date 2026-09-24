from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "research/analysis/cbrc_cross_dataset_statistics.py"


class CrossDatasetStatisticsGateTests(unittest.TestCase):
    def write_rows(self, path: Path, *, violation: bool = False) -> None:
        rows = []
        for index, dataset in enumerate(("d1", "d2", "d3")):
            qoi = {
                "measured_full_reference_error": 0.2 if violation and index == 0 else 0.0,
                "certified_bound": 0.1 if violation and index == 0 else 0.0,
                "epsilon": 0.1 if violation and index == 0 else 0.0,
            }
            rows.append(
                {
                    "dataset_id": dataset,
                    "representation": "test",
                    "edit_family": "translation",
                    "coupling_regime": "low",
                    "source_scene_id": f"scene-{index}",
                    "fallback_full": False,
                    "planner_work": 4.0,
                    "full_work": 10.0,
                    "qois": {"render": qoi},
                }
            )
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )

    def run_stats(self, *, violation: bool = False) -> tuple[subprocess.CompletedProcess[str], dict]:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        rows = root / "rows.jsonl"
        out = root / "stats"
        self.write_rows(rows, violation=violation)
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--rows",
                str(rows),
                "--output-dir",
                str(out),
                "--bootstrap-iterations",
                "100",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        payload = json.loads((out / "CROSS_DATASET_STATISTICS.json").read_text())
        return completed, payload

    def test_all_local_cross_dataset_campaign_can_pass(self):
        completed, payload = self.run_stats()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        gates = payload["crossDatasetGates"]
        observations = payload["crossDatasetObservations"]
        self.assertTrue(gates["pass"])
        self.assertFalse(observations["bothLocalAndFallbackObserved"])
        self.assertEqual(
            observations["fallbackObservationPolicy"],
            "observed-outcome-not-required",
        )

    def test_certificate_violation_still_fails_gate(self):
        completed, payload = self.run_stats(violation=True)
        self.assertEqual(completed.returncode, 5)
        self.assertFalse(payload["crossDatasetGates"]["pass"])
        self.assertFalse(
            payload["crossDatasetGates"]["zeroObservedCertificateViolations"]
        )


if __name__ == "__main__":
    unittest.main()
