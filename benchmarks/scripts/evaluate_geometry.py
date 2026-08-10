#!/usr/bin/env python3
"""Camera-aligned geometry evaluation using Maveb's pinned Open3D environment."""
from __future__ import annotations
import argparse,json,math,sys
from pathlib import Path
from typing import Iterable

def quaternion_rotation(qw:float,qx:float,qy:float,qz:float):
    import numpy as np
    n=math.sqrt(qw*qw+qx*qx+qy*qy+qz*qz)
    if n<=0: raise ValueError("zero-length COLMAP quaternion")
    w,x,y,z=qw/n,qx/n,qy/n,qz/n
    return np.asarray([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]],dtype=float)

def parse_colmap_camera_centers(path:Path)->dict[str,object]:
    import numpy as np
    centers={}; expecting=True
    for raw in path.read_text().splitlines():
        line=raw.strip()
        if not line or line.startswith("#"): continue
        if not expecting: expecting=True; continue
        f=line.split()
        if len(f)<10: raise ValueError(f"Malformed COLMAP image line in {path}")
        q=list(map(float,f[1:5])); t=np.asarray(list(map(float,f[5:8])),dtype=float); r=quaternion_rotation(*q)
        centers[f[9]]=-(r.T@t); expecting=False
    if not centers: raise ValueError(f"No camera poses in {path}")
    return centers

def umeyama_similarity(source,target):
    import numpy as np
    source=np.asarray(source,dtype=float); target=np.asarray(target,dtype=float)
    if source.shape!=target.shape or source.ndim!=2 or source.shape[1]!=3 or source.shape[0]<3: raise ValueError("similarity fit requires matching Nx3 arrays with N>=3")
    sm=source.mean(0); tm=target.mean(0); s=source-sm; t=target-tm; var=float((s*s).sum()/len(source))
    if var<=1e-18: raise ValueError("zero camera-centre variance")
    u,singular,vt=np.linalg.svd((t.T@s)/len(source)); signs=np.ones(3)
    if np.linalg.det(u)*np.linalg.det(vt)<0: signs[-1]=-1
    r=u@np.diag(signs)@vt; scale=float((singular*signs).sum()/var)
    if not math.isfinite(scale) or scale<=0: raise ValueError("invalid similarity scale")
    transform=np.eye(4); transform[:3,:3]=scale*r; transform[:3,3]=tm-scale*(r@sm); return transform,scale

def camera_similarity(candidate:Path,reference:Path):
    import numpy as np
    a=parse_colmap_camera_centers(candidate); b=parse_colmap_camera_centers(reference); names=sorted(set(a)&set(b))
    if len(names)<3: raise ValueError(f"Only {len(names)} matching camera names; need >=3")
    source=np.asarray([a[n] for n in names]); target=np.asarray([b[n] for n in names]); transform,scale=umeyama_similarity(source,target)
    aligned=(transform[:3,:3]@source.T).T+transform[:3,3]; errors=np.linalg.norm(aligned-target,axis=1)
    return transform,{"method":"camera-centre-umeyama-sim3","matchedCameras":len(names),"scale":scale,"cameraRmse":float(math.sqrt(float((errors*errors).mean()))),"cameraMedianError":float(np.median(errors)),"cameraMaximumError":float(errors.max()),"cameraNames":names}

