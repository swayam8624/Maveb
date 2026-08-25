#!/usr/bin/env python3
"""Prepare U6b from committed acquisition evidence and deterministic local asset roots.

The original acquisition ledger intentionally contained machine-local absolute paths and was
therefore not committed. The public-safe acquisition freeze preserves the exact asset hashes
and the SHA-256 of that original ledger. This wrapper re-resolves those frozen assets from
explicit local roots, re-verifies every frozen hash, then delegates to the preregistered U6b
preparation implementation without requiring the unavailable path-bearing ledger file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import prepare_u6b_confirmatory_visibility as base


ACQUISITION_FREEZE_STAGE = "U6b-confirmatory-asset-acquisition-freeze"


def validate_acquisition_evidence(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text())
    if payload.get("study") != base.STUDY_ID:
        raise ValueError("U6b acquisition evidence study mismatch")
    if payload.get("stage") != ACQUISITION_FREEZE_STAGE:
        raise ValueError("U6b acquisition evidence stage mismatch")
    if payload.get("status") != "acquired-after-frozen-clean-plan":
        raise ValueError("U6b acquisition evidence status mismatch")
    if payload.get("protocolSha256") != base.PROTOCOL_SHA256:
        raise ValueError("U6b acquisition evidence protocol SHA mismatch")
    if payload.get("acquisitionLedgerSha256") != base.ACQUISITION_SHA256:
        raise ValueError("U6b acquisition evidence no longer binds the frozen runtime ledger")
    videos = [str(item["videoId"]) for item in payload.get("entries", [])]
    if videos != base.EXPECTED_VIDEOS:
        raise ValueError(f"U6b acquisition evidence video order mismatch: {videos}")
    if payload.get("selectedAssetsAbsentAtFrozenPlan") is not True:
        raise ValueError("U6b acquisition evidence clean-plan boundary changed")
    if int(payload.get("partialFilesRemaining", -1)) != 0:
        raise ValueError("U6b acquisition evidence records partial files")
    if int(payload.get("u6bRenderedDepthCountAfterAcquisition", -1)) != 0:
        raise ValueError("U6b acquisition evidence crossed the render-outcome boundary")
    return payload


def _png_count(path: Path) -> int:
    if not path.is_dir():
        return 0
    return len(list(path.glob("*.png")))


def _require_hash(path: Path, expected_sha: str, *, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    actual = base.sha256_file(path)
    if actual != expected_sha:
        raise ValueError(f"{label} SHA mismatch: {actual} != {expected_sha}")


def resolve_runtime_acquisition(
    evidence: dict,
    *,
    ca1m_root: Path,
    arkit_root: Path,
) -> dict:
    ca1m_root = ca1m_root.expanduser().resolve()
    arkit_root = arkit_root.expanduser().resolve()
    resolved_entries: list[dict] = []

    for item in evidence["entries"]:
        video = str(item["videoId"])
        raw_root = arkit_root / "raw" / "Validation" / video
        archive = ca1m_root / f"ca1m-val-{video}.tar"
        confidence_zip = raw_root / "confidence.zip"
        lowres_zip = raw_root / "lowres_depth.zip"
        confidence_dir = raw_root / "confidence"
        lowres_dir = raw_root / "lowres_depth"

        _require_hash(
            archive,
            item["ca1mArchiveSha256"],
            label=f"U6b CA-1M archive {video}",
        )
        _require_hash(
            confidence_zip,
            item["confidenceZipSha256"],
            label=f"U6b confidence ZIP {video}",
        )
        _require_hash(
            lowres_zip,
            item["lowresDepthZipSha256"],
            label=f"U6b lowres-depth ZIP {video}",
        )

        confidence_count = _png_count(confidence_dir)
        lowres_count = _png_count(lowres_dir)
        if confidence_count != int(item["confidencePngCount"]):
            raise ValueError(
                f"U6b confidence PNG count mismatch for {video}: "
                f"{confidence_count} != {item['confidencePngCount']}"
            )
        if lowres_count != int(item["lowresDepthPngCount"]):
            raise ValueError(
                f"U6b lowres-depth PNG count mismatch for {video}: "
                f"{lowres_count} != {item['lowresDepthPngCount']}"
            )
        if archive.stat().st_size != int(item["ca1mArchiveBytes"]):
            raise ValueError(f"U6b CA-1M archive byte count mismatch for {video}")

        resolved_entries.append(
            {
                **item,
                "ca1mArchive": str(archive),
                "confidenceZip": str(confidence_zip),
                "lowresDepthZip": str(lowres_zip),
            }
        )

    return {
        "schemaVersion": 1,
        "study": base.STUDY_ID,
        "stage": "U6b-confirmatory-runtime-asset-resolution",
        "status": "resolved-from-frozen-acquisition-evidence",
        "protocolSha256": base.PROTOCOL_SHA256,
        "acquisitionLedgerSha256": base.ACQUISITION_SHA256,
        "entries": resolved_entries,
    }


def finalize_preparation_provenance(
    preparation_path: Path,
    *,
    acquisition_evidence_path: Path,
    acquisition_evidence: dict,
) -> None:
    if not preparation_path.is_file():
        raise FileNotFoundError(preparation_path)
    payload = json.loads(preparation_path.read_text())
    if payload.get("study") != base.STUDY_ID:
        raise ValueError("U6b generated preparation study mismatch")
    if payload.get("status") != "prepared-no-u6b-render-or-metric-outcomes":
        raise ValueError("U6b generated preparation status mismatch")
    if payload.get("noRenderedDepthProduced") is not True:
        raise ValueError("U6b generated preparation unexpectedly produced render outcomes")
    if payload.get("noU6bMetricsProduced") is not True:
        raise ValueError("U6b generated preparation unexpectedly produced metrics")

    evidence_sha = base.sha256_file(acquisition_evidence_path)
    generated_binding = payload.get("acquisitionLedgerSha256")
    if generated_binding != evidence_sha:
        raise ValueError(
            "U6b preparation delegate did not bind the supplied acquisition evidence as expected"
        )

    # Preserve the original preregistered runtime-ledger binding required by downstream U6b
    # validation while separately recording the public-safe evidence file actually supplied.
    payload["acquisitionLedgerSha256"] = acquisition_evidence["acquisitionLedgerSha256"]
    payload["acquisitionEvidenceSha256"] = evidence_sha
    payload["acquisitionEvidenceStage"] = acquisition_evidence["stage"]
    payload["assetResolution"] = (
        "deterministic local roots; all five CA-1M archives and ten ARKitScenes ZIPs "
        "reverified against the frozen acquisition evidence before preparation"
    )
    preparation_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--acquisition-evidence", type=Path, required=True)
    parser.add_argument("--input-preflight", type=Path, required=True)
    parser.add_argument("--ca1m-root", type=Path, required=True)
    parser.add_argument("--arkit-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    evidence_path = args.acquisition_evidence.resolve()
    evidence = validate_acquisition_evidence(evidence_path)
    runtime_acquisition = resolve_runtime_acquisition(
        evidence,
        ca1m_root=args.ca1m_root,
        arkit_root=args.arkit_root,
    )

    # Keep the mature preparation implementation and frozen math unchanged. Only replace its
    # unavailable path-bearing acquisition-ledger loader with the hash-verified local resolution.
    original_validate_acquisition = base.validate_acquisition
    original_argv = sys.argv
    try:
        base.validate_acquisition = lambda _path: runtime_acquisition
        sys.argv = [
            str(Path(base.__file__).resolve()),
            "--protocol",
            str(args.protocol.resolve()),
            "--acquisition-ledger",
            str(evidence_path),
            "--input-preflight",
            str(args.input_preflight.resolve()),
            "--arkit-root",
            str(args.arkit_root.expanduser().resolve()),
            "--output-root",
            str(args.output_root.expanduser().resolve()),
        ]
        result = base.main()
    finally:
        base.validate_acquisition = original_validate_acquisition
        sys.argv = original_argv

    if result != 0:
        return int(result)
    preparation_path = args.output_root.expanduser().resolve() / "preparation.json"
    finalize_preparation_provenance(
        preparation_path,
        acquisition_evidence_path=evidence_path,
        acquisition_evidence=evidence,
    )
    print(
        json.dumps(
            {
                "u6bPreparationFromFreeze": {
                    "status": "prepared-and-rebound-to-original-acquisition-ledger-sha",
                    "preparation": str(preparation_path),
                    "preparationSha256": base.sha256_file(preparation_path),
                    "acquisitionLedgerSha256": evidence["acquisitionLedgerSha256"],
                    "acquisitionEvidenceSha256": base.sha256_file(evidence_path),
                    "noConfirmatoryOutcomeProduced": True,
                }
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
