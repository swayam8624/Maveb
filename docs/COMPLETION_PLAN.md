# Maveb Completion Plan

This file defines a bounded finish line for Maveb. It intentionally does not treat every open roadmap item as required for the first research release.

## Release target

Ship **Maveb Research Release v0.1** as a reproducible Apple-silicon captured-world research engine that can:

1. ingest a calibrated recorded capture or prepared public benchmark input;
2. reconstruct or load metric proxy geometry and Gaussian content through deterministic, provenance-recorded paths;
3. package the result into the versioned `.aether`/Canonical Asset contracts;
4. open and inspect the world in AetherStudio with the maintained Metal renderer, picking and diagnostics;
5. reproduce the public metric-uncertainty research results without claiming that the failed downstream transfer functions succeeded; and
6. publish build instructions, benchmark evidence, known limitations and immutable research evidence.

The release is **not** blocked on visual odometry, live SLAM, GPU-resident Marching Cubes, material-aware Gaussian relighting, multiresolution streaming, navigation, particles, reflection probes, a cinematic timeline, or a commercial-grade live scanner. Those remain post-v0.1 work.

## Non-negotiable research boundary

The U6b five-room confirmatory set is exposed and closed. The frozen result is negative/null. Do not retune opacity exponent, base opacity, floor, clipping, alpha cutoff, covariance, source/target selection, bootstrap procedure, or gate thresholds on those rooms. Any further efficacy claim requires a newly frozen untouched set.

The final research story is allowed to be negative where the evidence is negative:

- U1a: single-Gaussian residual model rejected.
- U1b: robust Student-t(3) calibration passed and was frozen.
- U2: calibrated uncertainty predicts held-out FARO error.
- U3/U3b: uncertainty-to-TSDF transfer did not produce a robust geometry gain.
- U4a: support-gating transfer did not rescue the downstream geometry claim.
- U5a: covariance enlargement was harmful; U5c identified foreground/occlusion leakage as the dominant mechanism.
- U6a: opacity/visibility transfer was promising on exposed exploratory rooms.
- U6b: prospective confirmation failed the all-clauses gate; the effect was strongly scene-dependent.

## Critical path to v0.1

### C0 — Research closure

- [x] Freeze U6b authorization before first render.
- [x] Execute and freeze the single 120-render U6b confirmatory reveal.
- [x] Preserve negative/null claim policy after U6b failure.
- [ ] Add a read-only U6b heterogeneity audit using only frozen outputs and metadata. It may explain scene dependence; it must not optimize a new transfer rule.
- [ ] Add `docs/research/METRIC_UNCERTAINTY_RESULTS.md` consolidating U1a through U6b, immutable artifact SHAs, claim boundaries, limitations and future hypotheses.
- [ ] Update research issue #15 so the execution ledger matches the repository evidence.
- [ ] Close the metric-uncertainty research track as complete after the audit and consolidated results document are frozen.

Exit gate: a reader can determine exactly what passed, what failed, why the conclusions are valid, and which rooms/outputs are no longer eligible for confirmatory tuning.

### C1 — One real end-to-end captured-world proof

Use one user-owned, releasable capture as the v0.1 physical proof. Prefer the existing MavebCapture + Sony/iPad metric-alignment path if the required paired capture is available; otherwise use a single-device calibrated MavebCapture dataset and state the limitation explicitly.

- [ ] Freeze the capture inputs and licenses/releases before evaluating the result.
- [ ] Validate the capture package and calibrated poses/depth.
- [ ] Run the maintained reconstruction/alignment path without silent fallback.
- [ ] Produce metric proxy geometry and/or Gaussian content with provenance.
- [ ] Package a self-contained Canonical Asset / `.aether` world.
- [ ] Open it in AetherStudio and record a deterministic camera-path capture.
- [ ] Record accuracy, completeness, F-score/geometry metrics where a defensible reference exists; otherwise report only measurable pipeline/runtime evidence and do not invent an accuracy claim.

Exit gate: one documented physical capture travels from source data to a self-contained world that can be opened and inspected in Studio.

### C2 — Renderer and benchmark release gates

- [ ] Select named M1/M2 Gaussian benchmark scenes and freeze their workload hashes.
- [ ] Run the existing synchronized Metal benchmark and record median/p95 GPU time, allocations, Gaussian count, tile-entry counts and overflow counters.
- [ ] Define release budgets from measured supported hardware rather than tiny fixtures.
- [ ] Run the CI preset, sanitizer preset and maintained Metal goldens on the release candidate.
- [ ] Produce `benchmarks/latest-report.md` or an equivalent immutable v0.1 benchmark report.

Exit gate: correctness and performance statements in the README are backed by reproducible reports.

### C3 — Product-surface completion

Only finish the workflow needed to demonstrate the maintained engine truthfully.

- [ ] Make the Studio path obvious: open `.aether` -> inspect mesh/Gaussians -> select diagnostics -> play/capture camera path.
- [ ] Remove or clearly mark controls that point to unimplemented/live-scanner behavior.
- [ ] Ensure project save/load preserves the v0.1 demo state.
- [ ] Add a small first-run sample or documented public sample acquisition path that does not vendor restricted dataset bytes.
- [ ] Verify failure messages for missing Metal toolchain/dependencies/data are actionable.

Exit gate: a new user can build the app, open the reference world and reproduce the documented inspection workflow without reading implementation code.

### C4 — Reproducibility and release package

- [ ] Clean-clone build/test from the release commit.
- [ ] Freeze dependency versions and generate an SBOM/checksum manifest.
- [ ] Publish the research artifact index and benchmark commands.
- [ ] Update README architecture/status language to match v0.1 exactly.
- [ ] Add a release notes document with supported hardware/software, known limitations and intentionally deferred features.
- [ ] Tag `v0.1.0-research` only after all required C0-C4 exit gates pass.
- [ ] If signing credentials are available, notarize/package the macOS app; otherwise publish the source-build release and state that the binary distribution gate remains user-owned.

Exit gate: another developer can clone, build, run the reference workflow, locate the evidence, and understand the limitations.

## Explicitly deferred after v0.1

These may become later projects, but they do not block completion of the research release:

- full visual odometry / live SLAM and relocalization;
- GPU-resident Marching Cubes, eviction and continuous real-time fusion;
- material-aware Gaussian optimization and relighting;
- multiresolution Gaussian clustering, compression and streaming;
- multiple dynamic attachments, navigation, collision, particles and reflection probes;
- full cinematic/editor workflow and signed auto-update productization;
- any new uncertainty-transfer efficacy study on new untouched data.

## Immediate execution order

1. Freeze a U6b read-only heterogeneity audit and consolidated research results document.
2. Bring issue #15 and PR #14 narrative up to the actual frozen U6b outcome, then make the research PR merge-ready.
3. Run one real physical captured-world proof through the existing maintained pipeline.
4. Close named-scene Metal performance and clean-clone reproducibility gates.
5. Polish only the Studio workflow needed for the reference world.
6. Produce the v0.1 evidence bundle, release notes and tag.

When a new task does not directly close one of these gates, defer it unless it fixes a correctness, integrity, security, build or reproducibility defect.
