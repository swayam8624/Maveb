#!/usr/bin/env python3
"""Verify and freeze the single U6b confirmatory result without recomputing outcomes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_u5a_gaussian_depth import sha256_file


STUDY_ID = "metric-uncertainty-u6b-opacity-visibility-confirmatory-v1"
PROTOCOL_SHA256 = "0c58590d7c71c24797d583bd2681c1fc8994028d9b188b1fbe5fb5a4c4e1b3e3"
RENDER_TOOL_SHA256 = "6b1f511633c259890b0f531ac414773a6a2bcbfcf5ee932585db036cfd4a997d"
EXPECTED_SCENES = [
    "ca1m-42898811",
    "ca1m-45261121",
    "ca1m-47895341",
    "ca1m-47332915",
    "ca1m-47331971",
]
METHODS = (
    "depth-only-fixed-opacity",
    "calibrated-relative-precision-opacity",
    "shuffled-relative-precision-opacity",
)
TARGETS_PER_SCENE = 8
TOTAL_RENDERS = len(EXPECTED_SCENES) * len(METHODS) * TARGETS_PER_SCENE
PASSED_STATUS = "completed-confirmatory-gate-passed"
FAILED_STATUS = "completed-confirmatory-gate-not-passed"


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text())


def validate_protocol(path: Path) -> dict:
    if sha256_file(path) != PROTOCOL_SHA256:
        raise ValueError("U6b freeze protocol SHA mismatch")
    protocol = load_json(path)
    if (
        protocol.get("id") != STUDY_ID
        or protocol.get("status") != "preregistered-before-confirmatory-asset-acquisition"
        or protocol.get("frozen") is not True
    ):
        raise ValueError("U6b freeze requires the frozen confirmatory protocol")
    method_ids = tuple(record["id"] for record in protocol.get("methods", []))
    if method_ids != METHODS:
        raise ValueError("U6b freeze protocol method order changed")
    return protocol


def validate_preparation(path: Path) -> dict:
    preparation = load_json(path)
    if preparation.get("study") != STUDY_ID:
        raise ValueError("U6b freeze preparation study mismatch")
    if preparation.get("status") != "prepared-no-u6b-render-or-metric-outcomes":
        raise ValueError("U6b freeze preparation status mismatch")
    if preparation.get("protocolSha256") != PROTOCOL_SHA256:
        raise ValueError("U6b freeze preparation protocol SHA mismatch")
    if preparation.get("noRenderedDepthProduced") is not True:
        raise ValueError("U6b frozen preparation no-render declaration changed")
    if preparation.get("noU6bMetricsProduced") is not True:
        raise ValueError("U6b frozen preparation no-metric declaration changed")
    if tuple(preparation.get("methods", [])) != METHODS:
        raise ValueError("U6b freeze preparation method order changed")
    scene_names = [record["scene"] for record in preparation.get("scenes", [])]
    if scene_names != EXPECTED_SCENES:
        raise ValueError("U6b freeze preparation scene order changed")
    return preparation


def validate_authorization(
    path: Path,
    *,
    preparation_sha: str,
    render_tool_sha: str,
) -> dict:
    authorization = load_json(path)
    if authorization.get("study") != STUDY_ID:
        raise ValueError("U6b freeze authorization study mismatch")
    if authorization.get("stage") != "U6b-confirmatory-render-authorization":
        raise ValueError("U6b freeze authorization stage mismatch")
    if authorization.get("status") != "authorized-after-frozen-preparation-before-render":
        raise ValueError("U6b freeze authorization status mismatch")
    if authorization.get("protocolSha256") != PROTOCOL_SHA256:
        raise ValueError("U6b freeze authorization protocol SHA mismatch")
    if authorization.get("preparationSha256") != preparation_sha:
        raise ValueError("U6b freeze authorization preparation SHA mismatch")
    if authorization.get("renderToolSha256") != render_tool_sha:
        raise ValueError("U6b freeze authorization renderer SHA mismatch")
    if tuple(authorization.get("methods", [])) != METHODS:
        raise ValueError("U6b freeze authorization method order changed")
    if int(authorization.get("sceneCount", -1)) != len(EXPECTED_SCENES):
        raise ValueError("U6b freeze authorization scene count mismatch")
    if int(authorization.get("targetViewsPerScene", -1)) != TARGETS_PER_SCENE:
        raise ValueError("U6b freeze authorization target count mismatch")
    if int(authorization.get("totalRenderCount", -1)) != TOTAL_RENDERS:
        raise ValueError("U6b freeze authorization render count mismatch")
    if authorization.get("confirmatoryOutcomeObservedBeforeAuthorization") is not False:
        raise ValueError("U6b freeze authorization does not preserve the unopened boundary")
    scene_names = [record["scene"] for record in authorization.get("scenes", [])]
    if scene_names != EXPECTED_SCENES:
        raise ValueError("U6b freeze authorization scene order changed")
    return authorization


def scene_map(records: list[dict]) -> dict[str, dict]:
    return {record["scene"]: record for record in records}


def validate_result_metadata(
    result: dict,
    *,
    protocol: dict,
    preparation: dict,
    authorization: dict,
    preparation_sha: str,
    authorization_sha: str,
    render_tool_sha: str,
) -> bool:
    if result.get("study") != STUDY_ID:
        raise ValueError("U6b result study mismatch")
    if result.get("stage") != "U6b-confirmatory-heldout-faro-depth":
        raise ValueError("U6b result stage mismatch")
    if result.get("protocolSha256") != PROTOCOL_SHA256:
        raise ValueError("U6b result protocol SHA mismatch")
    if result.get("preparationSha256") != preparation_sha:
        raise ValueError("U6b result preparation SHA mismatch")
    if result.get("authorizationSha256") != authorization_sha:
        raise ValueError("U6b result authorization SHA mismatch")
    if result.get("renderToolSha256") != render_tool_sha:
        raise ValueError("U6b result renderer SHA mismatch")
    if int(result.get("renderCount", -1)) != TOTAL_RENDERS:
        raise ValueError("U6b result render count mismatch")
    if tuple(result.get("methodOrder", [])) != METHODS:
        raise ValueError("U6b result method order changed")
    if result.get("claimType") != protocol.get("claimType"):
        raise ValueError("U6b result claim type changed")
    if result.get("decisionRule") != protocol["evaluation"]["decisionRule"]:
        raise ValueError("U6b result decision rule changed")

    gate = result.get("confirmatoryGate")
    if not isinstance(gate, dict):
        raise ValueError("U6b result is missing the confirmatory gate")
    checks = gate.get("checks")
    if not isinstance(checks, dict) or not checks:
        raise ValueError("U6b result gate checks are missing")
    if any(type(value) is not bool for value in checks.values()):
        raise ValueError("U6b result gate checks are not booleans")
    recorded_passed = gate.get("allGateClausesPassed")
    if type(recorded_passed) is not bool:
        raise ValueError("U6b result all-gate decision is not boolean")
    if recorded_passed != all(checks.values()):
        raise ValueError("U6b result all-gate decision disagrees with recorded clauses")

    replicates = int(protocol["evaluation"]["pairedSceneBootstrapReplicates"])
    seed = int(protocol["evaluation"]["pairedSceneBootstrapSeed"])
    for key in ("candidateMinusBaseline", "candidateMinusShuffled"):
        bootstrap = gate.get(key)
        if not isinstance(bootstrap, dict):
            raise ValueError(f"U6b result missing recorded bootstrap: {key}")
        if int(bootstrap.get("replicates", -1)) != replicates:
            raise ValueError(f"U6b result bootstrap replicate count changed: {key}")
        if int(bootstrap.get("seed", -1)) != seed:
            raise ValueError(f"U6b result bootstrap seed changed: {key}")

    expected_status = PASSED_STATUS if recorded_passed else FAILED_STATUS
    if result.get("status") != expected_status:
        raise ValueError("U6b result status disagrees with the recorded gate decision")
    expected_claim = protocol["claimPolicy"]["ifPassed" if recorded_passed else "ifFailed"]
    if result.get("claimPolicyApplied") != expected_claim:
        raise ValueError("U6b result applied the wrong frozen claim policy")

    result_scenes = result.get("scenes")
    if not isinstance(result_scenes, dict) or set(result_scenes) != set(EXPECTED_SCENES):
        raise ValueError("U6b result scene set changed")
    prep_by_scene = scene_map(preparation["scenes"])
    auth_by_scene = scene_map(authorization["scenes"])

    for scene in EXPECTED_SCENES:
        result_scene = result_scenes[scene]
        prep_scene = prep_by_scene[scene]
        auth_scene = auth_by_scene[scene]
        if result_scene.get("targetManifestSha256") != prep_scene["targetManifestSha256"]:
            raise ValueError(f"U6b result target manifest changed for {scene}")
        if result_scene.get("targetManifestSha256") != auth_scene["targetManifestSha256"]:
            raise ValueError(f"U6b result target manifest is not authorization-bound for {scene}")
        methods = result_scene.get("methods")
        if not isinstance(methods, dict) or set(methods) != set(METHODS):
            raise ValueError(f"U6b result method set changed for {scene}")
        auth_targets = {int(target["targetIndex"]): target for target in auth_scene["targets"]}
        if sorted(auth_targets) != list(range(TARGETS_PER_SCENE)):
            raise ValueError(f"U6b authorization target set changed for {scene}")

        for method in METHODS:
            record = methods[method]
            prep_method = prep_scene["methods"][method]
            auth_method = auth_scene["methods"][method]
            if record.get("gaussianSha256") != prep_method["gaussianSha256"]:
                raise ValueError(f"U6b result Gaussian changed for {scene} {method}")
            if record.get("gaussianSha256") != auth_method["gaussianSha256"]:
                raise ValueError(f"U6b result Gaussian is not authorization-bound for {scene} {method}")
            if int(record.get("primitiveCount", -1)) != int(prep_method["primitiveCount"]):
                raise ValueError(f"U6b result primitive count changed for {scene} {method}")
            targets = record.get("targets")
            if not isinstance(targets, list) or len(targets) != TARGETS_PER_SCENE:
                raise ValueError(f"U6b result target count changed for {scene} {method}")
            indices = [int(target["targetIndex"]) for target in targets]
            if indices != list(range(TARGETS_PER_SCENE)):
                raise ValueError(f"U6b result target order changed for {scene} {method}")
            for target in targets:
                target_index = int(target["targetIndex"])
                if int(target["timestampNanoseconds"]) != int(auth_targets[target_index]["timestampNanoseconds"]):
                    raise ValueError(f"U6b result target timestamp changed for {scene} {method} {target_index}")
                render_sha = target.get("renderSha256")
                if not isinstance(render_sha, str) or len(render_sha) != 64:
                    raise ValueError(f"U6b result render SHA is malformed for {scene} {method} {target_index}")

    return recorded_passed


def verify_render_hashes(result: dict, output_root: Path) -> list[dict]:
    expected_paths: set[Path] = set()
    manifest: list[dict] = []
    for scene in EXPECTED_SCENES:
        for method in METHODS:
            targets = result["scenes"][scene]["methods"][method]["targets"]
            for target in targets:
                target_index = int(target["targetIndex"])
                relative_path = Path("scenes") / scene / "renders" / method / f"{target_index:02d}.f32"
                render_path = output_root / relative_path
                if not render_path.is_file():
                    raise FileNotFoundError(render_path)
                expected_sha = target["renderSha256"]
                actual_sha = sha256_file(render_path)
                if actual_sha != expected_sha:
                    raise ValueError(f"U6b render SHA mismatch: {scene} {method} target {target_index}")
                expected_paths.add(render_path.resolve())
                manifest.append(
                    {
                        "scene": scene,
                        "method": method,
                        "targetIndex": target_index,
                        "path": relative_path.as_posix(),
                        "renderSha256": actual_sha,
                    }
                )

    actual_paths = {path.resolve() for path in output_root.glob("scenes/*/renders/*/*.f32")}
    if actual_paths != expected_paths:
        extras = sorted(str(path) for path in actual_paths - expected_paths)
        missing = sorted(str(path) for path in expected_paths - actual_paths)
        raise ValueError(f"U6b render file set differs from frozen result; extras={extras}, missing={missing}")
    if len(manifest) != TOTAL_RENDERS:
        raise ValueError(f"U6b freeze verified {len(manifest)} renders, expected {TOTAL_RENDERS}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--render-tool", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    args = parser.parse_args()

    if args.evidence_output.exists():
        raise ValueError("U6b result freeze already exists; evidence will not be overwritten")
    result_path = args.output_root / "result.json"
    result = load_json(result_path)
    protocol = validate_protocol(args.protocol)
    preparation = validate_preparation(args.preparation)
    if not args.render_tool.is_file():
        raise FileNotFoundError(args.render_tool)
    render_tool_sha = sha256_file(args.render_tool)
    if render_tool_sha != RENDER_TOOL_SHA256:
        raise ValueError("U6b freeze renderer binary SHA mismatch")
    preparation_sha = sha256_file(args.preparation)
    authorization = validate_authorization(
        args.authorization,
        preparation_sha=preparation_sha,
        render_tool_sha=render_tool_sha,
    )
    authorization_sha = sha256_file(args.authorization)
    passed = validate_result_metadata(
        result,
        protocol=protocol,
        preparation=preparation,
        authorization=authorization,
        preparation_sha=preparation_sha,
        authorization_sha=authorization_sha,
        render_tool_sha=render_tool_sha,
    )
    render_manifest = verify_render_hashes(result, args.output_root)

    payload = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "stage": "U6b-confirmatory-result-freeze",
        "status": "frozen-confirmatory-result-gate-passed" if passed else "frozen-confirmatory-result-gate-not-passed",
        "protocolSha256": PROTOCOL_SHA256,
        "preparationSha256": preparation_sha,
        "authorizationSha256": authorization_sha,
        "resultSha256": sha256_file(result_path),
        "renderToolSha256": render_tool_sha,
        "renderCount": TOTAL_RENDERS,
        "sceneCount": len(EXPECTED_SCENES),
        "targetViewsPerScene": TARGETS_PER_SCENE,
        "methodOrder": list(METHODS),
        "resultStatus": result["status"],
        "allGateClausesPassed": passed,
        "recordedGateChecks": result["confirmatoryGate"]["checks"],
        "claimPolicyApplied": result["claimPolicyApplied"],
        "renderHashManifest": render_manifest,
        "verification": {
            "allRecordedRenderHashesVerified": True,
            "renderFileSetExactlyMatchedResult": True,
            "resultBindingsMatchedProtocolPreparationAuthorization": True,
            "gateOrMetricsRecomputed": False,
            "bootstrapRecomputed": False,
        },
        "claimBoundary": "This artifact freezes and verifies the already-produced single U6b confirmatory result. It does not recompute FARO metrics, bootstrap statistics, or the confirmatory gate, and it does not permit tuning after outcome exposure.",
    }
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
