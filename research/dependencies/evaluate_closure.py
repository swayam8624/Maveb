#!/usr/bin/env python3
"""Dependency-closure evaluator for MAVEB S1 experiments."""
from __future__ import annotations
import argparse, json
from collections import defaultdict, deque
from pathlib import Path


def evaluate(payload):
    nodes={node["id"]:node for node in payload["nodes"]}
    outgoing=defaultdict(list)
    for edge in payload["edges"]:
        if edge["source"] not in nodes or edge["target"] not in nodes:
            raise ValueError("edge references unknown node")
        outgoing[edge["source"]].append(edge["target"])

    changed=list(payload["change"]["changedSources"])
    for node in changed:
        if node not in nodes:
            raise ValueError(f"unknown changed node {node}")

    affected=set(changed)
    queue=deque(changed)
    while queue:
        source=queue.popleft()
        for target in outgoing[source]:
            if target in affected:
                continue
            affected.add(target)
            queue.append(target)

    by_kind=defaultdict(lambda:{"count":0,"bytes":0})
    for node_id in affected:
        node=nodes[node_id]
        bucket=by_kind[node["kind"]]
        bucket["count"]+=1
        bucket["bytes"]+=int(node.get("bytes",0))

    result={
        "schemaVersion":1,
        "affectedNodeIds":sorted(affected),
        "affectedByKind":dict(sorted(by_kind.items())),
        "affectedNodeCount":len(affected),
        "affectedBytes":sum(int(nodes[node].get("bytes",0)) for node in affected),
    }

    expected=payload.get("change",{}).get("expectedAffected")
    if expected is not None:
        expected=set(expected)
        result["oracleComparison"]={
            "falsePositives":sorted(affected-expected),
            "falseNegatives":sorted(expected-affected),
            "exactMatch":affected==expected,
        }
    return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("input",type=Path)
    ap.add_argument("--output",type=Path)
    args=ap.parse_args()
    result=evaluate(json.loads(args.input.read_text()))
    text=json.dumps(result,indent=2)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text)
    else:
        print(text,end="")
    if result.get("oracleComparison",{}).get("falseNegatives"):
        raise SystemExit(2)


if __name__=="__main__":
    main()
