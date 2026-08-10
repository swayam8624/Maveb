#!/usr/bin/env python3
"""Evidence-first real-data benchmark orchestration for Maveb."""
from __future__ import annotations

import argparse, dataclasses, datetime as dt, glob, json, os, shlex, shutil, subprocess, sys, time
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = ROOT / "benchmarks/manifests"
RESULTS = ROOT / "benchmarks/results"
ARKIT_ADAPTER = ROOT / "benchmarks/scripts/adapters/arkitscenes_to_aether.py"
GEOMETRY_EVALUATOR = ROOT / "benchmarks/scripts/evaluate_geometry.py"

@dataclasses.dataclass(slots=True)
class CommandResult:
    argv: list[str]; returncode: int; duration_seconds: float; stdout: str; stderr: str
    def to_json(self) -> dict[str, Any]:
        return {"argv": self.argv, "command": shlex.join(self.argv), "returnCode": self.returncode,
                "durationSeconds": round(self.duration_seconds, 6), "stdout": self.stdout, "stderr": self.stderr}

def utc_now() -> str: return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
def expand_path(value: str) -> Path: return Path(os.path.expanduser(os.path.expandvars(value))).resolve()

def load_manifest(dataset_id: str) -> dict[str, Any]:
    path = MANIFESTS / f"{dataset_id}.json"
    if not path.is_file(): raise ValueError(f"Unknown dataset '{dataset_id}'")
    data = json.loads(path.read_text())
    if data.get("schemaVersion") != SCHEMA_VERSION or data.get("id") != dataset_id:
        raise ValueError(f"Invalid manifest identity: {path}")
    return data

def iter_manifests() -> Iterable[dict[str, Any]]:
    for path in sorted(MANIFESTS.glob("*.json")):
        if path.name == "schema.json": continue
        data = json.loads(path.read_text())
        if data.get("schemaVersion") != SCHEMA_VERSION: raise ValueError(f"Unsupported manifest: {path}")
        yield data

def resolve_tools() -> dict[str, str | None]:
    deps = ROOT / ".aether-deps/bin"
    candidates = {
        "aether-capture": [ROOT / "build/debug/tools/aether-capture/aether-capture", ROOT / "build/ci/tools/aether-capture/aether-capture"],
        "aether-reconstruct": [ROOT / "build/debug/tools/aether-reconstruct/aether-reconstruct", ROOT / "build/ci/tools/aether-reconstruct/aether-reconstruct"],
        "aether-fuse": [ROOT / "build/debug/tools/aether-fuse/aether-fuse", ROOT / "build/ci/tools/aether-fuse/aether-fuse"],
        "colmap": [deps / "colmap"], "brush": [deps / "brush"], "aether-proxy": [deps / "aether-proxy"],
        "proxy-python": [ROOT / ".aether-deps/proxy-venv/bin/python"], "ffmpeg": [], "ffprobe": [],
    }
    out: dict[str, str | None] = {}
    for name, paths in candidates.items():
        local = next((str(p) for p in paths if p.is_file() and os.access(p, os.X_OK)), None)
        out[name] = local or shutil.which(name)
    return out

def run_command(argv: list[str], cwd: Path | None = None) -> CommandResult:
    start = time.monotonic()
    try:
        p = subprocess.run(argv, cwd=str(cwd) if cwd else None, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return CommandResult(argv, p.returncode, time.monotonic()-start, p.stdout, p.stderr)
    except FileNotFoundError as exc:
        return CommandResult(argv, 127, time.monotonic()-start, "", str(exc))

def parse_json_output(result: CommandResult) -> dict[str, Any] | None:
    for text in (result.stdout, result.stderr):
        for line in reversed(text.splitlines()):
            if line.strip().startswith("{"):
                try: return json.loads(line)
                except json.JSONDecodeError: pass
    return None

def git_revision() -> str | None:
    r = run_command(["git", "rev-parse", "HEAD"], ROOT)
    return r.stdout.strip() if r.returncode == 0 else None

def resolve_glob(root: Path, pattern: str) -> list[Path]:
    return [Path(v).resolve() for v in sorted(glob.glob(str(root / pattern), recursive=True))]

def resolve_input(m: dict[str, Any]) -> dict[str, Any]:
    root = expand_path(m["root"]); kind = m["kind"]
    r: dict[str, Any] = {"root": str(root), "exists": root.exists()}
    if kind == "images":
        images = root / m.get("imagesRel", "")
        r.update(images=str(images), ready=images.is_dir())
        if m.get("referenceGeometryRel") or m.get("referenceCamerasRel"):
            g = root / m["referenceGeometryRel"]; c = root / m["referenceCamerasRel"]
            r.update(referenceGeometry=str(g), referenceCameras=str(c), referenceReady=g.is_file() and c.is_file())
    elif kind == "video":
        videos = resolve_glob(root, m["videoGlob"]) if root.exists() else []
        r.update(videos=[str(v) for v in videos], video=str(videos[0]) if videos else None, ready=bool(videos))
    else:
        assets = {k: resolve_glob(root, p) if root.exists() else [] for k,p in m.get("requiredAssets",{}).items()}
        r.update(assets={k:[str(v) for v in values] for k,values in assets.items()}, ready=root.is_dir() and all(assets.values()))
    return r

def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True)+"\n"); tmp.replace(path)

