# CBRC paper claim ledger — 2026-09-21

This ledger translates the frozen MAVEB/CBRC evidence into statements that are
supported, statements that require careful qualification, and statements that
must not appear in the paper as established facts.

It is intentionally stricter than promotional project language.

## Supported by the frozen v2.1 public campaign

- The campaign contains **60 frozen revision cases across four public RGB/SfM
  scenes**.
- CBRC selected a **certified local repair in 44/60 cases** and an **automatic
  FULL fallback in 16/60 cases**.
- The frozen campaign observed **zero certificate violations** under the
  independent full-reference oracle.
- Native and Python planner decisions passed parity on **60/60 cases**.
- The selected output matched the independent full-after reference exactly at
  the reported RGB L-infinity precision in these 60 cases; the maximum emitted
  selected certificate bound was **2e-6**.
- **56/60 source edits** exceeded the protected RGB tolerance before repair, so
  the zero selected residual is not explained by a matrix containing only
  visually irrelevant edits.
- The frozen isolated millisecond cost model reports a median selected
  heterogeneous work ratio of approximately **0.36953 of FULL**, equivalent to
  approximately **2.706x lower calibrated work**.
- The public campaign automatically crosses to FULL in high/unstable cases
  rather than forcing a local result.
- The separate sparse-discovery sweep preserves exact candidate selection while
  reducing the number of inspected Gaussians, with median inspection ratio
  **0.01** and minimum inspection ratio **0.001** through the sweep.

## Supported by the trained-3DGS validation

- A pinned public trained 3DGS PLY is validated with SH coefficients, opacity,
  anisotropic scale and rotation preserved.
- The source PLY is pinned by SHA-256:
  `f03e4979ac27345da1422d960d604b98db9541bdb3586d135d64bb4d9bde8eb3`.
- Spatial persistent ownership is deterministic; it is **not semantic
  segmentation**.
- The five-case validation records **4 certified-local selections, 1 automatic
  FULL fallback and zero certificate violations**.
- Its median selected native temporal/output work ratio is approximately
  **0.03495 of FULL**, or about **28.6x lower native work** under that
  single-domain work definition.

## Supported, but only with explicit qualification

- **“2.706x lower work”** is acceptable for the calibrated public work model.
  **“2.706x speedup” is not.**
- **“28.6x lower native work”** is acceptable for the trained-3DGS campaign.
  **“28.6x speedup” is not.**
- **“No violations were observed in the frozen evaluated cases”** is
  acceptable. **“CBRC can never violate tolerance”** is not established by the
  experiments.
- The held-out empirical changed-fraction scheduler had zero observed unsafe
  false-LOCAL decisions on this frozen matrix, but the candidate residual is
  zero across these cases. The result is therefore not evidence that the
  empirical heuristic is a general safety mechanism.
- Some real-matrix ablations are neutral. Their presence must not be described
  as proof that every component is necessary on every workload. The separate
  synthetic mechanism-isolation suite is used only to demonstrate that each
  v1 mechanism has a deterministic falsifying stress case.

## Measured limitations that must remain visible

- Median `gaussiansInspected / FULL` is approximately **1.0** in both frozen
  end-to-end campaign paths. Local updates/publication are much smaller, but
  discovery remains a bottleneck.
- Sparse discovery is demonstrated separately and must not be silently credited
  to the frozen end-to-end campaign.
- The RGB/SfM public scenes use canonical scale normalization; they are not
  metric-scale reconstructions.
- Their Gaussian fields are seeded from real COLMAP SfM points and are not
  trained photorealistic 3DGS. The trained-3DGS campaign is the secondary
  representation check.
- The v1 search is greedy. It returns a certified feasible cone, not a proof of
  global combinatorial minimum work.
- Analytic cycles unsupported by the native v1 implementation fail closed.

## Claims not supported by the current evidence

Do **not** claim any of the following as established results:

- a paired end-to-end wall-clock speedup over FULL;
- global minimum-work optimality;
- universal safety outside the stated assumptions and tested revision domain;
- semantic object-level ownership in the trained-3DGS source;
- metric-scale reconstruction for the public RGB/SfM path;
- that every ablation separates on the real matrix;
- that empirical/learned sensitivity is itself a certificate;
- that the current evidence predicts or guarantees acceptance at SIGGRAPH or
  any other venue.

## Paper-writing rule

Any headline number must be traceable to the canonical machine-readable evidence
snapshot in this directory and to the corresponding GitHub Actions artifact.
If a number cannot be traced to a frozen artifact, it is not a paper result.
