# Maveb v0.1 Reference World v1

- Tracking issue: #23
- Release tracker: #22
- Status: acquisition not yet frozen
- Purpose: one real, traceable end-to-end captured-world proof for `v0.1.0-research`
- Research boundary: engineering/reproducibility evidence only; this is not a new metric-uncertainty efficacy study

## Exit claim

Reference World v1 may support this claim only after every required gate below passes:

> A real physical scene can be recorded through Maveb's maintained metric capture path, reconstructed into traceable metric proxy/appearance representations, packaged as a Canonical Asset / `.aether` scene, and inspected in AetherStudio with reproducible provenance.

It does not establish live SLAM, production-grade photogrammetry, general reconstruction accuracy, or a new uncertainty result.

## Immutable boundaries

1. The former placeholder live scanner is not an accepted acquisition source.
2. The metric source must be a real, finalized `.mavebcapture` containing RGB, metric depth/confidence, calibrated intrinsics and camera-to-world poses.
3. Synthetic fallback is forbidden.
4. Raw capture bytes may remain outside Git, but their immutable manifest/hash and acquisition metadata must be recorded before reconstruction-quality iteration.
5. A failed/corrupt acquisition may be rejected before downstream quality inspection. Once a valid capture is frozen as Reference World v1, scene replacement for cosmetic result selection requires explicitly abandoning v1 and starting a separately named v2.
6. Reconstruction/configuration changes after v1 acquisition are allowed only as ordinary engineering fixes and must remain visible in Git history and evidence. They are not scientific efficacy tuning.
7. If separate RGB-camera imagery is used, it must be frozen independently and aligned through the maintained robust sensor-alignment path rather than manual transform adjustment.
8. `tests/fixtures/textured.aetherproject` is unrelated local state and must never be staged as part of this track.

## Scene-selection rule

Before capture, choose one scene that is:

- user-owned or clearly releasable;
- static for the full capture;
- textured enough for feature matching;
- geometrically non-trivial, with foreground/background depth variation;
- includes at least one occlusion boundary;
- bounded enough for a deliberate walk-around capture;
- free of private documents/screens or identifiable bystanders that would prevent publication.

Do not select the scene based on U6b/U6c behavior.

## Local workspace

Keep heavy/raw bytes outside the repository. Recommended shell variable:

```bash
export MAVEB_REFERENCE_WORLD="$HOME/Datasets/MavebReferenceWorld/v1"
mkdir -p "$MAVEB_REFERENCE_WORLD"
```

Suggested external layout:

```text
$MAVEB_REFERENCE_WORLD/
  acquisition/
    reference.mavebcapture/
    rgb/                  # optional separate RGB source
  derived/
    proxy.ply
    reconstruction/
    metric-camera-rig.json
    base-gaussians.ply
    canonical-scene/
    reference-world.aether
  logs/
```

No path in this document is evidence until the corresponding real bytes exist and their hashes are frozen.

## C1.0 — main/toolchain preflight

Starting point is the merged C0 research closure:

`16b660aa4420477095e663db29753f81c31f810d`

Run from a clean index while preserving unrelated unstaged local files:

```bash
cmake --preset debug
cmake --build --preset debug
ctest --preset debug
```

Expected maintained tools for this track:

- `build/debug/tools/aether-capture/aether-capture`
- `build/debug/tools/aether-keyframes/aether-keyframes`
- `build/debug/tools/aether-reconstruct/aether-reconstruct`
- `build/debug/tools/aether-fuse/aether-fuse`
- `.aether-deps/bin/aether-proxy` after `tools/bootstrap-reconstruction.zsh` installs the pinned Python 3.12/Open3D environment
- `build/debug/tools/aether-export-glb/aether-export-glb`
- `build/debug/tools/aether-pack/aether-pack`
- `build/debug/tools/aether-inspect/aether-inspect`
- `build/debug/tools/maveb-align-sensors/maveb-align-sensors`
- `build/debug/apps/AetherStudio/AetherStudio.app`

`aether-proxy` is a Python console script from `tools/aether-proxy/pyproject.toml`, not a CMake-built executable. Its maintained pinned installation is created by `tools/bootstrap-reconstruction.zsh` under `.aether-deps/bin/`.

Record tool versions and the exact Maveb commit in the evidence manifest; do not infer them later.

## C1.1 — acquire and freeze the metric capture

Build/run `MavebCapture` on a real LiDAR-capable device according to `apps/MavebCapture/README.md`.

The finalized package must retain:

- camera planes;
- metric scene depth;
- uint8 confidence where available;
- image/depth intrinsics;
- camera-to-world transforms;
- tracking state;
- AR and monotonic host timestamps;
- exposure metadata;
- frame journal/manifest hashes.

After exporting the real package to the Mac:

1. copy it into `$MAVEB_REFERENCE_WORLD/acquisition/`;
2. do not edit files inside the package;
3. record the package/manifest identity and a recursive file manifest;
4. create the repository acquisition evidence record before looking at reconstruction-quality results.

Planned repository evidence path:

`benchmarks/evidence/reference-world-v1-acquisition.json`

That file does **not** exist yet and must not be created with placeholder hashes.

## C1.2 — validate before reconstruction

The capture must pass structural and geometry preflight before any quality iteration.

Validation must establish at minimum:

