#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${MAVEB_PYTHON:-$ROOT/.venv-maveb/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${MAVEB_PYTHON:-python3}"
fi

BROAD_ROOT="${MAVEB_REVIEWER_SOURCE_ROOT:-$ROOT/build/broad-benchmark-paper}"
BROAD_COMPLETE="$BROAD_ROOT/BROAD_CAMPAIGN_COMPLETE.json"

if [[ ! -f "$BROAD_COMPLETE" ]]; then
  echo "Missing completed paper-grade broad campaign:" >&2
  echo "  $BROAD_COMPLETE" >&2
  echo "Finish/adopt the broad campaign before the final reviewer pass." >&2
  exit 2
fi

echo "============================================================"
echo "MAVEB final reviewer/manuscript pass"
echo "============================================================"
echo "Broad evidence : $BROAD_COMPLETE"
echo "Reviewer root  : ${MAVEB_REVIEWER_RESULTS_DIR:-$ROOT/build/reviewer-stress-v2}"
echo

export MAVEB_REVIEWER_SOURCE_ROOT="$BROAD_ROOT"
export MAVEB_REVIEWER_RESULTS_DIR="${MAVEB_REVIEWER_RESULTS_DIR:-$ROOT/build/reviewer-stress-v2}"
export MAVEB_REVIEWER_REUSE="${MAVEB_REVIEWER_REUSE:-1}"
export MAVEB_REVIEWER_SCENES_PER_DATASET="${MAVEB_REVIEWER_SCENES_PER_DATASET:-1}"
export MAVEB_REQUIRE_COW="${MAVEB_REQUIRE_COW:-1}"
export MAVEB_MIN_FREE_GIB="${MAVEB_MIN_FREE_GIB:-10}"

bash "$ROOT/run_reviewer_stress_campaign.sh"

STATUS="$ROOT/researchpaper/generated/reviewer_v2_status.md"
TEX="$ROOT/researchpaper/generated/reviewer_v2_results.tex"

echo
echo "============================================================"
echo "Reviewer-v2 manuscript status"
echo "============================================================"
if [[ -f "$STATUS" ]]; then
  cat "$STATUS"
else
  echo "Missing generated status: $STATUS" >&2
  exit 3
fi

echo
echo "Generated manuscript bridge:"
echo "  $TEX"

if command -v latexmk >/dev/null 2>&1; then
  echo
  echo "============================================================"
  echo "Compiling researchpaper/main.tex with latexmk"
  echo "============================================================"
  (
    cd "$ROOT/researchpaper"
    latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
  )
  echo "Compiled: $ROOT/researchpaper/main.pdf"
elif command -v pdflatex >/dev/null 2>&1; then
  echo
  echo "latexmk unavailable; compiling with pdflatex/bibtex fallback."
  (
    cd "$ROOT/researchpaper"
    pdflatex -interaction=nonstopmode -halt-on-error main.tex
    bibtex main
    pdflatex -interaction=nonstopmode -halt-on-error main.tex
    pdflatex -interaction=nonstopmode -halt-on-error main.tex
  )
  echo "Compiled: $ROOT/researchpaper/main.pdf"
else
  echo
  echo "TeX compiler not installed; reviewer evidence and manuscript bridge are complete."
  echo "Compile researchpaper/main.tex on a machine with latexmk or pdflatex."
fi

echo
echo "Scientific rule:"
echo "  reviewerEvidenceReady=false is a valid frozen result."
echo "  Do not delete cases, retune epsilon, or hand-edit the generated block to force PASS."
