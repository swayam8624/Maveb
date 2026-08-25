#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "benchmarks" / "scripts" / "audit_u6c_heterogeneity.py"
PROTOCOL = (
    ROOT
    / "benchmarks"
    / "experiments"
    / "metric-uncertainty-u6c-heterogeneity-audit-v1.json"
)
U6B_RESULT = (
    ROOT
    / "benchmarks"
    / "evidence"
    / "metric-uncertainty-u6b-result-v1.json"
)
EXPECTED_PARENT_SHA = "c361fda74d005c3d76c2d33b83626e5ef4039ee9fbce177d0b42e42fc9a0a823"


class U6cCliBindingTests(unittest.TestCase):
    def test_frozen_protocol_and_sealed_u6b_result_run_end_to_end(self) -> None:
        protocol = json.loads(PROTOCOL.read_text())
        self.assertEqual(protocol["parentResultSha256"], EXPECTED_PARENT_SHA)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "u6c.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--protocol",
                    str(PROTOCOL),
                    "--u6b-result",
                    str(U6B_RESULT),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(output.read_text())
            self.assertEqual(
                payload["status"],
                "completed-post-hoc-descriptive-audit",
            )
            self.assertEqual(payload["parentResultSha256"], EXPECTED_PARENT_SHA)
            self.assertFalse(payload["parentAllGateClausesPassed"])
            self.assertEqual(payload["sceneCount"], 5)


if __name__ == "__main__":
    unittest.main()
