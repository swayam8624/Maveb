# MAVEB Research Metric Contracts

**Frozen:** 2026-09-20
These definitions exist before medium/full experiments so later results cannot redefine success post hoc.

## 1. Update Locality Ratio (ULR)

For a revision and a declared work domain D:

[
ULR_D = rac{W_D^{incremental}}{W_D^{full-rebuild}}
]

where work is measured with **explicit counters first**, wall time second.

Required domains:
- observations inspected;
- TSDF samples/blocks read or written;
- mesh cells/patches regenerated;
- Gaussian primitives inspected;
- Gaussian primitives updated;
- texture texels/tiles regenerated;
- CPU→GPU and GPU→CPU bytes transferred;
- GPU buffers/resources rebuilt;
- peak additional memory.

A local method does **not** earn a low ULR merely because its optimization set is small if it still scans/copies the whole world.

## 2. Unchanged World Damage (UWD)

For edit region Ω and protected complement Ωᶜ, report a vector rather than one hidden weighted scalar:

[
UWD = (D_{surface}, D_{normal}, D_{primitive}, D_{render}, D_{identity})
]

Required components where applicable:
- surface point-to-surface / Chamfer drift on Ωᶜ;
- normal angular drift on Ωᶜ;
- canonicalized primitive/neighborhood displacement;
- protected-view LPIPS/SSIM/PSNR change;
- identity switches / false births / false deaths.

The intended edit quality inside Ω is always reported separately. A method cannot improve UWD by refusing to perform the requested edit.

## 3. Representation Churn

For two revisions describing the same or nearly the same underlying geometry:

[
RC = rac{births + deaths + split/merge events + unmatched primitives}{reference primitive mass}
]

Primitive count alone is insufficient. Report churn together with surface/render equivalence.

## 4. Identity Survival

For controlled lineage ground truth:
- survival rate;
- identity switches;
- false births;
- false deaths;
- split parent-recovery;
- merge ancestor-recovery;
- downstream task delta with lineage enabled vs disabled.

No lineage mechanism is publishable from matching accuracy alone; it must improve a downstream edit/change/history metric.

## 5. Certificate Coverage

For a predicted geometry-error bound B(x):

[
coverage(	au)=P(error(x) \le B(x))
]

Report:
- empirical coverage on untouched held-out scenes;
- median and p95 slack (B-error);
- abstention/rejection rate;
- edit success on accepted cases;
- worst violation magnitude.

A trivially huge bound that covers everything is not useful. Tightness and acceptance rate are co-primary.

## 6. Pareto evaluation

For representation/systems work, preserve the raw vector:

[
(quality, frame time, update time, memory, storage, energy)
]

Do not collapse this to one score in primary analysis. Report Pareto dominance and per-budget operating points.

## Required anti-cherry-pick rule

Every experiment configuration declares its primary metrics before execution. Exploratory metrics discovered afterward may be reported but are labelled exploratory.
