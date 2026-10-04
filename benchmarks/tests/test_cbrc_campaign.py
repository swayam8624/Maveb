from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/cbrc_campaign.py"
spec = importlib.util.spec_from_file_location("cbrc_campaign", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def row(*, fallback=False, coupling="low", actual=0.02, bound=0.03):
    return {
        "scene_id": "scene",
        "revision_id": "r",
        "coupling_regime": coupling,
        "fallback_full": fallback,
        "qois": {
            "rgb_linf": {
                "epsilon": 0.04,
                "certified_bound": 0.0 if fallback else bound,
                "measured_full_reference_error": 0.0 if fallback else actual,
            }
        },
    }


class CBRCCampaignTests(unittest.TestCase):
    def test_complete_campaign_gate_passes(self):
        rows = [
            row(),
            row(),
            row(),
            row(coupling="high"),
            row(fallback=True, coupling="adversarial"),
        ]
        result = mod.gate_rows(
            rows,
            {
                "minimum_revisions": 5,
                "minimum_scenes": 1,
                "require_local_success": True,
                "require_full_fallback": True,
                "require_high_coupling": True,
            },
        )
        self.assertTrue(result["pass"])

    def test_missing_fallback_fails(self):
        result = mod.gate_rows(
            [row() for _ in range(5)],
            {
                "minimum_revisions": 5,
                "minimum_scenes": 1,
                "require_local_success": True,
                "require_full_fallback": True,
                "require_high_coupling": False,
            },
        )
        self.assertFalse(result["pass"])
        self.assertFalse(result["gates"]["hasAutomaticFullFallback"])

    def test_capture_case_requires_three_value_target(self):
        case = {
            "id": "bad",
            "epsilon": 0.1,
            "revision": {
                "archive": "world",
                "entity": 1,
                "target": [1, 2],
                "timestamp": 2,
            },
        }
        with self.assertRaisesRegex(ValueError, "target"):
            mod.capture_case(
                case,
                revision_tool=Path("tool"),
                case_dir=Path("out"),
            )

    def test_native_python_planner_parity(self):
        manifest = {
            "production_certificate": {
                "outputConePlanner": {
                    "plannerWork": 25.0,
                    "passes": True,
                    "fullRepair": False,
                }
            }
        }
        baseline = {
            "baselines": {
                "CBRC": {
                    "work": 25.0,
                    "passes": True,
                    "usedFullRebuild": False,
                }
            }
        }
        result = mod.verify_native_python_planner_parity(manifest, baseline)
        self.assertTrue(result["pass"])
        self.assertEqual(result["workDelta"], 0.0)

    def test_native_python_planner_parity_detects_fallback_mismatch(self):
        manifest = {
            "production_certificate": {
                "outputConePlanner": {
                    "plannerWork": 100.0,
                    "passes": True,
                    "fullRepair": True,
                }
            }
        }
        baseline = {
            "baselines": {
                "CBRC": {
                    "work": 100.0,
                    "passes": True,
                    "usedFullRebuild": False,
                }
            }
        }
        result = mod.verify_native_python_planner_parity(manifest, baseline)
        self.assertFalse(result["pass"])
        self.assertFalse(result["fallbackMatch"])

    def test_restore_case_input_reverts_mutated_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.aetherworld"
            destination = root / "case" / "input.aetherworld"
            source.write_text("pristine-world\n")
            Path(str(source) + ".gaussians.r1.bin").write_bytes(b"gaussian-r1")
            Path(str(source) + ".ownership.r1.bin").write_bytes(b"ownership-r1")

            destination.parent.mkdir(parents=True)
            destination.write_text("mutated-world\n")
            Path(str(destination) + ".gaussians.r1.bin").write_bytes(b"old-r1")
            Path(str(destination) + ".ownership.r1.bin").write_bytes(b"old-own-r1")
            Path(str(destination) + ".gaussians.r2.bin").write_bytes(b"stale-r2")
            Path(str(destination) + ".ownership.r2.bin").write_bytes(b"stale-own-r2")

            mod.restore_case_input(
                {
                    "revision": {
                        "archive": str(destination),
                    }
                },
                {
                    "source_archive": str(source),
                    "source_revision": 1,
                },
            )

            self.assertEqual(destination.read_text(), "pristine-world\n")
            self.assertEqual(
                Path(str(destination) + ".gaussians.r1.bin").read_bytes(),
                b"gaussian-r1",
            )
            self.assertEqual(
                Path(str(destination) + ".ownership.r1.bin").read_bytes(),
                b"ownership-r1",
            )
            self.assertFalse(Path(str(destination) + ".gaussians.r2.bin").exists())
            self.assertFalse(Path(str(destination) + ".ownership.r2.bin").exists())

    def test_safe_resume_invalidation_clears_only_execution_root(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            frozen = base / "frozen"
            frozen.mkdir()
            frozen_marker = frozen / "reviewer-stress-campaign.json"
            frozen_marker.write_text('{"cases":[{"id":"frozen"}]}\n')

            root = base / "campaign"
            root.mkdir()
            state = root / "CAMPAIGN_RESUME_STATE.json"
            state.write_text(
                json.dumps({"executionSignature": "old-signature"}) + "\n"
            )
            (root / "stale-result.txt").write_text("stale\n")

            new_state, invalidated = mod.ensure_resume_signature(
                root=root,
                state_path=state,
                signature="new-signature",
                resume=True,
                invalidate_stale_resume=True,
                worker_case=None,
            )

            self.assertTrue(invalidated)
            self.assertEqual(new_state, root / "CAMPAIGN_RESUME_STATE.json")
            self.assertTrue(root.is_dir())
            self.assertFalse((root / "stale-result.txt").exists())
            self.assertTrue(frozen_marker.is_file())

    def test_resume_mismatch_still_fails_without_explicit_invalidation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "campaign"
            root.mkdir()
            state = root / "CAMPAIGN_RESUME_STATE.json"
            state.write_text(
                json.dumps({"executionSignature": "old-signature"}) + "\n"
            )

            with self.assertRaisesRegex(SystemExit, "does not match"):
                mod.ensure_resume_signature(
                    root=root,
                    state_path=state,
                    signature="new-signature",
                    resume=True,
                    invalidate_stale_resume=False,
                    worker_case=None,
                )

    def test_worker_never_invalidates_shared_campaign_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "campaign"
            root.mkdir()
            state = root / ".worker-state-case-1.json"
            state.write_text(
                json.dumps({"executionSignature": "old-signature"}) + "\n"
            )
            marker = root / "keep.txt"
            marker.write_text("keep\n")

            with self.assertRaisesRegex(SystemExit, "does not match"):
                mod.ensure_resume_signature(
                    root=root,
                    state_path=state,
                    signature="new-signature",
                    resume=True,
                    invalidate_stale_resume=True,
                    worker_case="case-1",
                )
            self.assertTrue(marker.is_file())

    def test_execution_signature_changes_with_oracle_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = root / "campaign.json"
            oracle = root / "oracle"
            revision = root / "revision"
            freeze = root / "freeze.json"
            campaign.write_text('{"cases":[{"id":"x"}]}\n')
            oracle.write_bytes(b"oracle")
            revision.write_bytes(b"revision")
            freeze.write_text("{}\n")

            with mock.patch.dict("os.environ", {"MAVEB_ORACLE_BACKEND": "cpu"}):
                cpu = mod.execution_signature(
                    campaign_path=campaign,
                    oracle=oracle,
                    revision_tool=revision,
                    git_sha="abc",
                    freeze_provenance=freeze,
                )
            with mock.patch.dict("os.environ", {"MAVEB_ORACLE_BACKEND": "metal"}):
                metal = mod.execution_signature(
                    campaign_path=campaign,
                    oracle=oracle,
                    revision_tool=revision,
                    git_sha="abc",
                    freeze_provenance=freeze,
                )

            self.assertNotEqual(cpu, metal)

    def test_reusable_case_can_adopt_matching_pre_marker_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory)
            (case_dir / "replay-manifest.json").write_text(
                json.dumps({"git_sha": "abc123"}) + "\n"
            )
            (case_dir / "revision-row.json").write_text(
                json.dumps({"case_id": "case-1"}) + "\n"
            )
            (case_dir / "baselines.json").write_text(
                json.dumps({"case_id": "case-1"}) + "\n"
            )

            adopted = mod.reusable_case(
                case_dir,
                case_id="case-1",
                signature="signature",
                git_sha="abc123",
                adopt_existing=True,
            )
            self.assertIsNotNone(adopted)
            self.assertTrue(adopted["adoptedExisting"])

            rejected = mod.reusable_case(
                case_dir,
                case_id="case-1",
                signature="signature",
                git_sha="different",
                adopt_existing=True,
            )
            self.assertIsNone(rejected)

    def test_adoption_timing_payload_can_preserve_measured_values(self):
        measured = {
            "case_id": "case-1",
            "capture_wall_ms": 11.0,
            "evidence_wall_ms": 22.0,
            "baseline_wall_ms": 33.0,
            "case_wall_ms": 66.0,
        }
        adopted = dict(measured)
        adopted["resumed"] = True
        adopted["adoptedExisting"] = True
        self.assertEqual(adopted["case_wall_ms"], 66.0)
        self.assertEqual(adopted["evidence_wall_ms"], 22.0)

    def test_baseline_summary_aggregates_method_statistics(self):
        records = [
            {
                "baselines": {
                    "CBRC": {
                        "passes": True,
                        "usedFullRebuild": False,
                        "workRatioFull": 0.25,
                    }
                },
                "ablations": {
                    "ABLATE_NO_FALLBACK": {
                        "passes": False,
                        "usedFullRebuild": False,
                        "workRatioFull": 0.1,
                    }
                },
            },
            {
                "baselines": {
                    "CBRC": {
                        "passes": True,
                        "usedFullRebuild": True,
                        "workRatioFull": 1.0,
                    }
                },
                "ablations": {
                    "ABLATE_NO_FALLBACK": {
                        "passes": True,
                        "usedFullRebuild": False,
                        "workRatioFull": 0.2,
                    }
                },
            },
        ]
        summary = mod.baseline_summary(records)
        self.assertEqual(summary["baselines"]["CBRC"]["passRate"], 1.0)
        self.assertEqual(
            summary["baselines"]["CBRC"]["fullRebuildRate"], 0.5
        )
        self.assertEqual(
            summary["baselines"]["CBRC"]["medianWorkRatioFull"], 0.625
        )
        self.assertEqual(
            summary["ablations"]["ABLATE_NO_FALLBACK"]["passRate"], 0.5
        )

    def test_certificate_violation_fails(self):
        rows = [row() for _ in range(4)] + [row(actual=0.04, bound=0.03)]
        result = mod.gate_rows(
            rows,
            {
                "minimum_revisions": 5,
                "minimum_scenes": 1,
                "require_local_success": True,
                "require_full_fallback": False,
                "require_high_coupling": False,
            },
        )
        self.assertFalse(result["pass"])
        self.assertFalse(result["gates"]["noCertificateViolations"])


if __name__ == "__main__":
    unittest.main()
