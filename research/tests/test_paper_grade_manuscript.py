from __future__ import annotations

import importlib.util
import re
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
            "73.33",
            "0.47447",
            "66.67",
            "1168",
            "122.3",
        ):
            self.assertNotIn(detailed_metric, abstract)

        self.assertIn("AR maps", abstract)
        self.assertIn("digital twins", abstract)
        self.assertIn("selective maintenance", abstract)
        self.assertIn("1,275 revisions over 85 scenes", abstract)
        self.assertIn("20 independently selected scenes", abstract)

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

    def test_final_residual_evidence_is_integrated_unconditionally(self):
        text = MANUSCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("generated/reviewer_v2", text)
        self.assertNotIn(r"\\ifreviewervtwoready", text)
        self.assertIn("The first residual-sensitive freeze, v4, is a negative result.", text)
        self.assertIn("V5 changes one mechanism.", text)
        self.assertIn("V6 repeats the same mechanism across 20 independent scenes.", text)
        self.assertIn("687 certified non-zero local cases", text)
        self.assertIn("151 tolerance-crossover groups", text)
        self.assertIn("0.477 [0.432, 0.517]", text)

    def test_v6_scene_level_statistics_do_not_treat_cases_as_independent(self):
        text = MANUSCRIPT.read_text(encoding="utf-8")
        self.assertIn("scene as its primary sampling unit", text)
        self.assertIn("dataset stratum", text)
        self.assertIn("3,840 parameter cases are pooled evidence, not 3,840 independent samples", text)
        self.assertIn("five-scene-per-dataset design", text)
        self.assertIn("dataset-stratified scene-bootstrap 95\\% interval", text)

    def test_v4_negative_result_is_preserved(self):
        text = MANUSCRIPT.read_text(encoding="utf-8")
        self.assertIn("256 non-zero-residual cases falls back to \\FULL{}", text)
        self.assertIn("no certified non-zero local cases and no tolerance crossovers", text)
        self.assertIn(
            "all 256 non-zero fallbacks to the post-repair certified bound exceeding epsilon",
            text,
        )

    def test_opacity_delta_certificate_is_defined_and_bounded(self):
        text = MANUSCRIPT.read_text(encoding="utf-8")
        self.assertIn(r"\\label{eq:opacitydelta}", text)
        self.assertIn("+0.002", text)
        self.assertIn("two-sided early-termination discrepancy", text)
        self.assertIn(
            "V5 and v6 use this refinement for opacity residuals",
            text,
        )
        self.assertIn(
            "translation control continues to use Eq.~\\ref{eq:gaussianbound}",
            text,
        )

    def test_defensive_not_cadence_is_reduced(self):
        text = MANUSCRIPT.read_text(encoding="utf-8")
        standalone_not = len(re.findall(r"\bnot\b", text, flags=re.IGNORECASE))
        self.assertLessEqual(standalone_not, 40)


if __name__ == "__main__":
    unittest.main()
