#!/usr/bin/env python3
"""Fetch and safely extract the pinned public RGB/COLMAP benchmark source."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict:
    payload = json.loads(path.read_text())
    required = ["url", "expectedBytes", "sha256", "primaryScenes", "sourceId"]
    for key in required:
        if key not in payload:
            raise ValueError(f"source manifest missing {key}")
    return payload


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MAVEB-CBRC-public-benchmark/1.0"},
    )
    temporary = destination.with_suffix(destination.suffix + ".part")
    if temporary.exists():
        temporary.unlink()

    downloaded = 0
    with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as out:
        total = response.headers.get("Content-Length")
        total_bytes = int(total) if total and total.isdigit() else None
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            downloaded += len(chunk)
            if sys.stderr.isatty():
                if total_bytes:
                    pct = 100.0 * downloaded / total_bytes
                    print(
                        f"\rDownloaded {downloaded / (1024**2):.1f} MiB "
                        f"/ {total_bytes / (1024**2):.1f} MiB ({pct:.1f}%)",
                        end="",
                        file=sys.stderr,
                        flush=True,
                    )
                else:
                    print(
                        f"\rDownloaded {downloaded / (1024**2):.1f} MiB",
                        end="",
                        file=sys.stderr,
                        flush=True,
                    )
    if sys.stderr.isatty():
        print(file=sys.stderr)
    temporary.replace(destination)


def verify_archive(path: Path, expected_bytes: int, expected_sha256: str) -> dict:
    size = path.stat().st_size
    digest = sha256(path)
    if size != expected_bytes:
        raise ValueError(
            f"archive size mismatch: got {size}, expected {expected_bytes}"
        )
    if digest.lower() != expected_sha256.lower():
        raise ValueError(
            f"archive SHA-256 mismatch: got {digest}, expected {expected_sha256}"
        )
    return {"bytes": size, "sha256": digest}


def safe_extract_selected(
    archive: Path,
    destination: Path,
    scenes: list[dict],
) -> list[dict]:
    prefixes: dict[str, list[str]] = {}
    for scene in scenes:
        scene_id = str(scene["id"])
        raw = scene.get("memberPrefixes")
        if raw is None:
            raw = [scene.get("memberPrefix")]
        if not isinstance(raw, list) or not raw or not all(isinstance(v, str) and v for v in raw):
            raise ValueError(f"scene {scene_id} requires memberPrefix/memberPrefixes")
        prefixes[scene_id] = [str(v) for v in raw]
    extracted: dict[str, list[str]] = {scene_id: [] for scene_id in prefixes}
    destination.mkdir(parents=True, exist_ok=True)
    destination_resolved = destination.resolve()

    with zipfile.ZipFile(archive, "r") as handle:
        infos = handle.infolist()
        for info in infos:
            member = info.filename.replace("\\", "/")
            scene_id = None
            matched_prefix = None
            for candidate_id, candidates in prefixes.items():
                for prefix in candidates:
                    if member.startswith(prefix):
                        scene_id = candidate_id
                        matched_prefix = prefix
                        break
                if scene_id is not None:
                    break
            if scene_id is None or matched_prefix is None or info.is_dir():
                continue

            relative = Path(member[len(matched_prefix):])
            if not relative.parts or relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"unsafe ZIP member: {member}")

            target = destination / scene_id / "sparse" / "0" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            resolved = target.resolve()
            if destination_resolved not in resolved.parents:
                raise ValueError(f"ZIP member escapes destination: {member}")
            with handle.open(info, "r") as source, target.open("wb") as out:
                shutil.copyfileobj(source, out)
            extracted[scene_id].append(str(target))

    report = []
    for scene in scenes:
        scene_id = str(scene["id"])
        model_dir = destination / scene_id / "sparse" / "0"
        points = model_dir / "points3D.bin"
        if not points.is_file():
            points = model_dir / "points3D.txt"
        if not points.is_file():
            raise FileNotFoundError(
                f"scene {scene_id} missing points3D.bin/points3D.txt after extraction"
            )
        report.append(
            {
                "sceneId": scene_id,
                "modelDir": str(model_dir.resolve()),
                "pointsPath": str(points.resolve()),
                "pointsSha256": sha256(points),
                "files": sorted(extracted[scene_id]),
            }
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("research/config/cbrc_public_real_sources.json"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument(
        "--scene-set",
        choices=("primary", "v2"),
        default="primary",
        help="primary=pilot T&T scenes; v2=four-scene paper campaign",
    )
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache = output / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    archive = (
        args.archive.expanduser().resolve()
        if args.archive
        else cache / Path(str(manifest["url"])).name
    )

    if args.force_download and archive.exists() and not args.archive:
        archive.unlink()

    if not archive.exists():
        if args.archive:
            raise FileNotFoundError(archive)
        print(f"Downloading {manifest['url']}", file=sys.stderr)
        download(str(manifest["url"]), archive)

    integrity = verify_archive(
        archive,
        int(manifest["expectedBytes"]),
        str(manifest["sha256"]),
    )

    extracted_root = output / "extracted"
    scene_key = "primaryScenes" if args.scene_set == "primary" else "campaignV2Scenes"
    if scene_key not in manifest:
        raise ValueError(f"source manifest missing {scene_key}")
    scenes = safe_extract_selected(
        archive,
        extracted_root,
        list(manifest[scene_key]),
    )

    report = {
        "schemaVersion": 1,
        "artifact": "maveb-public-rgb-colmap-source",
        "sourceId": manifest["sourceId"],
        "sourceManifest": str(args.manifest.resolve()),
        "url": manifest["url"],
        "archive": str(archive.resolve()),
        "archiveBytes": integrity["bytes"],
        "archiveSha256": integrity["sha256"],
        "license": manifest.get("license"),
        "sceneSet": args.scene_set,
        "scenes": scenes,
    }
    report_path = output / "PUBLIC_SOURCE_PROVENANCE.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