def ensure_clean(path: Path, force: bool) -> None:
    if path.exists():
        if not force: raise ValueError(f"Output exists: {path}; use --force or --run-id")
        shutil.rmtree(path)
    path.mkdir(parents=True)

def command_step(argv: list[str], *, success_key: str = "ok") -> tuple[str, dict[str, Any]]:
    result = run_command(argv, ROOT); payload = parse_json_output(result)
    good = result.returncode == 0 and payload and bool(payload.get(success_key))
    return ("pass" if good else "fail"), {"command": result.to_json(), "payload": payload}

def validate_images(images: Path, t: dict[str,str|None]) -> tuple[str,dict[str,Any]]:
    if not t["aether-capture"]: return "blocked", {"reason":"aether-capture-not-found"}
    return command_step([t["aether-capture"], "validate", str(images), "--json"], success_key="valid")

def reconstruct(images: Path, output: Path, t: dict[str,str|None], a: argparse.Namespace) -> tuple[str,dict[str,Any]]:
    req = ("aether-reconstruct","colmap","brush","aether-proxy"); missing=[n for n in req if not t[n]]
    if missing: return "blocked", {"reason":"missing-tools","tools":missing}
    argv=[t["aether-reconstruct"],str(images),"--output",str(output),"--colmap",t["colmap"],"--brush",t["brush"],
          "--proxy",t["aether-proxy"],"--trainer","brush","--seed","42","--steps",str(a.steps),
          "--checkpoint-every",str(a.checkpoint_every),"--json"]
    if a.dry_run: argv.append("--dry-run")
    return command_step(argv)

def extract_video(video: Path, output: Path, t: dict[str,str|None], fps: float) -> tuple[str,dict[str,Any]]:
    if not t["ffmpeg"]: return "blocked", {"reason":"ffmpeg-not-found"}
    output.mkdir(parents=True, exist_ok=True)
    result=run_command([t["ffmpeg"],"-hide_banner","-loglevel","error","-y","-i",str(video),"-vf",f"fps={fps:g}","-q:v","2",str(output/"frame_%06d.jpg")])
    count=len(list(output.glob("frame_*.jpg"))); status="pass" if result.returncode==0 and count>=3 else "fail"
    return status,{"command":result.to_json(),"frameCount":count,"framesDirectory":str(output),"samplingFps":fps,
                   "note":"Deterministic uniform baseline; adaptive keyframe selection remains a separate gate."}

def video_metadata(video: Path,t:dict[str,str|None])->dict[str,Any]:
    if not t["ffprobe"]: return {"status":"blocked","reason":"ffprobe-not-found"}
    r=run_command([t["ffprobe"],"-v","error","-show_entries","format=duration:stream=width,height,r_frame_rate,codec_name","-of","json",str(video)])
    try: p=json.loads(r.stdout) if r.returncode==0 else None
    except json.JSONDecodeError: p=None
    return {"status":"pass" if p else "fail","command":r.to_json(),"payload":p}

def adapt_arkit(source:Path, output:Path,t:dict[str,str|None],a:argparse.Namespace)->tuple[str,dict[str,Any]]:
    if not t["ffmpeg"]: return "blocked", {"reason":"ffmpeg-not-found"}
    if not ARKIT_ADAPTER.is_file(): return "blocked", {"reason":"arkitscenes-adapter-not-found"}
    argv=[sys.executable,str(ARKIT_ADAPTER),str(source),"--output",str(output),"--stride",str(a.arkit_stride),"--ffmpeg",t["ffmpeg"]]
    if a.arkit_max_frames is not None: argv += ["--max-frames",str(a.arkit_max_frames)]
    return command_step(argv)

