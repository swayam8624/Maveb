#!/usr/bin/env python3
"""Convert ARKitScenes raw low-resolution RGB-D into MavebCapture schema-v2."""
from __future__ import annotations

import argparse, bisect, hashlib, json, math, shutil, struct, subprocess, sys
from pathlib import Path
from typing import Iterable

POSE_TOLERANCE_SECONDS=0.0051; ASSET_TOLERANCE_SECONDS=0.0011

def timestamp_from_path(path:Path)->float:
    try: return float(path.stem.rsplit("_",1)[1])
    except (IndexError,ValueError) as exc: raise ValueError(f"Cannot parse timestamp from {path.name}") from exc

def rodrigues(v:tuple[float,float,float])->list[list[float]]:
    x,y,z=v; theta=math.sqrt(x*x+y*y+z*z)
    if theta<1e-12: return [[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]
    x,y,z=x/theta,y/theta,z/theta; c=math.cos(theta); s=math.sin(theta); q=1-c
    return [[x*x*q+c,x*y*q-z*s,x*z*q+y*s],[y*x*q+z*s,y*y*q+c,y*z*q-x*s],[z*x*q-y*s,z*y*q+x*s,z*z*q+c]]

def trajectory_to_camera_to_world(tokens:list[float])->list[float]:
    if len(tokens)!=7: raise ValueError("trajectory lines require seven values")
    r=rodrigues((tokens[1],tokens[2],tokens[3])); rt=[[r[j][i] for j in range(3)] for i in range(3)]; t=tokens[4:7]
    p=[-sum(rt[i][j]*t[j] for j in range(3)) for i in range(3)]
    return [rt[0][0],rt[1][0],rt[2][0],0.,rt[0][1],rt[1][1],rt[2][1],0.,rt[0][2],rt[1][2],rt[2][2],0.,p[0],p[1],p[2],1.]

def load_trajectory(path:Path)->tuple[list[float],dict[float,list[float]]]:
    poses={}
    for number,line in enumerate(path.read_text().splitlines(),1):
        if not line.strip(): continue
        try: values=[float(v) for v in line.split()]
        except ValueError as exc: raise ValueError(f"{path}:{number}: invalid trajectory") from exc
        if len(values)!=7: raise ValueError(f"{path}:{number}: expected seven fields")
        poses[values[0]]=trajectory_to_camera_to_world(values)
    if not poses: raise ValueError(f"No poses in {path}")
    return sorted(poses),poses

def nearest_timestamp(target:float,values:list[float],tolerance:float)->float|None:
    i=bisect.bisect_left(values,target); c=[]
    if i<len(values): c.append(values[i])
    if i: c.append(values[i-1])
    if not c: return None
    best=min(c,key=lambda v:abs(v-target)); return best if abs(best-target)<=tolerance else None

def timestamp_index(paths:Iterable[Path])->tuple[list[float],dict[float,Path]]:
    m={timestamp_from_path(p):p for p in paths}; return sorted(m),m

def near(target:float,times:list[float],mapping:dict[float,Path],tol:float)->Path|None:
    match=nearest_timestamp(target,times,tol); return mapping.get(match) if match is not None else None

def read_intrinsics(path:Path)->tuple[int,int,float,float,float,float]:
    values=path.read_text().strip().split()
    if len(values)!=6: raise ValueError(f"Invalid .pincam: {path}")
    w,h,fx,fy,cx,cy=map(float,values)
    if w<=0 or h<=0 or fx<=0 or fy<=0: raise ValueError(f"Invalid calibration: {path}")
    return int(w),int(h),fx,fy,cx,cy

def ffmpeg_decode(ffmpeg:str,source:Path,pixel_format:str)->bytes:
    p=subprocess.run([ffmpeg,"-hide_banner","-loglevel","error","-i",str(source),"-frames:v","1","-f","rawvideo","-pix_fmt",pixel_format,"pipe:1"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if p.returncode: raise RuntimeError(p.stderr.decode(errors="replace").strip())
    return p.stdout

def depth_to_f32(raw:bytes,count:int)->bytes:
    if len(raw)!=count*2: raise ValueError("depth byte count mismatch")
    out=bytearray(count*4)
    for i in range(count): struct.pack_into("<f",out,i*4,struct.unpack_from("<H",raw,i*2)[0]*0.001)
    return bytes(out)

def write_plane(root:Path,path:Path,data:bytes,w:int,h:int,stride:int,fmt:str)->dict[str,object]:
    path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)
    return {"path":path.relative_to(root).as_posix(),"sha256":hashlib.sha256(data).hexdigest(),"width":w,"height":h,
            "rowStrideBytes":stride,"pixelFormat":fmt,"byteCount":len(data)}

def convert(source:Path,output:Path,*,stride:int,maximum_frames:int|None,ffmpeg:str)->dict[str,object]:
    if stride<=0: raise ValueError("--stride must be positive")
    traj=source/"lowres_wide.traj"; rgb_dir=source/"lowres_wide"; depth_dir=source/"lowres_depth"; conf_dir=source/"confidence"; intr_dir=source/"lowres_wide_intrinsics"
    for required in (traj,rgb_dir,depth_dir,intr_dir):
        if not required.exists(): raise ValueError(f"Missing ARKitScenes asset: {required}")
    pose_t,poses=load_trajectory(traj); rgb_t,rgbs=timestamp_index(rgb_dir.glob("*.png")); depth_t,depths=timestamp_index(depth_dir.glob("*.png")); intr_t,intrs=timestamp_index(intr_dir.glob("*.pincam")); conf_t,confs=timestamp_index(conf_dir.glob("*.png")) if conf_dir.is_dir() else ([],{})
    candidates=depth_t[::stride]; candidates=candidates[:maximum_frames] if maximum_frames is not None else candidates
    if output.exists(): shutil.rmtree(output)
    output.mkdir(parents=True); frames=[]; skipped={"rgb":0,"intrinsics":0,"pose":0,"decode":0}
    for timestamp in candidates:
        rgb=near(timestamp,rgb_t,rgbs,ASSET_TOLERANCE_SECONDS); intr=near(timestamp,intr_t,intrs,ASSET_TOLERANCE_SECONDS); pose_tstamp=nearest_timestamp(timestamp,pose_t,POSE_TOLERANCE_SECONDS)
        if rgb is None: skipped["rgb"]+=1; continue
        if intr is None: skipped["intrinsics"]+=1; continue
        if pose_tstamp is None: skipped["pose"]+=1; continue
        w,h,fx,fy,cx,cy=read_intrinsics(intr)
        if (w,h)!=(256,192): raise ValueError(f"Expected 256x192 lowres_wide, got {w}x{h}")
        confidence=near(timestamp,conf_t,confs,ASSET_TOLERANCE_SECONDS) if conf_t else None
        try:
            nv12=ffmpeg_decode(ffmpeg,rgb,"nv12"); depth=depth_to_f32(ffmpeg_decode(ffmpeg,depths[timestamp],"gray16le"),w*h); conf=ffmpeg_decode(ffmpeg,confidence,"gray") if confidence else None
            if len(nv12)!=w*h*3//2 or (conf is not None and len(conf)!=w*h): raise ValueError("decoded plane byte count mismatch")
        except (RuntimeError,ValueError): skipped["decode"]+=1; continue
        fid=len(frames)+1; d=output/"frames"/f"{fid:06d}"; luma=write_plane(output,d/"luma.y8",nv12[:w*h],w,h,w,"y8"); chroma=write_plane(output,d/"chroma.cbcr8x2",nv12[w*h:],w//2,h//2,w,"cbcr8x2"); depthp=write_plane(output,d/"depth.f32",depth,w,h,w*4,"depth-f32-metres")
        k=[fx,0.,0.,0.,fy,0.,cx,cy,1.]; frame={"frameID":fid,"arTimestampSeconds":timestamp,"hostTimestampNanoseconds":int(round(timestamp*1e9)),"nativeImageOrientation":"landscapeRight","mirrored":False,"cameraTrackingState":"normal","cameraToWorld":poses[pose_tstamp],"calibration":{"imageWidth":w,"imageHeight":h,"depthWidth":w,"depthHeight":h,"imageIntrinsics":k,"depthIntrinsics":k},"luma":luma,"chroma":chroma,"depth":depthp}
        if conf is not None: frame["confidence"]=write_plane(output,d/"confidence.u8",conf,w,h,w,"arkit-confidence-u8")
        frames.append(frame)
    if not frames: raise ValueError("No synchronized ARKitScenes frames could be converted")
    manifest={"schemaVersion":2,"sourceID":f"arkitscenes-{source.name}","coordinateSystem":{"camera":"ARKit right-handed: +X right, +Y up, -Z forward","pose":"column-major camera-to-world 4x4 matrix","depthUnit":"metres","intrinsics":"3x3 column-major pixels"},"frames":frames,"adapter":{"name":"MavebBench ARKitScenes raw adapter","source":str(source),"stride":stride,"candidateFrames":len(candidates),"convertedFrames":len(frames),"skipped":skipped,"notes":["depth uint16 millimetres -> float32 metres","RGB PNG -> NV12 planes","trajectory world-to-camera axis-angle -> ARKit camera-to-world"]}}
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n"); return manifest

def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(); p.add_argument("source",type=Path); p.add_argument("--output",type=Path,required=True); p.add_argument("--stride",type=int,default=6); p.add_argument("--max-frames",type=int); p.add_argument("--ffmpeg",default=shutil.which("ffmpeg") or "ffmpeg"); a=p.parse_args(argv)
    try: manifest=convert(a.source.resolve(),a.output.resolve(),stride=a.stride,maximum_frames=a.max_frames,ffmpeg=a.ffmpeg)
    except (OSError,RuntimeError,ValueError) as exc: print(f"arkitscenes_to_aether: {exc}",file=sys.stderr); return 2
    print(json.dumps({"ok":True,"output":str(a.output.resolve()),"frames":len(manifest["frames"])})); return 0

if __name__=="__main__": raise SystemExit(main())
