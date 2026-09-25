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

    def test_abstract_is_impact_led_not_a_results_dump(self):
        text = MANUSCRIPT.read_text(encoding="utf-8")
        match = re.search(
            r"\\begin\{abstract\}(.*?)\\end\{abstract\}",
            text,
            flags=re.S,
        )
        self.assertIsNotNone(match)
        abstract = match.group(1)
        words = re.findall(r"[A-Za-z][A-Za-z-]*", abstract)
        self.assertLessEqual(len(words), 260)

        for detailed_metric in (
            "935",
            "340",
            "73.33",
            "0.47447",
            "95\\% CI",
            "66.67",
        ):
            self.assertNotIn(detailed_metric, abstract)

        self.assertIn("AR maps", abstract)
        self.assertIn("digital twins", abstract)
        self.assertIn("selective maintenance", abstract)

        for repeated_frame in ("frozen", "campaign", "contract", "evidence"):
            self.assertLessEqual(
                abstract.lower().count(repeated_frame),
                1,
                repeated_frame,
            )

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

    def test_final_v6_claims_are_directly_integrated(self):
        text = MANUSCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("generated/reviewer_v2_results.tex", text)
        self.assertNotIn("generated/reviewer_v2_state.tex", text)
        self.assertNotIn(r"\ifreviewervtwoready", text)
        self.assertIn(
            r"\subsection{Confirmatory breadth: useful non-zero residuals}",
            text,
        )
        self.assertIn("All 3,840 frozen confirmatory cases complete", text)
        self.assertIn("Every one of the 20 scenes", text)

    def test_v6_claim_surfaces_are_consistent(self):
        text = MANUSCRIPT.read_text(encoding="utf-8")
        abstract = re.search(
            r"\\begin\{abstract\}(.*?)\\end\{abstract\}",
            text,
            flags=re.S,
        ).group(1)
        self.assertIn("20 independent scenes", abstract)
        self.assertIn("0.477", abstract)
        self.assertIn(r"\label{tab:v6-confirmatory}", text)
        self.assertIn("median scene-level residual effectivity is 1168.21", text)
        self.assertIn("A separately frozen 3,840-case confirmatory study", text)

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

    def test_word_export_defaults_to_open_without_generated_state(self):
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
            BUILDER.ROOT = Path(directory)
            try:
                expanded = BUILDER.expand_reviewer_v2_for_word(source)
            finally:
                BUILDER.ROOT = original_root

        self.assertIn("OPEN", expanded)
        self.assertNotIn(" READY ", expanded)
        self.assertNotIn("reviewer_v2_results.tex", expanded)
        self.assertNotIn(r"\ifreviewervtwoready", expanded)

    def test_actual_manuscript_needs_no_generated_reviewer_state(self):
        source = MANUSCRIPT.read_text(encoding="utf-8")
        original_root = BUILDER.ROOT
        with tempfile.TemporaryDirectory() as directory:
            BUILDER.ROOT = Path(directory)
            try:
                expanded = BUILDER.expand_reviewer_v2_for_word(source)
            finally:
                BUILDER.ROOT = original_root

        self.assertEqual(expanded, source)
        self.assertNotIn(r"\ifreviewervtwoready", expanded)
        self.assertNotIn("generated/reviewer_v2_state.tex", expanded)
        self.assertNotIn("generated/reviewer_v2_results.tex", expanded)
        self.assertIn("All 3,840 frozen confirmatory cases complete", expanded)
        self.assertIn("The remaining limitation is certificate tightness", expanded)

    def test_defensive_not_cadence_is_reduced(self):
        text = MANUSCRIPT.read_text(encoding="utf-8")
        standalone_not = len(re.findall(r"\bnot\b", text, flags=re.IGNORECASE))
        self.assertLessEqual(standalone_not, 40)


if __name__ == "__main__":
    unittest.main()
