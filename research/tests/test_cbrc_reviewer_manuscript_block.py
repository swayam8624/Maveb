from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "research/analysis/cbrc_reviewer_manuscript_block.py"

spec = importlib.util.spec_from_file_location("reviewer_manuscript_block", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


class ReviewerManuscriptBridgeTests(unittest.TestCase):
    def test_open_audit_emits_comments_only(self):
        audit = {
            "recordCount": 256,
            "certifiedNonzeroLocalCases": 0,
            "toleranceCrossoverGroups": 0,
            "readinessGates": {
                "noCertificateViolations": True,
                "hasCertifiedNonzeroLocal": False,
            },
        }
        tex = mod.build_open_tex(audit)
        self.assertIn("reviewerEvidenceReady=false", tex)
        self.assertNotIn("\\subsection{Certified non-zero residual stress test}", tex)

    def test_ready_audit_emits_nonzero_residual_claim(self):
        audit = {
            "recordCount": 256,
            "localCases": 180,
            "fullFallbackCases": 76,
            "certifiedPartialRepairCases": 256,
            "certifiedNonzeroLocalCases": 42,
            "nearBoundaryLocalCases": 11,
            "toleranceCrossoverGroups": 7,
            "certificateViolationCount": 0,
            "repairCertificateViolationCount": 0,
            "nonzeroLocalDatasets": ["3rscan", "bonn-rgbd-dynamic"],
        }
        tex = mod.build_ready_tex(
            audit,
            have_real_scene=False,
            have_crossover=False,
        )
        self.assertIn("\\subsection{Certified non-zero residual stress test}", tex)
        self.assertIn("42 certified \\LOCAL{}", tex)
        self.assertIn("0 core-certificate violations", tex)
        self.assertIn("0 omitted-subset certificate violations", tex)
        self.assertNotIn("\\includegraphics", tex)

    def test_figure_copy_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            destination = root / "nested/destination.png"
            source.write_bytes(b"fixture")
            self.assertTrue(mod.copy_if_present(source, destination))
            self.assertEqual(destination.read_bytes(), b"fixture")


if __name__ == "__main__":
    unittest.main()
