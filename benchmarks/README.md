# MavebBench

MavebBench is the repository's evidence layer for real reconstruction data. Dataset bytes stay
outside Git under `MAVEB_DATA`; committed manifests describe how to locate them. The harness does
not turn missing adapters into fake passes.

## Setup

```bash
export MAVEB_ROOT="$HOME/Desktop/Programming/Maveb"
export MAVEB_DATA="$HOME/Datasets/MavebBench"
export PATH="$MAVEB_ROOT/.aether-deps/bin:$PATH"

cmake --preset debug
cmake --build --preset debug
AETHER_BUILD_COLMAP=1 ./tools/bootstrap-reconstruction.zsh
```

The bootstrap keeps Brush, COLMAP, `aether-proxy`, and their pinned identities under
`.aether-deps/`.

## Commands

```bash
python3 benchmarks/scripts/mavebbench.py doctor
python3 benchmarks/scripts/mavebbench.py list

# Proven RGB baseline: capture validation -> COLMAP -> coverage gate -> proxy -> Brush.
python3 benchmarks/scripts/mavebbench.py run eth3d-pipes --steps 2000 --checkpoint-every 1000

# Video path: ffprobe -> deterministic extraction -> validation -> the same reconstruction path.
python3 benchmarks/scripts/mavebbench.py run uco3d-object --video-fps 2 --steps 2000

# Fast planning without executing external reconstruction.
python3 benchmarks/scripts/mavebbench.py suite smoke --dry-run

python3 benchmarks/scripts/mavebbench.py report --output benchmarks/latest-report.md
```

Generated frames, jobs, logs and reports live under `benchmarks/results/` and are ignored by Git.

## Status semantics

`pass` means the named command actually completed and produced parseable success evidence.
`fail` means an executable or dataset step ran and failed. `blocked` means a required executable is
missing. `adapter-required` is a deliberate engineering gate, currently used for raw ARKitScenes
and DTU ground-truth integration. `reference-only` means the dataset is present but is not currently
a reconstruction input.

## Initial evidence

The first real baseline on Apple Silicon used ETH3D Pipes with the pinned dependency set:

- 14 / 14 images registered.
- 3,154 tracked sparse points.
- Sparse coverage gate passed with full connectivity.
- Proxy generation produced 3,778 vertices and 7,242 triangles.
- Brush produced valid checkpoints and `base-gaussians.ply` at 2,000 smoke-test steps.

Those numbers are a smoke baseline, not a final quality claim. They should be regenerated locally
rather than copied into future benchmark reports.

## Dataset policy

Dataset licenses are independent of the Apache-2.0 source license. MavebBench never vendors the
downloaded datasets. Keep commercial/publication usage consistent with each dataset's original
terms.
