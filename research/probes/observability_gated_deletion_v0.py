#!/usr/bin/env python3
"""Synthetic probe for immediate-removal vs observability-gated world history.

A world contains stable entities on a 1D spatial line. Each frame observes only
one moving coverage window. There are no physical removals.

Baseline semantics approximate PR #28 ingestion: the new snapshot contains only
currently observed entities. A coverage-gated policy carries forward previous
entities outside current coverage because absence there is not evidence.

We count false removals and ID churn on re-observation. This is a correctness
probe, not a publishable benchmark.
"""
from __future__ import annotations
import json
from pathlib import Path

def run(entity_count=100,frames=40,window=20):
    positions={i:float(i) for i in range(entity_count)}
    baseline_present=set(range(entity_count))
    gated_present=set(range(entity_count))
    baseline_ids={i:i for i in range(entity_count)}
    gated_ids={i:i for i in range(entity_count)}
    next_baseline_id=entity_count

    false_removals_baseline=0
    false_removals_gated=0
    id_churn_baseline=0
    id_churn_gated=0

    for frame in range(frames):
        start=(frame*7) % max(1,entity_count-window+1)
        end=start+window
        visible={i for i,p in positions.items() if start<=p<end}

        # No real deletion: every visible physical entity is observed.
        baseline_next=set(visible)
        removed=baseline_present-baseline_next
        false_removals_baseline+=len(removed)

        # Entities reappearing after baseline forgot them receive fresh IDs.
        for entity in visible:
            if entity not in baseline_present:
                id_churn_baseline+=1
                baseline_ids[entity]=next_baseline_id
                next_baseline_id+=1
        baseline_present=baseline_next

        # Coverage-gated: only observed coverage can provide absence evidence.
        # Since every entity in coverage is observed in this fixture, nothing is
        # contradicted; entities outside coverage are carried forward.
        gated_next=set(gated_present)
        gated_next.update(visible)
        false_removals_gated+=0
        for entity in visible:
            if entity not in gated_present:
                id_churn_gated+=1
        gated_present=gated_next

    return {
      "schemaVersion":1,
      "experiment":"observability-gated-deletion-v0",
      "configuration":{"entityCount":entity_count,"frames":frames,"coverageWindowEntities":window},
      "baselineImmediateSnapshot":{"falseRemovals":false_removals_baseline,"idChurnEvents":id_churn_baseline},
      "coverageGated":{"falseRemovals":false_removals_gated,"idChurnEvents":id_churn_gated},
      "decision":"CORRECTNESS FAILURE CONFIRMED IN THE MODEL: absence from a partial observation set cannot be treated as removal. Add explicit observability/contradiction semantics before real persistent-world deletion tests."
    }

if __name__=="__main__":
    result=run()
    out=Path("research/results/probes/observability-gated-deletion-v0.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