- manifest/journal consistency;
- expected plane files and byte counts;
- finite metric depth;
- confidence range validity;
- intrinsics matching declared resolutions;
- finite rigid camera-to-world transforms;
- usable tracking state;
- non-zero accepted frame count;
- bounded filtered/dropped counts with reasons retained.

If the acquisition is corrupt, reject it here rather than compensating downstream.

## C1.3 — deterministic metric proxy

The first geometric product is the recorded RGB-D oracle path, not RGB photogrammetry.

Baseline command shape:

```bash
build/debug/tools/aether-fuse/aether-fuse \
  "$MAVEB_REFERENCE_WORLD/acquisition/reference.mavebcapture" \
  --output "$MAVEB_REFERENCE_WORLD/derived/proxy.ply" \
  --voxel 0.01 \
  --truncation 0.04 \
  --json
```

Origin/dimensions may be established by a documented preflight if required. Do not repeatedly alter bounds based on prettier outputs without recording why.

Freeze:

- fusion command/configuration;
- input acquisition hash;
- output proxy SHA-256;
- vertex/triangle counts;
- runtime/diagnostic counters exposed by the maintained tool.

## C1.4 — appearance and Gaussian path

A flagship world should contain an appearance representation in addition to the metric proxy.

Two acceptable source paths:

### Path A — capture RGB

Use RGB/keyframes extracted from the frozen metric capture if the maintained adapter supports sufficient reconstruction quality.

### Path B — separately frozen RGB camera

Freeze the complete image set before evaluating reconstruction quality. Run the maintained COLMAP/reconstruction adapter, then robustly align COLMAP cameras into the metric capture frame with `maveb-align-sensors`.

Manual scene transforms are not accepted alignment evidence.

Expected orchestration shape:

```bash
build/debug/tools/aether-keyframes/aether-keyframes <frames> \
  --output <keyframes> --json

build/debug/tools/aether-reconstruct/aether-reconstruct <dataset> \
  --output <reconstruction-job> --trainer brush --seed 42 --json
```

If separate-camera alignment is required:

```bash
build/debug/tools/maveb-align-sensors/maveb-align-sensors \
  <colmap/sparse/0> <reference.mavebcapture> \
  --matches <camera-matches.json> \
  --output <metric-camera-rig.json> --json
```

Freeze reconstruction and alignment commands, versions, hashes, inlier/residual evidence and final `base-gaussians.ply` identity. If the maintained trainer is unavailable or fails, record that failure and repair the maintained path rather than substituting an untracked export.

## C1.5 — Canonical Asset v1

The final unpacked scene must conform to `docs/formats/CANONICAL_ASSET.md`:

```text
canonical-scene/
  metadata.json
  canonical-asset.json
  canonical.glb
  cameras.json
  confidence.bin       # when per-vertex confidence is used
  proxy.ply            # expected for Reference World v1
  base-gaussians.ply   # expected for flagship Gaussian presentation
```

Required semantics:

- right-handed;
- Y-up;
- metres (`metersPerUnit = 1.0`);
- camera forward `-Z` in the canonical packaged frame;
- embedded GLB buffers/images;
- calibrated camera identities/intrinsics/poses;
- explicit confidence semantics;
- geometry/appearance provider names, versions, input hashes and configuration hashes.

Proxy and Gaussian representations must remain semantically distinct.

## C1.6 — pack and inspect

```bash
build/debug/tools/aether-pack/aether-pack \
  "$MAVEB_REFERENCE_WORLD/derived/canonical-scene" \
  --output "$MAVEB_REFERENCE_WORLD/derived/reference-world.aether" \
  --json

build/debug/tools/aether-inspect/aether-inspect \
  "$MAVEB_REFERENCE_WORLD/derived/reference-world.aether" \
  --json
```

Freeze:

- final `.aether` SHA-256;
- inspector JSON;
- expected asset/chunk identities;
- deterministic repack result where promised by the format contract.

## C1.7 — Studio proof

Open the real package:

```bash
open build/debug/apps/AetherStudio/AetherStudio.app
```

Required observed workflow:

1. load the real `reference-world.aether`;
2. navigate the scene;
3. display Gaussian representation when present;
4. display proxy/hybrid representation;
5. exercise source-ID picking where applicable;
6. exercise depth/ID/occupancy/opacity diagnostics where applicable;
7. save project/session state;
8. close and reopen;
9. verify scene state restores correctly;
10. record screenshots/video as release evidence.

A screenshot alone is not sufficient; the package/provenance chain remains the primary evidence.

## C1.8 — final evidence record

Planned path:

`benchmarks/evidence/reference-world-v1-result.json`

It must be generated only after the real acquisition exists and must record:

- source ownership/release statement;
- Maveb commit SHA;
- acquisition manifest/hash;
- external tool versions;
- all relevant commands/configuration;
- proxy/canonical/Gaussian hashes;
- sensor alignment evidence if used;
- package hash/inspection result;
- geometry/runtime summary;
- Studio proof references;
- limitations/failures;
- explicit `syntheticFallbackUsed: false`.

## Definition of done

C1 passes only when the repository can trace:

`physical scene -> immutable real capture -> validated poses/depth -> maintained reconstruction -> Canonical Asset -> .aether -> AetherStudio`

with no fabricated metadata, synthetic substitution, silent manual alignment, or untracked intermediate replacement.
