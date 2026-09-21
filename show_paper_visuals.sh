#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ "${1:-}" == "--folders" ]]; then
  open "$ROOT/build/public-real-v2/siggraph-visuals" 2>/dev/null || true
  open "$ROOT/build/public-real-v2/campaign/paper-artifacts" 2>/dev/null || true
  open "$ROOT/build/trained-3dgs-campaign/siggraph-visuals" 2>/dev/null || true
  open "$ROOT/build/paper-grade-final/representation" 2>/dev/null || true
  exit 0
fi

files=(
  "build/public-real-v2/siggraph-visuals/figures/F0_hero.png"
  "build/public-real-v2/siggraph-visuals/figures/F0_system_overview.svg"
  "build/public-real-v2/siggraph-visuals/figures/F9_evidence_dashboard.png"
  "build/public-real-v2/siggraph-visuals/figures/F10_case_mosaic.png"
  "build/public-real-v2/siggraph-visuals/video/MAVEB_teaser.gif"
  "build/public-real-v2/siggraph-visuals/video/MAVEB_supplementary_cases.gif"
  "build/public-real-v2/campaign/paper-artifacts/F1_actual_vs_bound.svg"
  "build/public-real-v2/campaign/paper-artifacts/F2_work_vs_changed_fraction.svg"
  "build/public-real-v2/campaign/paper-artifacts/F3_coupling_cone.svg"
  "build/public-real-v2/campaign/paper-artifacts/F4_fallback_crossover.svg"
  "build/public-real-v2/campaign/paper-artifacts/F5_effectivity.svg"
  "build/public-real-v2/campaign/paper-artifacts/F6_layer_work.svg"
  "build/public-real-v2/campaign/paper-artifacts/F7_cone_support_residual.svg"
  "build/public-real-v2/campaign/paper-artifacts/F8_adversarial_fallback.svg"
  "build/public-real-v2/sparse-discovery/F11_sparse_discovery.svg"
  "build/paper-grade-final/representation/F12_representation_comparison.svg"
  "build/trained-3dgs-campaign/siggraph-visuals/figures/F0_hero.png"
  "build/trained-3dgs-campaign/siggraph-visuals/figures/F9_evidence_dashboard.png"
  "build/trained-3dgs-campaign/siggraph-visuals/figures/F10_case_mosaic.png"
  "build/trained-3dgs-campaign/siggraph-visuals/video/MAVEB_teaser.gif"
)

found=0
missing=0
for relative in "${files[@]}"; do
  if [[ -f "$ROOT/$relative" ]]; then
    printf 'open  %s\n' "$relative"
    open "$ROOT/$relative"
    found=$((found + 1))
  else
    printf 'miss  %s\n' "$relative" >&2
    missing=$((missing + 1))
  fi
done

echo
printf 'Opened %d visualization(s).\n' "$found"
if (( missing > 0 )); then
  printf '%d expected visualization(s) are not present yet.\n' "$missing"
  echo "Generate/regenerate the complete package with:"
  echo "  ./run_paper_grade_research.sh"
fi
