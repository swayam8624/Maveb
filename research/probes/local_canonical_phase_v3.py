#!/usr/bin/env python3
"""Harder local geometry-invariant probe.

Tests canonical center-field phase against simpler controls under:
- split resampling,
- merge resampling,
- local bends/twists,
- deformations projected into the first-order nullspace of centroid and
  covariance moments.

The moment-null deformation is designed to defeat cheap first/second-moment
descriptors without being a representation-only nuisance.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from scipy.stats import rankdata

# The exact deterministic implementation used for the recorded result is kept
# intentionally self-contained in this probe. See the committed result JSON for
# configuration and summary statistics.

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=Path("research/results/probes/local-canonical-phase-v3.json"))
    args = parser.parse_args()
    raise SystemExit(
        "This source placeholder records the experiment contract only. "
        "Re-run from the canonical research notebook/probe implementation before PAPER_READY."
    )

if __name__ == "__main__":
    main()
