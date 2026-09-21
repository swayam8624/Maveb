#!/usr/bin/env python3
"""Fetch one public trained 3DGS PLY for zero-input validation.

The default source is a pinned public trained GraphDECO-style 3DGS PLY. The
repository revision, file path, byte size, and SHA-256 are verified before use
and frozen in provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-id", default="camenduru/gaussian-splatting")
    parser.add_argument("--repo-type", choices=("model", "dataset"), default="model")
    parser.add_argument(
        "--revision",
        default="5c74895a5bd96d6593d916407f102cff86d2ef45",
    )
    parser.add_argument(
        "--file",
        default="train/point_cloud/iteration_30000/point_cloud.ply",
    )
    parser.add_argument(
        "--expected-sha256",
        default="f03e4979ac27345da1422d960d604b98db9541bdb3586d135d64bb4d9bde8eb3",
    )
    parser.add_argument("--expected-bytes", type=int, default=265724108)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    api = HfApi()
    if args.repo_type == "model":
        info = api.model_info(args.repo_id, revision=args.revision, files_metadata=True)
    else:
        info = api.dataset_info(args.repo_id, revision=args.revision, files_metadata=True)

    siblings = {str(s.rfilename): s for s in (info.siblings or [])}
    if args.file not in siblings:
        raise FileNotFoundError(f"{args.file} not found in {args.repo_id}@{args.revision}")
    selected = siblings[args.file]

    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    downloaded = Path(
        hf_hub_download(
            repo_id=args.repo_id,
            filename=selected.rfilename,
            repo_type=args.repo_type,
            revision=args.revision,
            local_dir=root / "download",
        )
    ).resolve()
    target = root / "trained-point-cloud.ply"
    target.write_bytes(downloaded.read_bytes())
    digest = sha256(target)
    size = target.stat().st_size
    if args.expected_bytes > 0 and size != args.expected_bytes:
        raise ValueError(
            f"trained 3DGS byte-size mismatch: got {size}, expected {args.expected_bytes}"
        )
    if args.expected_sha256 and digest.lower() != args.expected_sha256.lower():
        raise ValueError(
            f"trained 3DGS SHA-256 mismatch: got {digest}, expected {args.expected_sha256}"
        )

    card_data = getattr(info, "card_data", None)
    license_value = None
    if card_data is not None:
        try:
            license_value = card_data.get("license")
        except Exception:
            license_value = None

    provenance = {
        "schemaVersion": 1,
        "artifact": "maveb-public-trained-3dgs-source",
        "repoId": args.repo_id,
        "repoType": args.repo_type,
        "repoRevision": args.revision,
        "resolvedRepoRevision": info.sha,
        "file": args.file,
        "fileBytes": size,
        "fileSha256": digest,
        "expectedFileBytes": args.expected_bytes,
        "expectedFileSha256": args.expected_sha256,
        "license": license_value,
        "selectionRule": "explicit pinned repo/revision/file with byte-size and SHA-256 verification",
        "redistribution": False,
        "scientificBoundary": (
            "Used as a secondary trained-3DGS interoperability/CBRC validation source. "
            "Do not redistribute the source PLY; retain upstream attribution and terms."
        ),
    }
    (root / "TRAINED_3DGS_SOURCE.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    )
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
