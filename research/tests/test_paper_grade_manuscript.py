from __future__ import annotations

import importlib.util
import re
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANUSCRIPT = ROOT / "researchpaper/main.tex"


BUILDER_PATH = ROOT / "researchpaper/build_manuscript.py"
BUILDER_SPEC = importlib.util.spec_from_file_location("build_manuscript", BUILDER_PATH)
assert BUILDER_SPEC is not None and BUILDER_SPEC.loader is not None
BUILDER = importlib.util.module_from_spec(BUILDER_SPEC)
BUILDER_SPEC.loader.exec_module(BUILDER)


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

    def test_word_export_resolves_reviewer_state_and_inlines_results(self):
        source = (
            r"\IfFileExists{generated/reviewer_v2_state.tex}{%"
            r"\input{generated/reviewer_v2_state.tex}%"
            r"}{%\newif\ifreviewervtwoready\reviewervtworeadyfalse}"
            "\n"
            r"before \ifreviewervtwoready READY \else OPEN \fi after"
            "\n"
            r"\IfFileExists{generated/reviewer_v2_results.tex}"
            r"{\input{generated/reviewer_v2_results.tex}}{}"
        )
        original_root = BUILDER.ROOT
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "generated"
            generated.mkdir()
            (generated / "reviewer_v2_state.tex").write_text(
                "\\newif\\ifreviewervtwoready\n"
                "\\reviewervtworeadytrue\n",
                encoding="utf-8",
            )
            (generated / "reviewer_v2_results.tex").write_text(
                "\\subsection{Certified non-zero residual stress test}\n"
                "\\begin{figure*}[t]x\\end{figure*}\n",
                encoding="utf-8",
            )
            BUILDER.ROOT = root
            try:
                expanded = BUILDER.expand_reviewer_v2_for_word(source)
            finally:
                BUILDER.ROOT = original_root

        self.assertIn("READY", expanded)
        self.assertNotIn(" OPEN ", expanded)
        self.assertIn("Certified non-zero residual stress test", expanded)
        self.assertNotIn("reviewer_v2_results.tex", expanded)
        self.assertNotIn(r"\ifreviewervtwoready", expanded)

    def test_defensive_not_cadence_is_reduced(self):
        text = MANUSCRIPT.read_text(encoding="utf-8")
        standalone_not = len(re.findall(r"\bnot\b", text, flags=re.IGNORECASE))
        self.assertLessEqual(standalone_not, 40)


if __name__ == "__main__":
    unittest.main()