def validate_fuse(capture:Path,output:Path,t:dict[str,str|None])->tuple[str,dict[str,Any]]:
    if not t["aether-fuse"]: return "blocked", {"reason":"aether-fuse-not-found"}
    return command_step([t["aether-fuse"],str(capture),"--output",str(output),"--dry-run","--json"])

def evaluate_geometry(job:Path,resolved:dict[str,Any],t:dict[str,str|None],max_points:int)->tuple[str,dict[str,Any]]:
    py=t.get("proxy-python")
    if not py: return "blocked", {"reason":"proxy-python-not-found"}
    candidate=job/"proxy/proxy.ply"; cameras=job/"sparse/0-text/images.txt"
    if not candidate.is_file() or not cameras.is_file(): return "fail", {"reason":"candidate-geometry-or-cameras-missing"}
    argv=[py,str(GEOMETRY_EVALUATOR),str(candidate),resolved["referenceGeometry"],"--candidate-cameras",str(cameras),
          "--reference-cameras",resolved["referenceCameras"],"--align","camera","--thresholds","0.01,0.02,0.05",
          "--max-points",str(max_points),"--aligned-output",str(job.parent/"geometry/aligned-candidate.ply")]
    return command_step(argv)

def run_dataset(a:argparse.Namespace,m:dict[str,Any],t:dict[str,str|None])->dict[str,Any]:
    resolved=resolve_input(m); run_id=a.run_id or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir=RESULTS/m["id"]/run_id; ensure_clean(run_dir,a.force)
    record={"schemaVersion":1,"dataset":m["id"],"title":m["title"],"kind":m["kind"],"startedAt":utc_now(),
            "gitRevision":git_revision(),"resolvedInput":resolved,"steps":[]}
    if not resolved.get("ready"):
        record.update(status="fail",reason="dataset-not-found-or-incomplete",finishedAt=utc_now()); write_json(run_dir/"run.json",record); return record
    kind=m["kind"]
    if kind=="images":
        status,d=validate_images(Path(resolved["images"]),t); record["steps"].append({"name":"capture-validation","status":status,**d})
        if status=="pass" and not a.validate_only:
            job=run_dir/"reconstruction"; status,d=reconstruct(Path(resolved["images"]),job,t,a); record["steps"].append({"name":"reconstruction","status":status,**d})
            if status=="pass" and not a.dry_run and resolved.get("referenceReady"):
                status,d=evaluate_geometry(job,resolved,t,a.geometry_max_points); record["steps"].append({"name":"geometry-evaluation","status":status,**d})
        record["status"]=status
    elif kind=="video":
        video=Path(resolved["video"]); record["steps"].append({"name":"video-metadata",**video_metadata(video,t)})
        frames=run_dir/"frames"; status,d=extract_video(video,frames,t,a.video_fps); record["steps"].append({"name":"video-frame-extraction","status":status,**d})
        if status=="pass": status,d=validate_images(frames,t); record["steps"].append({"name":"capture-validation","status":status,**d})
        if status=="pass" and not a.validate_only: status,d=reconstruct(frames,run_dir/"reconstruction",t,a); record["steps"].append({"name":"reconstruction","status":status,**d})
        record["status"]=status
    elif kind=="arkit-scenes":
        converted=run_dir/"maveb-capture"; status,d=adapt_arkit(Path(resolved["root"]),converted,t,a); record["steps"].append({"name":"arkitscenes-conversion","status":status,**d})
        if status=="pass": status,d=validate_fuse(converted,run_dir/"arkit-fuse-validation.ply",t); record["steps"].append({"name":"aether-fuse-contract","status":status,**d})
        record["status"]=status
    elif kind=="dtu":
        record["status"]="adapter-required"; record["steps"].append({"name":"adapter-status","status":"adapter-required","reason":"DTU camera/reference normalization is not yet mapped to AETHER's evaluation contract"})
    else:
        record["status"]="reference-only"; record["steps"].append({"name":"adapter-status","status":"reference-only","reason":m.get("note","")})
    record["finishedAt"]=utc_now(); write_json(run_dir/"run.json",record); return record

def latest_run(dataset_id:str)->dict[str,Any]|None:
    root=RESULTS/dataset_id
    if not root.is_dir(): return None
    runs=sorted((p for p in root.iterdir() if (p/"run.json").is_file()),reverse=True)
    return json.loads((runs[0]/"run.json").read_text()) if runs else None

