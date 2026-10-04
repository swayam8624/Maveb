# MAVEB / CBRC canonical evidence freeze — 2026-09-21

This is the durable provenance pointer for the evidence used by the current
paper line. The JSON beside this file is authoritative for machine-readable
IDs, hashes and headline measurements.

## Canonical public v2.1 campaign

- GitHub Actions run: `35576709420`
- Artifact ID: `10629865889`
- Execution test-merge SHA: `ccc8413674933e5a2d58d2ee1a4fd949bd9806ea`
- Artifact ZIP SHA-256:
  `0a69bf097658024856ce92cad6581172d5de08ad73eebc0cf2be68f5110876fe`
- 60 frozen revisions / 4 public RGB/SfM scenes.
- 44 certified-local selections / 16 automatic FULL fallbacks.
- 0 observed certificate violations.
- 60/60 native↔Python planner parity.
- 56/60 source edits exceed the protected RGB tolerance before repair.
- Median calibrated heterogeneous work / FULL:
  `0.3695301075670818`.
- Corresponding calibrated work-reduction factor:
  `2.7061394444523503x`.
- Maximum measured selected RGB residual: `0.0`.
- Maximum selected certified bound: `2e-6`.
- Sparse candidate discovery: exact selection agreement; median inspected
  fraction `0.01`, minimum `0.001`.

**The 2.706x value is calibrated work reduction, not paired end-to-end
wall-clock speedup.**

## Canonical trained-3DGS validation

- GitHub Actions run: `35576709338`
- Artifact ID: `10628629024`
- Artifact ZIP SHA-256:
  `e55bf8899072ece49f776bba2d853ddb7bbfdede1f99e7ee8e57e58d22634d4d`
- 5 revisions / 1 trained public 3DGS scene.
- 4 certified-local selections / 1 automatic FULL fallback.
- 0 observed certificate violations.
- Median native temporal/output work / FULL:
  `0.03494791666666667` (~`28.614x` lower native work).
- Median Gaussian inspected ratio remains
  `0.9999972000873573`, an explicit systems limitation.
- Upstream PLY SHA-256:
  `f03e4979ac27345da1422d960d604b98db9541bdb3586d135d64bb4d9bde8eb3`.

**The 28.614x value is native-work reduction, not wall-clock speedup.**

## Reporting revision

PR #65, merged as `c42971cba36d0575dfd21eb03663bf221e04f9ef`,
changes reporting semantics only: effectivity is undefined when independent
measured residual is numerically zero. The execution artifact predates this
reporting-only cleanup, so regenerate F5/summary from the raw campaign rows with
current `main` instead of quoting the artifact's legacy denominator-floor
effectivity values.

## Completion boundary

The CBRC v1 implementation, frozen evidence, trained-representation check,
paper figures/videos, falsification infrastructure and claim boundaries are
complete. Paper prose, related-work positioning, submission formatting and
external peer review remain.
