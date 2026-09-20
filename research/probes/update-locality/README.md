# Update-locality cheap probe

This probe exercises Maveb's real `Reality Diff -> SelectiveUpdatePlan -> GaussianLocalUpdateSelection` path on a controlled synthetic world.

It exists to falsify H5 before building a larger dependency-graph architecture.

## Sweep

The fixture contains 100 stable entities laid out on a 10x10 metric grid with four owned Gaussian primitives per entity. It sweeps:

- changed entity fractions: 1%, 2%, 5%, 10%, 25%, 50%, 100%
- clustered versus spatially scattered changes
- selective-update cell sizes: 0.25 m, 0.5 m, 1.0 m
- halo sizes: 0, 1, 2 cells

Each changed entity translates by 0.12 m while unchanged entities remain byte-for-byte stable at the entity level.

## Run

```bash
./build/debug/tools/maveb-update-locality-probe/maveb-update-locality-probe \
  > research/results/probes/update-locality-baseline.json
```

## Measurements

- `dirtyRegions`
- `selectedGaussians / totalGaussians`
- `gaussianUpdateLocalityRatio`
- stable owned Gaussians rejected/protected inside dirty spatial cells
- unaffected Gaussian count

For the Gaussian stage, the baseline locality ratio is:

```
ULR_gaussian = selected_gaussians / total_gaussians
```

This is only one component of the eventual cross-representation Update Locality Ratio. Surviving H5 work must later account for TSDF blocks, mesh cells, bytes rewritten, optimization pixels and GPU work, and must compare final quality against a full rebuild.

## Falsification

H5 is weakened if small changed-world fractions still cause a near-global Gaussian selection across reasonable cell/halo settings, or if locality only improves by settings that damage reconstruction quality in later real-data tests.

H5 is strengthened only if measured work scales substantially below full rebuild while final reconstruction quality remains near the full-rebuild oracle.
