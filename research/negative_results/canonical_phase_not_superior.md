# Negative result: canonical phase is not empirically superior to spatial density

**Date:** 2026-09-20
**Probe:** local-canonical-phase-v3

The raw anisotropic Gaussian-field phase was already rejected because covariance/opacity nuisance overwhelms geometry. This follow-up tested the narrowed, geometry-canonicalized center field.

A deliberately hard deformation was projected into the first-order nullspace of centroid and covariance constraints. This makes simple moments nearly useless while leaving a true non-rigid geometric change.

Results against merge-resampling nuisance:

- normalized density L2 edit-vs-merge AUC: **0.7273**
- canonical phase edit-vs-merge AUC: **0.6968**
- amplitude AUC: **0.7046**
- moment AUC: **0.4727**
- pair-histogram AUC: **0.6819**

Phase therefore survives as a geometry-sensitive signal, but **does not beat the simpler normalized density descriptor** in this hard probe.

## Decision

Do not make "spectral phase is the best geometry invariant" a MAVEB claim.

Phase remains interesting only if it provides an analytical property a direct spatial metric cannot—for example a local Fourier-shift displacement estimate or a conservative edit-disturbance certificate.