def geometry_to_cloud(path:Path,max_points:int,seed:int):
    import open3d as o3d
    o3d.utility.random.seed(seed); mesh=o3d.io.read_triangle_mesh(str(path),enable_post_processing=False)
    if mesh.has_vertices() and mesh.has_triangles():
        count=min(max_points,max(10000,len(mesh.triangles)*4)); cloud=mesh.sample_points_uniformly(number_of_points=count)
        return cloud,{"kind":"triangle-mesh","vertices":len(mesh.vertices),"triangles":len(mesh.triangles),"sampledPoints":len(cloud.points)}
    cloud=o3d.io.read_point_cloud(str(path))
    if not cloud.has_points(): raise ValueError(f"Could not read geometry: {path}")
    if len(cloud.points)>max_points:
        step=max(1,len(cloud.points)//max_points); cloud=cloud.select_by_index(list(range(0,len(cloud.points),step))[:max_points])
    return cloud,{"kind":"point-cloud","points":len(cloud.points)}

def percentile(values,fraction:float)->float:
    if not values: return math.nan
    ordered=sorted(map(float,values)); return ordered[min(len(ordered)-1,max(0,int(round((len(ordered)-1)*fraction))))]

def f_score(candidate:Iterable[float],reference:Iterable[float],threshold:float)->dict[str,float]:
    a=list(candidate); b=list(reference); p=sum(v<=threshold for v in a)/max(1,len(a)); r=sum(v<=threshold for v in b)/max(1,len(b)); f=0. if p+r==0 else 2*p*r/(p+r)
    return {"threshold":threshold,"precision":p,"recall":r,"fScore":f}

def evaluate(a:argparse.Namespace)->dict[str,object]:
    import numpy as np, open3d as o3d
    candidate,ci=geometry_to_cloud(a.candidate,a.max_points,a.seed); reference,ri=geometry_to_cloud(a.reference,a.max_points,a.seed); transform=np.eye(4); alignment={"method":"none"}
    if a.candidate_cameras and a.reference_cameras: transform,alignment=camera_similarity(a.candidate_cameras,a.reference_cameras); candidate.transform(transform)
    elif a.align!="none": raise ValueError("camera alignment requires both camera files")
    ad=list(candidate.compute_point_cloud_distance(reference)); rd=list(reference.compute_point_cloud_distance(candidate))
    if not ad or not rd: raise ValueError("no distance samples")
    accuracy=float(np.mean(ad)); completeness=float(np.mean(rd)); thresholds=[float(v) for v in a.thresholds.split(",") if v.strip()]
    metrics={"accuracyMean":accuracy,"accuracyMedian":float(np.median(ad)),"accuracyP95":percentile(ad,.95),"completenessMean":completeness,"completenessMedian":float(np.median(rd)),"completenessP95":percentile(rd,.95),"chamferMean":.5*(accuracy+completeness),"fScores":[f_score(ad,rd,t) for t in thresholds],"candidateSamples":len(ad),"referenceSamples":len(rd)}
    payload={"ok":True,"candidate":str(a.candidate.resolve()),"reference":str(a.reference.resolve()),"candidateGeometry":ci,"referenceGeometry":ri,"alignment":{**alignment,"matrixRowMajor":transform.tolist()},"units":"reference-coordinate units (metres for ETH3D/metric scanner references)","metrics":metrics}
    if a.aligned_output:
        a.aligned_output.parent.mkdir(parents=True,exist_ok=True)
        if not o3d.io.write_point_cloud(str(a.aligned_output),candidate,write_ascii=False,compressed=False): raise ValueError("failed to write aligned point cloud")
        payload["alignedOutput"]=str(a.aligned_output.resolve())
    return payload

def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(); p.add_argument("candidate",type=Path); p.add_argument("reference",type=Path); p.add_argument("--candidate-cameras",type=Path); p.add_argument("--reference-cameras",type=Path); p.add_argument("--align",choices=("none","camera"),default="camera"); p.add_argument("--thresholds",default="0.01,0.02,0.05"); p.add_argument("--max-points",type=int,default=500000); p.add_argument("--seed",type=int,default=42); p.add_argument("--aligned-output",type=Path); a=p.parse_args(argv)
    try: payload=evaluate(a)
    except (OSError,RuntimeError,ValueError) as exc: print(json.dumps({"ok":False,"error":str(exc)}),file=sys.stderr); return 2
    print(json.dumps(payload)); return 0

if __name__=="__main__": raise SystemExit(main())
