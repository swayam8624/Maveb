# Rejected variant: raw Gaussian-field phase as a geometry-only invariant

**Date:** 2026-09-20  
**Probe:** phase-representation-nuisance-v1

## Hypothesis attacked
A local spectral phase signature computed directly from the ordinary anisotropic, opacity-weighted Gaussian density might act as a geometry-preservation invariant.

## Falsification
Keep every Gaussian center fixed. Perturb covariance eigenvalues and opacity only, then compare the phase drift against phase drift caused by actual center edits.

## Result
The raw-field phase nuisance median was **0.2178**, while the tested center-edit median was **0.1655**. Edit-vs-nuisance AUC was **0.4531**.

Therefore the raw field phase is not acting like a geometry-only signal in this probe: representation-parameter changes can move it as much as or more than actual center geometry.

A center-only canonicalized field, where every primitive is replaced by the same isotropic kernel before spectral analysis, is invariant to covariance/opacity perturbations by construction and remains a candidate. That narrower candidate still requires split/merge/resampling and local-neighborhood attacks.

## Decision
**Permanently reject the naïve raw anisotropic opacity-weighted phase formulation as the primary invariant.**

Do not erase this failure. Future phase variants must state exactly which Gaussian attributes are canonicalized and why.
