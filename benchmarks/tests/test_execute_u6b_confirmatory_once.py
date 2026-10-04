#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "execute_u6b_confirmatory_once.py"
spec = importlib.util.spec_from_file_location("execute_u6b_confirmatory_once", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class U6bSealedExecutorTests(unittest.TestCase):
    def test_hidden_runner_stdout_is_not_exposed(self) -> None:
        visible_stdout = io.StringIO()
        visible_stderr = io.StringIO()
        with contextlib.redirect_stdout(visible_stdout), contextlib.redirect_stderr(visible_stderr):
            hidden = module.run_hidden_stdout(
                [
                    sys.executable,
                    "-c",
                    "import sys; print('SECRET-METRIC'); print('render-progress', file=sys.stderr)",
                ],
                label="test runner",
            )
        self.assertIn("SECRET-METRIC", hidden)
        self.assertNotIn("SECRET-METRIC", visible_stdout.getvalue())
        self.assertNotIn("SECRET-METRIC", visible_stderr.getvalue())
        self.assertIn("render-progress", visible_stderr.getvalue())

    def test_failure_message_does_not_leak_hidden_stdout(self) -> None:
        with self.assertRaises(RuntimeError) as captured:
            module.run_hidden_stdout(
                [
                    sys.executable,
                    "-c",
                    "import sys; print('SECRET-METRIC'); sys.exit(7)",
                ],
                label="test runner",
            )
        message = str(captured.exception)
        self.assertIn("exit code 7", message)
        self.assertNotIn("SECRET-METRIC", message)

    def test_exact_result_copy_is_hash_identical_and_non_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "result.json"
            destination = root / "evidence" / "result.json"
            source.write_bytes(b"immutable-result\n")
            result_sha = module.copy_exact_once(source, destination)
            self.assertEqual(result_sha, module.sha256_file(source))
            self.assertEqual(result_sha, module.sha256_file(destination))
            with self.assertRaisesRegex(ValueError, "already exists"):
                module.copy_exact_once(source, destination)

    def write_sealed_fixture(self, root: Path, *, freeze_gate: bool = True) -> tuple[Path, Path, Path]:
        result_path = root / "run" / "result.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result = {
            "study": module.STUDY_ID,
            "stage": module.RESULT_STAGE,
            "status": "completed-confirmatory-gate-passed",
            "renderCount": module.TOTAL_RENDERS,
            "confirmatoryGate": {"allGateClausesPassed": True},
        }
        result_path.write_text(json.dumps(result, sort_keys=True) + "\n")
        result_evidence = root / "evidence" / "result.json"
        result_evidence.parent.mkdir(parents=True, exist_ok=True)
        result_evidence.write_bytes(result_path.read_bytes())
        freeze_path = root / "evidence" / "freeze.json"
        freeze = {
            "study": module.STUDY_ID,
            "stage": module.FREEZE_STAGE,
            "renderCount": module.TOTAL_RENDERS,
            "resultSha256": module.sha256_file(result_path),
            "allGateClausesPassed": freeze_gate,
        }
        freeze_path.write_text(json.dumps(freeze, sort_keys=True) + "\n")
        return result_path, freeze_path, result_evidence

    def test_sealed_outputs_expose_gate_only_after_matching_hash_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result_path, freeze_path, result_evidence = self.write_sealed_fixture(Path(directory))
            summary = module.validate_sealed_outputs(
                result_path=result_path,
                freeze_path=freeze_path,
                result_evidence_path=result_evidence,
            )
            self.assertTrue(summary["allGateClausesPassed"])
            self.assertFalse(summary["intermediateMetricStdoutExposed"])
            self.assertEqual(summary["resultSha256"], summary["resultEvidenceSha256"])

    def test_sealed_outputs_reject_gate_disagreement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result_path, freeze_path, result_evidence = self.write_sealed_fixture(
                Path(directory),
                freeze_gate=False,
            )
            with self.assertRaisesRegex(ValueError, "gate decision mismatch"):
                module.validate_sealed_outputs(
                    result_path=result_path,
                    freeze_path=freeze_path,
                    result_evidence_path=result_evidence,
                )


if __name__ == "__main__":
    unittest.main()
