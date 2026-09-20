#!/usr/bin/env python3
"""Quantify UV-address churn in MAVEB's current ordinal square-grid texture atlas layout.

The production TextureBaker derives columns/rows/cell from total triangle count
and assigns each triangle tile from its ordinal. This probe measures how many
unchanged triangle IDs change tile/cell coordinates after local insertion or
removal when a mesh is flattened into a new ordinal sequence.

This is a structural dependency probe, not a rendering benchmark.
"""
from __future__ import annotations
import json, math
from pathlib import Path

ATLAS=8192
GUTTER=4

def layout(count):
    columns=math.ceil(math.sqrt(count))
    rows=(count+columns-1)//columns
    cell=min(ATLAS//columns,ATLAS//rows)
    if cell<=GUTTER*2+1:
        return None
    return columns,rows,cell

def tile(ordinal,count):
    cfg=layout(count)
    if cfg is None: return None
    columns,rows,cell=cfg
    return (ordinal%columns,ordinal//columns,cell)

def insertion_churn(count,insert_at,insert_count=1):
    old={i:tile(i,count) for i in range(count)}
    new_count=count+insert_count
    changed=0
    for old_id in range(count):
        new_ordinal=old_id if old_id<insert_at else old_id+insert_count
        if old[old_id]!=tile(new_ordinal,new_count):
            changed+=1
    return changed/count

def removal_churn(count,remove_at,remove_count=1):
    if remove_at+remove_count>count: return None
    new_count=count-remove_count
    changed=0; survivors=0
    for old_id in range(count):
        if remove_at<=old_id<remove_at+remove_count: continue
        survivors+=1
        new_ordinal=old_id if old_id<remove_at else old_id-remove_count
        if tile(old_id,count)!=tile(new_ordinal,new_count):
            changed+=1
    return changed/max(1,survivors)

def run():
    cases=[]
    for count in [9999,10000,10001,99999,100000,100489,100500,249999,250000]:
        for position_name,fraction in [("front",0.0),("quarter",0.25),("middle",0.5),("tail",1.0)]:
            insert_at=min(count,int(count*fraction))
            remove_at=min(count-1,int((count-1)*fraction))
            cases.append({
              "triangles":count,
              "position":position_name,
              "layout":layout(count),
              "insertOneChurnFraction":insertion_churn(count,insert_at,1),
              "removeOneChurnFraction":removal_churn(count,remove_at,1)
            })
    return {
      "schemaVersion":1,
      "experiment":"atlas-uv-churn-v0",
      "atlasSize":ATLAS,
      "gutterPixels":GUTTER,
      "cases":cases,
      "decision":"CURRENT ORDINAL ATLAS IS NOT LOCAL-UPDATE-STABLE. Stable per-patch/page addressing is required before texture work can participate in an exact dependency-local repair claim."
    }

if __name__=="__main__":
    result=run()
    out=Path("research/results/probes/atlas-uv-churn-v0.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
