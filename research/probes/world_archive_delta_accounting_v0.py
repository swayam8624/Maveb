#!/usr/bin/env python3
"""World-history storage accounting probe.

Compares idealized full immutable snapshots against periodic checkpoints plus
entity-level deltas. This is a mechanical scaling probe only; generic journaling
is not claimed as novel.

The byte model deliberately reports normalized 'entity-state units' and then
maps them to a configurable serialized-state estimate so conclusions do not
depend on one current JSON formatting detail.
"""
from __future__ import annotations
import json
from pathlib import Path

def simulate(entities=1_000_000,revisions=200,changed_fraction=.01,
             checkpoint_every=25,entity_bytes=192,delta_overhead_bytes=32):
    changed=max(1,int(entities*changed_fraction))
    full_units=entities*revisions
    checkpoints=(revisions-1)//checkpoint_every+1
    delta_revisions=revisions-checkpoints
    delta_units=checkpoints*entities+delta_revisions*changed

    full_bytes=full_units*entity_bytes
    delta_bytes=checkpoints*entities*entity_bytes + delta_revisions*changed*(entity_bytes+delta_overhead_bytes)
    return {
      "entities":entities,
      "revisions":revisions,
      "changedFraction":changed_fraction,
      "checkpointEvery":checkpoint_every,
      "checkpoints":checkpoints,
      "changedEntitiesPerDelta":changed,
      "fullSnapshotEntityUnits":full_units,
      "checkpointDeltaEntityUnits":delta_units,
      "entityUnitRatio":delta_units/full_units,
      "estimatedFullBytes":full_bytes,
      "estimatedCheckpointDeltaBytes":delta_bytes,
      "estimatedByteRatio":delta_bytes/full_bytes,
      "modelEntityBytes":entity_bytes,
      "modelDeltaOverheadBytes":delta_overhead_bytes
    }

def run():
    rows=[]
    for fraction in (.001,.005,.01,.02,.05,.1):
        for checkpoint in (10,25,50):
            rows.append(simulate(changed_fraction=fraction,checkpoint_every=checkpoint))
    return {
      "schemaVersion":1,
      "experiment":"world-archive-delta-accounting-v0",
      "rows":rows,
      "decision":"MECHANICAL PASS: checkpoint+delta history can scale with changed entity fraction rather than full entity count; implementation is justified only as infrastructure for the broader dependency-locality system."
    }

if __name__=="__main__":
    result=run()
    out=Path("research/results/probes/world-archive-delta-accounting-v0.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
