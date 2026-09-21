#!/usr/bin/env python3
"""Stable-slot Gaussian revision traffic sanity probe.

This is not a performance benchmark. It estimates canonical-record write traffic
for a fixed-capacity stable-slot model versus whole-asset reloads across repeated
small revisions. AetherGaussianGpu is 256 bytes by ABI.

The purpose is only to decide whether implementing a patchable GPU record store
is mechanically capable of eliminating full canonical-buffer rewrite traffic.
"""
from __future__ import annotations
import json
from pathlib import Path

RECORD_BYTES=256

def simulate(initial=1_000_000,capacity_factor=1.25,revisions=200,
             modify_fraction=.01,split_fraction=.001,merge_fraction=.0005):
    capacity=int(initial*capacity_factor)
    active=initial
    free=capacity-initial
    full_bytes=0
    patch_bytes=0
    max_active=active
    completed=0
    for _ in range(revisions):
        n=active
        modify=max(1,int(n*modify_fraction))
        split=max(0,int(n*split_fraction))
        merge=max(0,int(n*merge_fraction))
        if split>free:
            break
        full_bytes+=n*RECORD_BYTES
        active+=split
        free-=split
        merge=min(merge,active//2)
        active-=merge
        free+=merge
        # Count parent+child writes for split, survivor+tombstone writes for merge.
        patch_bytes+=(modify+2*split+2*merge)*RECORD_BYTES
        max_active=max(max_active,active)
        completed+=1
    return {
      "modifyFraction":modify_fraction,
      "revisionsCompleted":completed,
      "capacity":capacity,
      "finalActive":active,
      "freeSlots":free,
      "maxActive":max_active,
      "fullReloadBytes":full_bytes,
      "stableSlotWriteBytes":patch_bytes,
      "writeRatio":patch_bytes/full_bytes if full_bytes else None,
      "capacityExhausted":completed<revisions
    }

def run():
    rows=[simulate(modify_fraction=f) for f in (.001,.005,.01,.02,.05)]
    return {
      "schemaVersion":1,
      "experiment":"gaussian-stable-slot-traffic-v0",
      "recordBytes":RECORD_BYTES,
      "configuration":{"initial":1_000_000,"capacityFactor":1.25,"revisions":200,
                       "splitFractionPerRevision":.001,"mergeFractionPerRevision":.0005},
      "rows":rows,
      "decision":"MECHANICAL PASS ONLY: patch traffic scales with changed primitive count in this accounting model. Real viability depends on fragmentation, active-slot iteration, Metal update latency, and split/merge semantics."
    }

if __name__=="__main__":
    result=run()
    out=Path("research/results/probes/gaussian-stable-slot-traffic-v0.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