def report_markdown(records:list[dict[str,Any]])->str:
    lines=["# MavebBench report","","| Dataset | Kind | Status | Evidence |","|---|---|---:|---|"]
    for r in records:
        evidence=[]
        for s in r.get("steps",[]):
            p=s.get("payload") or {}; summary=p.get("summary") or {}; metrics=p.get("metrics") or {}
            if s["name"]=="capture-validation" and summary.get("imageCount") is not None: evidence.append(f"{summary['imageCount']} images")
            if s["name"]=="video-frame-extraction": evidence.append(f"{s.get('frameCount',0)} extracted frames")
            if s["name"]=="reconstruction":
                if p.get("registeredImages") is not None: evidence.append(f"{p['registeredImages']} registered")
                if p.get("trackedPoints") is not None: evidence.append(f"{p['trackedPoints']} tracks")
            if s["name"]=="geometry-evaluation" and metrics:
                evidence.append(f"Chamfer {metrics['chamferMean']:.4f}"); fs=metrics.get("fScores") or []
                if fs: evidence.append(f"F@{fs[0]['threshold']:.2f} {fs[0]['fScore']:.3f}")
            if s["name"]=="arkitscenes-conversion" and p.get("frames") is not None: evidence.append(f"{p['frames']} RGB-D frames")
        lines.append(f"| {r.get('title',r['dataset'])} | {r.get('kind','')} | **{r.get('status','unknown')}** | {', '.join(evidence) or '—'} |")
    return "\n".join(lines+["","Statuses are evidence-based; unresolved adapter gates are never reported as PASS.",""])

def doctor()->int:
    t=resolve_tools(); data=os.environ.get("MAVEB_DATA"); payload={"repoRoot":str(ROOT),"mavebData":data,
        "mavebDataExists":bool(data and Path(data).expanduser().is_dir()),"tools":t,"manifests":[m["id"] for m in iter_manifests()]}
    print(json.dumps(payload,indent=2)); return 0 if payload["mavebDataExists"] and t["aether-capture"] and t["aether-reconstruct"] else 2

def list_datasets()->int:
    for m in iter_manifests():
        r=resolve_input(m); print(f"{m['id']:<24} {m['kind']:<15} {'READY' if r.get('ready') else 'MISSING':<7} {m['title']}")
    return 0

def suite(a:argparse.Namespace,t:dict[str,str|None])->int:
    ids={"smoke":["eth3d-pipes","uco3d-object","arkitscenes-47333462","dtu-sampleset"],
         "rgb":["eth3d-pipes","eth3d-meadow","tnt-barn","uco3d-object"],"all":[m["id"] for m in iter_manifests()]}[a.suite]
    records=[]
    for dataset_id in ids:
        child=argparse.Namespace(**vars(a)); child.run_id=f"suite-{a.suite}"; child.force=True; records.append(run_dataset(child,load_manifest(dataset_id),t))
    print(report_markdown(records)); return 1 if any(r["status"]=="fail" for r in records) else 0

def report(output:Path|None)->int:
    records=[r for m in iter_manifests() if (r:=latest_run(m["id"]))]
    text=report_markdown(records)
    if output: output.parent.mkdir(parents=True,exist_ok=True); output.write_text(text)
    print(text); return 0

def parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(description="Maveb real-data reconstruction benchmark harness"); sub=p.add_subparsers(dest="command",required=True)
    sub.add_parser("list"); sub.add_parser("doctor")
    def opts(x):
        x.add_argument("--steps",type=int,default=2000); x.add_argument("--checkpoint-every",type=int,default=1000); x.add_argument("--video-fps",type=float,default=2.0)
        x.add_argument("--arkit-stride",type=int,default=6); x.add_argument("--arkit-max-frames",type=int,default=300); x.add_argument("--geometry-max-points",type=int,default=500_000)
        x.add_argument("--dry-run",action="store_true"); x.add_argument("--validate-only",action="store_true"); x.add_argument("--run-id"); x.add_argument("--force",action="store_true")
    r=sub.add_parser("run"); r.add_argument("dataset"); opts(r)
    s=sub.add_parser("suite"); s.add_argument("suite",choices=("smoke","rgb","all")); opts(s)
    q=sub.add_parser("report"); q.add_argument("--output",type=Path); return p

def main(argv:list[str]|None=None)->int:
    a=parser().parse_args(argv)
    try:
        if a.command=="list": return list_datasets()
        if a.command=="doctor": return doctor()
        if a.command=="report": return report(a.output)
        t=resolve_tools()
        if a.command=="run":
            r=run_dataset(a,load_manifest(a.dataset),t); print(json.dumps(r,indent=2)); return 1 if r["status"]=="fail" else 0
        return suite(a,t)
    except (ValueError,OSError) as exc:
        print(f"mavebbench: {exc}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
