from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANUSCRIPT = ROOT / "researchpaper/main.tex"


class PaperGradeManuscriptTests(unittest.TestCase):
    def test_current_headline_uses_paper_grade_campaign(self):
        text = MANUSCRIPT.read_text(encoding="utf-8")
        self.assertIn("1,275 revisions over 85 scenes", text)
        self.assertIn("935 certified \\LOCAL{} repairs", text)
        self.assertIn("340 \\FULL{} fallbacks", text)
        self.assertIn("0.4744733", text)
        self.assertIn("translation, rotation, uniform-scale, and opacity", text)

    def test_legacy_60_case_headline_is_gone(self):
        text = MANUSCRIPT.read_text(encoding="utf-8")
        forbidden = (
            "Across the 60 frozen public revisions",
            "44 certified-local",
            "16 full rebuilds",
            "0.3695301",
            "2.706\\times",
            "four of five revisions stay local",
        )
        for phrase in forbidden:
            self.assertNotIn(phrase, text)

    def test_reviewer_v2_claims_are_fail_closed(self):
        text = MANUSCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            "\\IfFileExists{generated/reviewer_v2_results.tex}",
            text,
        )
        self.assertIn(
            "results remain outside the present claims until that campaign is executed",
            text,
        )

    def test_reviewer_v2_state_controls_all_claim_surfaces(self):
        text = MANUSCRIPT.read_text(encoding="utf-8")
        self.assertIn(r"\IfFileExists{generated/reviewer_v2_state.tex}", text)
        self.assertGreaterEqual(text.count(r"\ifreviewervtwoready"), 5)
        self.assertIn("successful cases are reported as a separate stress result", text)
        self.assertIn("Useful certified approximation with non-zero residual remains", text)

    def test_defensive_not_cadence_is_reduced(self):
        text = MANUSCRIPT.read_text(encoding="utf-8")
        standalone_not = len(re.findall(r"\bnot\b", text, flags=re.IGNORECASE))
        self.assertLessEqual(standalone_not, 40)


if __name__ == "__main__":
    unittest.main()
