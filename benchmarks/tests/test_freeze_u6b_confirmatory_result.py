#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "freeze_u6b_confirmatory_result.py"
spec = importlib.util.spec_from_file_location("freeze_u6b_confirmatory_result", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class U6bConfirmatoryResultFreezeTests(unittest.TestCase):
    @staticmethod
    def protocol() -> dict:
        return {
            "claimType": "prospective confirmatory test on untouched validation rooms",
            "evaluation": {
                "decisionRule": "All confirmatory gate clauses must pass.",
                "pairedSceneBootstrapReplicates": 2000,
                "pairedSceneBootstrapSeed": 42,
            },
            "claimPolicy": {
                "ifPassed": "passed-policy",
                "ifFailed": "failed-policy",
            },
        }

    @staticmethod
    def preparation() -> dict:
        scenes = []
        for scene_index, scene in enumerate(module.EXPECTED_SCENES):
            scenes.append(
                {
                    "scene": scene,
                    "targetManifestSha256": f"target-{scene_index}",
                    "methods": {
                        method: {
                            "gaussianSha256": f"gaussian-{scene_index}-{method}",
                            "primitiveCount": 100 + scene_index,
                        }
                        for method in module.METHODS
                    },
                }
            )
        return {"scenes": scenes}

    @staticmethod
    def authorization(preparation: dict) -> dict:
        scenes = []
        for scene_index, scene in enumerate(module.EXPECTED_SCENES):
            prep_scene = preparation["scenes"][scene_index]
            scenes.append(
                {
                    "scene": scene,
                    "targetManifestSha256": prep_scene["targetManifestSha256"],
                    "methods": {
                        method: {
                            "gaussianSha256": prep_scene["methods"][method]["gaussianSha256"],
                            "primitiveCount": prep_scene["methods"][method]["primitiveCount"],
                        }
                        for method in module.METHODS
                    },
                    "targets": [
                        {
                            "targetIndex": target_index,
                            "timestampNanoseconds": 1_000_000 * scene_index + target_index,
                            "faroDepthSha256": f"faro-{scene_index}-{target_index}",
                        }
                        for target_index in range(module.TARGETS_PER_SCENE)
                    ],
                }
            )
        return {"scenes": scenes}

    @staticmethod
    def result(preparation: dict, authorization: dict) -> dict:
        scenes = {}
        for scene_index, scene in enumerate(module.EXPECTED_SCENES):
            prep_scene = preparation["scenes"][scene_index]
            auth_scene = authorization["scenes"][scene_index]
            scenes[scene] = {
                "targetManifestSha256": prep_scene["targetManifestSha256"],
                "methods": {},
            }
            for method in module.METHODS:
                scenes[scene]["methods"][method] = {
                    "gaussianSha256": prep_scene["methods"][method]["gaussianSha256"],
                    "primitiveCount": prep_scene["methods"][method]["primitiveCount"],
                    "targets": [
                        {
                            "targetIndex": target["targetIndex"],
                            "timestampNanoseconds": target["timestampNanoseconds"],
                            "renderSha256": "0" * 64,
                        }
                        for target in auth_scene["targets"]
                    ],
                    "sceneSummary": {},
                }
        return {
            "study": module.STUDY_ID,
            "stage": "U6b-confirmatory-heldout-faro-depth",
            "status": module.PASSED_STATUS,
            "claimType": "prospective confirmatory test on untouched validation rooms",
            "protocolSha256": module.PROTOCOL_SHA256,
            "preparationSha256": "prep",
            "authorizationSha256": "auth",
            "renderToolSha256": module.RENDER_TOOL_SHA256,
            "renderCount": module.TOTAL_RENDERS,
            "methodOrder": list(module.METHODS),
            "scenes": scenes,
            "confirmatoryGate": {
                "candidateMinusBaseline": {"replicates": 2000, "seed": 42},
                "candidateMinusShuffled": {"replicates": 2000, "seed": 42},
                "checks": {
                    "candidateVsBaselineMedianEffectFloor": True,
                    "candidateVsBaselineWins": True,
                    "candidateVsBaselinePaired95LowerAboveZero": True,
                    "candidateVsShuffledMedianEffectFloor": True,
                    "candidateVsShuffledWins": True,
                    "candidateVsShuffledPaired95LowerAboveZero": True,
                    "coverageMedianRatio": True,
                    "coveragePerSceneMinimumRatio": True,
                    "overlapMeanAbsoluteErrorGuard": True,
                },
                "allGateClausesPassed": True,
            },
            "decisionRule": "All confirmatory gate clauses must pass.",
            "claimPolicyApplied": "passed-policy",
        }

    def test_frozen_layout_is_exactly_120_renders(self) -> None:
        self.assertEqual(len(module.EXPECTED_SCENES), 5)
        self.assertEqual(len(module.METHODS), 3)
        self.assertEqual(module.TARGETS_PER_SCENE, 8)
        self.assertEqual(module.TOTAL_RENDERS, 120)

    def test_result_metadata_binds_recorded_decision_without_recomputing(self) -> None:
        protocol = self.protocol()
        preparation = self.preparation()
        authorization = self.authorization(preparation)
        result = self.result(preparation, authorization)
        passed = module.validate_result_metadata(
            result,
            protocol=protocol,
            preparation=preparation,
            authorization=authorization,
            preparation_sha="prep",
            authorization_sha="auth",
            render_tool_sha=module.RENDER_TOOL_SHA256,
        )
        self.assertTrue(passed)

    def test_result_rejects_status_gate_disagreement(self) -> None:
        protocol = self.protocol()
        preparation = self.preparation()
        authorization = self.authorization(preparation)
        result = self.result(preparation, authorization)
        result["status"] = module.FAILED_STATUS
        with self.assertRaisesRegex(ValueError, "status disagrees"):
            module.validate_result_metadata(
                result,
                protocol=protocol,
                preparation=preparation,
                authorization=authorization,
                preparation_sha="prep",
                authorization_sha="auth",
                render_tool_sha=module.RENDER_TOOL_SHA256,
            )

    def test_result_rejects_all_gate_flag_disagreement(self) -> None:
        protocol = self.protocol()
        preparation = self.preparation()
        authorization = self.authorization(preparation)
        result = self.result(preparation, authorization)
        result["confirmatoryGate"]["allGateClausesPassed"] = False
        with self.assertRaisesRegex(ValueError, "all-gate decision disagrees"):
            module.validate_result_metadata(
                result,
                protocol=protocol,
                preparation=preparation,
                authorization=authorization,
                preparation_sha="prep",
                authorization_sha="auth",
                render_tool_sha=module.RENDER_TOOL_SHA256,
            )

    def build_render_tree(self, root: Path) -> dict:
        preparation = self.preparation()
        authorization = self.authorization(preparation)
        result = self.result(preparation, authorization)
        for scene in module.EXPECTED_SCENES:
            for method in module.METHODS:
                for target in result["scenes"][scene]["methods"][method]["targets"]:
                    target_index = int(target["targetIndex"])
                    path = root / "scenes" / scene / "renders" / method / f"{target_index:02d}.f32"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(f"{scene}|{method}|{target_index}".encode())
                    target["renderSha256"] = module.sha256_file(path)
        return result

    def test_render_hash_verifier_accepts_exact_frozen_file_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.build_render_tree(root)
            manifest = module.verify_render_hashes(result, root)
            self.assertEqual(len(manifest), module.TOTAL_RENDERS)
            self.assertEqual(
                [record["targetIndex"] for record in manifest[:8]],
                list(range(module.TARGETS_PER_SCENE)),
            )

    def test_render_hash_verifier_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.build_render_tree(root)
            path = (
                root
                / "scenes"
                / module.EXPECTED_SCENES[0]
                / "renders"
                / module.METHODS[0]
                / "00.f32"
            )
            path.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "render SHA mismatch"):
                module.verify_render_hashes(result, root)

    def test_render_hash_verifier_rejects_extra_render(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.build_render_tree(root)
            extra = root / "scenes" / "extra-scene" / "renders" / "extra-method" / "00.f32"
            extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_bytes(b"extra")
            with self.assertRaisesRegex(ValueError, "render file set differs"):
                module.verify_render_hashes(result, root)


if __name__ == "__main__":
    unittest.main()
