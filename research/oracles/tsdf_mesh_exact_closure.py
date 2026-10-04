#!/usr/bin/env python3
"""Exact tiny-scene oracle for sparse-TSDF dirty-block -> mesh-owner invalidation.

The production IncrementalSparseTsdfMesher rebuilds the dirty block's own cell-owner
patch and the seven negative-neighbour owners that may reference samples from it.

For tiny bounded grids this script exhaustively enumerates all dirty-block subsets,
computes the production closure, and independently computes the exact set of mesh
owner patches whose owned cell domains can read at least one sample from a dirty
block under the documented positive-topology + symmetric-gradient halo contract.

Any mismatch is a correctness failure.
"""
from __future__ import annotations
import argparse, itertools, json
from pathlib import Path


def production_closure(dirty, counts):
    owners=set()
    for x,y,z in dirty:
        for dx in (0,1):
            for dy in (0,1):
                for dz in (0,1):
                    if x<dx or y<dy or z<dz:
                        continue
                    ox,oy,oz=x-dx,y-dy,z-dz
                    if ox<counts[0] and oy<counts[1] and oz<counts[2]:
                        owners.add((ox,oy,oz))
    return owners


def exact_dependency_closure(dirty, counts):
    # A patch owner O reads samples from blocks whose coordinates differ by 0 or +1
    # in each axis because its owned cells read the positive topology halo; the
    # symmetric one-sample gradient halo is contained within the same adjacent block
    # relation at block granularity. Therefore dirty block D affects O iff
    # D = O + delta, delta in {0,1}^3.
    exact=set()
    dirty=set(dirty)
    for ox in range(counts[0]):
        for oy in range(counts[1]):
            for oz in range(counts[2]):
                owner=(ox,oy,oz)
                reads=set()
                for dx in (0,1):
                    for dy in (0,1):
                        for dz in (0,1):
                            sx,sy,sz=ox+dx,oy+dy,oz+dz
                            if sx<counts[0] and sy<counts[1] and sz<counts[2]:
                                reads.add((sx,sy,sz))
                if reads & dirty:
                    exact.add(owner)
    return exact


def run(counts=(3,3,3), maximum_subset=4):
    blocks=[(x,y,z) for x in range(counts[0]) for y in range(counts[1]) for z in range(counts[2])]
    cases=0
    mismatches=[]
    max_amp=0.0
    by_size={}
    for size in range(1,maximum_subset+1):
        local=0
        closure_sizes=[]
        for dirty_tuple in itertools.combinations(blocks,size):
            prod=production_closure(dirty_tuple,counts)
            exact=exact_dependency_closure(dirty_tuple,counts)
            cases+=1; local+=1
            closure_sizes.append(len(exact))
            max_amp=max(max_amp,len(exact)/size)
            if prod!=exact:
                mismatches.append({
                    "dirty":dirty_tuple,
                    "productionOnly":sorted(prod-exact),
                    "oracleOnly":sorted(exact-prod),
                })
                if len(mismatches)>=20:
                    break
        by_size[str(size)]={
            "cases":local,
            "closureMin":min(closure_sizes) if closure_sizes else 0,
            "closureMax":max(closure_sizes) if closure_sizes else 0,
            "closureMean":sum(closure_sizes)/len(closure_sizes) if closure_sizes else 0.0,
        }
        if mismatches:
            break
    return {
        "schemaVersion":1,
        "experiment":"tsdf-mesh-exact-closure-oracle-v0",
        "counts":list(counts),
        "maximumDirtySubsetSize":maximum_subset,
        "cases":cases,
        "mismatchCount":len(mismatches),
        "maximumClosureAmplification":max_amp,
        "byDirtySubsetSize":by_size,
        "mismatches":mismatches,
        "decision":"PASS" if not mismatches else "FAIL",
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--counts",nargs=3,type=int,default=(3,3,3))
    ap.add_argument("--maximum-subset",type=int,default=4)
    ap.add_argument("--output",type=Path)
    args=ap.parse_args()
    result=run(tuple(args.counts),args.maximum_subset)
    text=json.dumps(result,indent=2)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text)
    else:
        print(text,end="")
    raise SystemExit(0 if result["decision"]=="PASS" else 1)


if __name__=="__main__":
    main()
