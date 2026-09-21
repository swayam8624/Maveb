#!/usr/bin/env python3
"""Fetch one public trained 3DGS PLY for zero-input validation.

The default source is a public Hugging Face model repository containing many
trained 3DGS variants. We query file metadata and deterministically choose the
smallest non-empty point_cloud.ply unless --file is supplied. The exact repo
revision, file path, size and SHA-256 are frozen in provenance.
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
    parser.add_argument("--repo-id", default="3DGSQA/recon_variants_v3")
    parser.add_argument("--repo-type", choices=("model", "dataset"), default="model")
    parser.add_argument("--file")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    api = HfApi()
    if args.repo_type == "model":
        info = api.model_info(args.repo_id, files_metadata=True)
    else:
        info = api.dataset_info(args.repo_id, files_metadata=True)

    siblings = list(info.siblings or [])
    candidates = [
        sibling
        for sibling in siblings
        if str(sibling.rfilename).endswith("point_cloud.ply")
        and (getattr(sibling, "size", None) or 0) > 0
    ]
    if args.file:
        candidates = [s for s in candidates if s.rfilename == args.file]
        if not candidates:
            raise FileNotFoundError(f"{args.file} is not a non-empty point_cloud.ply in {args.repo_id}")
    elif not candidates:
        raise RuntimeError(f"{args.repo_id} exposes no non-empty point_cloud.ply files")
    else:
        candidates.sort(key=lambda s: (int(s.size), str(s.rfilename)))

    selected = candidates[0]
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    downloaded = Path(
        hf_hub_download(
            repo_id=args.repo_id,
            filename=selected.rfilename,
            repo_type=args.repo_type,
            revision=info.sha,
            local_dir=root / "download",
        )
    ).resolve()
    target = root / "trained-point-cloud.ply"
    target.write_bytes(downloaded.read_bytes())

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
        "repoRevision": info.sha,
        "file": selected.rfilename,
        "fileBytes": target.stat().st_size,
        "fileSha256": sha256(target),
        "license": license_value,
        "selectionRule": (
            "explicit --file" if args.file else "smallest non-empty point_cloud.ply by Hub metadata"
        ),
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
