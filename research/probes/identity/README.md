# Persistent identity cheap probe

This probe exercises the real `Aether::World` association and ingest paths. It is diagnostic research infrastructure, not evidence of a publishable claim.

## Questions

1. When two same-class physical entities approach, cross, or become geometrically ambiguous, when does the current greedy association baseline switch identity?
2. Does observation ordering affect an ambiguous match?
3. Do deterministic geometry/appearance signatures protect identity?
4. What happens when a valid persistent entity is temporarily absent from one observation revision and later reappears?
5. How does explicit upstream identity differ from purely heuristic re-association?

## Run

```bash
./build/debug/tools/maveb-identity-probe/maveb-identity-probe > research/results/probes/identity-baseline.json
```

The output is one machine-readable JSON document. It contains a controlled crossing sweep and a dropout/reappearance experiment.

## Metrics

- `identitySurvivalRate`: correctly preserved physical IDs / 2 in the controlled crossing fixture.
- `identitySwitches`: physical entities assigned the other fixture entity's prior ID.
- `falseBirths`: fixture entities assigned a fresh ID where persistence was expected.
- `identityPreserved` in the reappearance probe: whether the returning physical entity recovered its original stable ID.

The probe deliberately does not fail the build when the baseline performs poorly. A negative result is the point. Any improved association/evidence mechanism must later run the same fixture plus harder public/real revision data.

## Research boundary

Dynamic 3D Gaussians and LTGS already establish forms of temporal persistence. Therefore a positive Maveb result cannot be "persistent identity exists." The useful question is whether identity across intermittent recapture/reconstruction churn can be maintained and whether that persistence causes measurable improvements in unchanged-world preservation or update locality.
