#!/usr/bin/env python3
"""Normalize one local VG-Scene sequence into a MAVEB temporal-pair manifest.

This adapter never downloads data. It only inspects a user-provided local sequence directory,
pairs RGB/depth frames deterministically, verifies camera metadata presence, and emits a canonical
manifest that later S1 experiments can consume. Dataset/license review remains external.
"""
from __future__ import annotations

import argparse, json, math, re, sys
from pathlib import Path
from typing import Iterable

IMAGE_EXTENSIONS={".png",".jpg",".jpeg",".bmp",".tif",".tiff",".exr"}

def files_in(directory: Path)->list[Path]:
    return sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)

def first_existing(root:Path,candidates:Iterable[str])->Path|None:
    for rel in candidates:
        p=root/rel
        if p.is_dir(): return p
    return None

def numeric_key(path:Path)->tuple:
    parts=re.findall(r"\d+(?:\.\d+)?",path.stem)
    if parts:
        return (0, *(float(v) for v in parts), path.stem)
    return (1, path.stem)

def pair_frames(rgb:list[Path],depth:list[Path])->list[tuple[Path,Path]]:
    depth_by_stem={p.stem:p for p in depth}
    exact=[(p,depth_by_stem[p.stem]) for p in rgb if p.stem in depth_by_stem]
    if len(exact)==len(rgb)==len(depth): return exact
    if len(rgb)!=len(depth):
        raise ValueError(f"RGB/depth cardinality mismatch: {len(rgb)} vs {len(depth)}")
    return list(zip(sorted(rgb,key=numeric_key),sorted(depth,key=numeric_key),strict=True))

def parse_intrinsic(path:Path)->dict:
    values=[]
    for token in path.read_text().replace(","," ").split():
        try: values.append(float(token))
        except ValueError: continue
    if len(values)>=9:
        fx,fy,cx,cy=values[0],values[4],values[2],values[5]
    elif len(values)>=4:
        fx,fy,cx,cy=values[:4]
    else:
        raise ValueError(f"Cannot parse camera intrinsics from {path}")
    if not all(math.isfinite(v) and v>0 for v in (fx,fy)) or not all(math.isfinite(v) for v in (cx,cy)):
        raise ValueError(f"Invalid camera intrinsics in {path}")
    return {"fx":fx,"fy":fy,"cx":cx,"cy":cy,"source":str(path)}

def discover_camera(sequence:Path,kind:str)->tuple[Path,Path]:
    intrinsic_names=("intrinsic.txt","intrinsics.txt","camera.txt","camera_intrinsic.txt")
    trajectory_names=("traj.txt","groundtruth.txt","trajectory.txt","poses.txt")
    intr=next((sequence/n for n in intrinsic_names if (sequence/n).is_file()),None)
    traj=next((sequence/n for n in trajectory_names if (sequence/n).is_file()),None)
    if intr is None:
        # Real sequences sometimes place camera metadata one level above streams.
        intr=next((p for p in sequence.glob("**/*") if p.is_file() and "intrin" in p.name.lower()),None)
    if traj is None:
        traj=next((p for p in sequence.glob("**/*") if p.is_file() and ("groundtruth" in p.name.lower() or "traj" in p.name.lower())),None)
    if intr is None or traj is None:
        raise ValueError(f"{kind} sequence is missing intrinsic or trajectory metadata")
    return intr,traj

def build(sequence:Path,kind:str)->dict:
    if not sequence.is_dir(): raise ValueError(f"Sequence directory does not exist: {sequence}")
    rgb=first_existing(sequence,("rgb","color","results/rgb","results/color","images","results/images"))
    depth=first_existing(sequence,("depth","results/depth","depths","results/depths"))
    if rgb is None or depth is None: raise ValueError("Unable to discover RGB and depth directories")
    rgb_files,depth_files=files_in(rgb),files_in(depth)
    if not rgb_files or not depth_files: raise ValueError("RGB/depth directories are empty")
    pairs=pair_frames(rgb_files,depth_files)
    intr,traj=discover_camera(sequence,kind)
    camera=parse_intrinsic(intr)
    frames=[{"index":i,"rgb":str(a.relative_to(sequence)),"depth":str(b.relative_to(sequence))}
            for i,(a,b) in enumerate(pairs)]
    return {
      "schemaVersion":1,
      "dataset":"VG-Scene",
      "sequence":sequence.name,
      "kind":kind,
      "frameCount":len(frames),
      "camera":camera,
      "trajectory":str(traj.relative_to(sequence)),
      "frames":frames,
      "temporalContract":{
        "ordered":True,
        "rgbDepthPaired":True,
        "poseMetadataPresent":True,
        "readyForRevisionPartitioning":True
      },
      "note":"Structural adapter only; no claim that VG-Mapping method code has been reproduced."
    }

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("sequence",type=Path)
    ap.add_argument("--kind",choices=("real","synthetic"),required=True)
    ap.add_argument("--output",type=Path)
    ap.add_argument("--validate-only",action="store_true")
    args=ap.parse_args()
    try: payload=build(args.sequence.resolve(),args.kind)
    except Exception as exc:
        print(json.dumps({"ok":False,"error":str(exc)},sort_keys=True))
        return 2
    payload["ok"]=True
    if args.output and not args.validate_only:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        tmp=args.output.with_suffix(args.output.suffix+".tmp")
        tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
        tmp.replace(args.output)
    print(json.dumps(payload,sort_keys=True))
    return 0

if __name__=="__main__": raise SystemExit(main())
