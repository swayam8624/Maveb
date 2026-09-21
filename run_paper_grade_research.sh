#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${MAVEB_PYTHON:-$ROOT/.venv-maveb/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${MAVEB_PYTHON:-python3}"
fi

echo "============================================================"
echo "MAVEB complete paper-grade research execution"
echo "============================================================"
echo "Git SHA: $(git rev-parse HEAD)"
echo

echo "==> [A] Large public RGB/SfM campaign + calibration + visuals"
"$ROOT/run_public_real_campaign_v2.sh"

echo "==> [B] Public trained-3DGS validation + visuals"
"$ROOT/run_trained_3dgs_campaign.sh"

echo "==> [C] Cross-representation coverage figure"
COMPARE="$ROOT/build/paper-grade-final/representation"
mkdir -p "$COMPARE"
"$PYTHON" research/visualization/cbrc_representation_comparison.py   --sfm-answer "$ROOT/build/public-real-v2/campaign/REAL_CAMPAIGN_ANSWER.json"   --trained-answer "$ROOT/build/trained-3dgs-campaign/campaign/REAL_CAMPAIGN_ANSWER.json"   --output-dir "$COMPARE"

echo "==> [D] Final evidence readiness audit including trained 3DGS"
FINAL="$ROOT/build/paper-grade-final"
mkdir -p "$FINAL"
"$PYTHON" research/analysis/cbrc_paper_readiness.py   --campaign-dir "$ROOT/build/public-real-v2/campaign"   --calibration "$ROOT/build/public-real-v2/calibration/work-cost-model.json"   --sparse-summary "$ROOT/build/public-real-v2/sparse-discovery/sparse-discovery-summary.json"   --empirical "$ROOT/build/public-real-v2/campaign/empirical-heldout.json"   --visual-package "$ROOT/build/public-real-v2/siggraph-visuals/VISUAL_PACKAGE.json"   --trained-status "$ROOT/build/trained-3dgs-campaign/TRAINED_3DGS_STATUS.json"   --output "$FINAL/PAPER_GRADE_STATUS.json"

cat <<EOF

============================================================
MAVEB PAPER-GRADE RESEARCH PACKAGE COMPLETE
============================================================
Core v2 evidence : build/public-real-v2/campaign/
Calibration      : build/public-real-v2/calibration/
Sparse scaling   : build/public-real-v2/sparse-discovery/
SIGGRAPH visuals : build/public-real-v2/siggraph-visuals/
Trained 3DGS     : build/trained-3dgs-campaign/
Representation   : build/paper-grade-final/representation/
Final audit      : build/paper-grade-final/PAPER_GRADE_STATUS.json

This completion message means the scripted evidence gates passed. It does not
predict or guarantee acceptance by SIGGRAPH or any other venue.
EOF
