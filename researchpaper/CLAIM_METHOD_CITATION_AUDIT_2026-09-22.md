# MAVEB Claim, Method, Citation, and Evidence Audit — 2026-09-22

This audit records the submission-manuscript consistency check performed against the current repository implementation and the frozen public/trained evidence artifacts.

## Citation integrity

- Manuscript citation keys: 28 unique.
- Bibliography entries: 28.
- Missing cited keys: 0.
- Unused bibliography entries: 0.
- Dataset/reconstruction citations are explicit for COLMAP/SfM, Tanks & Temples, and Deep Blending.
- BundleFusion metadata was corrected to ACM TOG 36(4), Article 24, DOI 10.1145/3072959.3054739.
- Recent/non-obvious related-work entries and the evaluation-source citations were cross-checked against publisher, CVF, project, or arXiv records.

## Frozen quantitative claims

Public v2.1 evidence:
- 60 revisions across 4 scenes.
- 44 certified-local selections and 16 FULL fallbacks.
- 0 observed certificate violations.
- 60/60 native/Python output-cone planner parity.
- 56/60 source edits exceed the protected RGB tolerance before repair.
- Median calibrated four-domain work / FULL = 0.3695301075670818.
- Corresponding calibrated work reduction = 2.7061394444523503x.
- Maximum selected emitted bound = 2e-6.
- Maximum measured selected support-replay residual = 0 at the reported precision.
- Sparse discovery preserves exact candidate selection; median inspected fraction = 0.01, minimum = 0.001, maximum tested scale = 1,000,000 Gaussians.

Trained-3DGS evidence:
- 5 frozen revisions.
- 4 certified-local selections and 1 FULL fallback.
- 0 observed certificate violations.
- Median native temporal/output work / FULL = 0.03494791666666667.
- Corresponding native-work reduction = 28.614008941877792x.
- Median Gaussian inspection / FULL = 0.9999972000873573.
- Median Gaussian update / FULL = 0.018153700271218206.
- Median GPU publication bytes / FULL = 0.018153700271218206.
- Median temporal invalidation / FULL = 0.03494791666666667.

The manuscript values and tables use the same quantities, with only display rounding.

## Method-to-code traceability

- Typed revision graph, exact predecessor closure, sparse analytic DAG propagation, greedy feasible-cone search, and FULL fallback:
  - `engine/revision/src/RevisionPlanner.cpp`
  - `research/cbrc/core.py`
  - `research/cbrc/edges.py`
- Heterogeneous captured-world graph and calibrated work accounting:
  - `engine/cbrc/include/aether/cbrc/CapturedWorldRevisionGraph.hpp`
  - `engine/cbrc/src/CapturedWorldRevisionGraph.cpp`
  - `research/cbrc/work.py`
- Per-domain locality ledger:
  - `engine/world/include/aether/world/LocalityLedger.hpp`
  - `engine/world/src/LocalityLedger.cpp`
- Gaussian finite-edit image certificate:
  - `engine/world_gaussian/src/GaussianImageRevisionCertificate.cpp`
  - `research/cbrc/layer_bounds.py`
- Headless persistent Gaussian revision path:
  - `tools/maveb-cbrc-revision/main.cpp`
- Independent full-after Gaussian oracle and support-replay residual:
  - `tools/maveb-cbrc-gaussian-oracle/main.cpp`
  - `benchmarks/scripts/cbrc_replay.py`
  - `benchmarks/scripts/cbrc_evidence_bundle.py`
- Public campaign, strict evaluator, baselines, ablations, and parity:
  - `benchmarks/scripts/cbrc_campaign.py`
  - `benchmarks/scripts/cbrc_evaluate.py`
  - `research/experiments/cbrc_baseline_suite.py`
- Exact sparse-discovery study:
  - `benchmarks/scripts/cbrc_sparse_discovery_sweep.py`

## Semantic alignment corrections made in this audit

1. The manuscript now describes the independent oracle exactly as implemented: it renders before and full-after states and measures the residual left outside the selected repair support through support replay. It no longer implies that the oracle executes an independently implemented local production pipeline.
2. EMPIRICAL edge semantics now match both C++ and Python: empirical magnitudes may order work, but an empirical-only dependency without an analytic bound fails closed through exact predecessor closure rather than becoming soft certificate evidence.
3. The real campaign scope is stated explicitly. The broader ledger/graph implements observation, TSDF, mesh, texture, material, Gaussian, publication, and temporal domains, while the frozen 60-case and 5-case headline campaigns measure Gaussian inspection/update, GPU publication, and temporal invalidation.
4. The public 2.706x result is labeled as calibrated four-domain work reduction, not wall-clock speedup.
5. Native/Python parity is identified as output-cone planner parity for the frozen campaign.
6. Dataset and reconstruction provenance citations were added.

## Claim boundaries retained

The manuscript does not claim:
- end-to-end wall-clock speedup;
- universal production safety;
- global minimum-work optimality;
- semantic ownership;
- metric-scale public reconstructions;
- that every real-matrix ablation separates;
- that empirical sensitivity is safety evidence;
- or guaranteed venue acceptance.

## Build/structural gates

The manuscript workflow additionally verifies:
- exact Figure 2 SHA-256;
- successful manuscript and supplement compilation;
- no overfull boxes or undefined references under the builder's QA rules;
- expected figure/table/equation counts in the Word export;
- exact Figure 2 bytes in the DOCX media package.

This file is an internal traceability record; the frozen measurement artifacts themselves are not rewritten by this audit.
