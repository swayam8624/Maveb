#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${MAVEB_PYTHON:-$ROOT/.venv-maveb/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${MAVEB_PYTHON:-python3}"
fi

OUT="${MAVEB_SUBMISSION_FINAL_DIR:-$ROOT/build/submission-final}"
BUILD_DIR="$OUT/manuscript-build"
STATUS="$OUT/SUBMISSION_STATUS.json"
BUNDLE="$OUT/MAVEB_submission_bundle.zip"
REVIEWER_ROOT="${MAVEB_REVIEWER_RESULTS_DIR:-$ROOT/build/reviewer-stress-v2}"
AUDIT="$REVIEWER_ROOT/analysis/REVIEWER_EVIDENCE_AUDIT.json"
VISUALS="$REVIEWER_ROOT/visuals/REVIEWER_VISUALS.json"

mkdir -p "$OUT"

echo "============================================================"
echo "MAVEB submission finalization"
echo "============================================================"
echo "Git SHA            : $(git rev-parse HEAD)"
echo "Reviewer evidence  : $REVIEWER_ROOT"
echo "Final output       : $OUT"
echo

echo "==> [1/4] Resume frozen reviewer-v2 campaign"
bash "$ROOT/run_reviewer_stress_campaign.sh"

echo "==> [2/4] Require frozen reviewer-v2 readiness"
"$PYTHON" - "$AUDIT" "$VISUALS" "$STATUS" "$(git rev-parse HEAD)" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

audit_path = Path(sys.argv[1]).resolve()
visuals_path = Path(sys.argv[2]).resolve()
status_path = Path(sys.argv[3]).resolve()
git_sha = sys.argv[4]

if not audit_path.is_file():
    raise SystemExit(f"missing reviewer audit: {audit_path}")
audit = json.loads(audit_path.read_text(encoding="utf-8"))
visuals = (
    json.loads(visuals_path.read_text(encoding="utf-8"))
    if visuals_path.is_file()
    else {}
)

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

ready = bool(audit.get("reviewerEvidenceReady", False))
payload = {
    "schemaVersion": 1,
    "artifact": "maveb-submission-finalization-status",
    "gitSha": git_sha,
    "submissionReady": False,
    "reviewerEvidenceReady": ready,
    "reviewerAudit": str(audit_path),
    "reviewerAuditSha256": sha256(audit_path),
    "reviewerVisuals": str(visuals_path) if visuals_path.is_file() else None,
    "reviewerVisualsSha256": sha256(visuals_path) if visuals_path.is_file() else None,
    "reviewerSummary": {
        key: audit.get(key)
        for key in (
            "recordCount",
            "localCases",
            "fullFallbackCases",
            "certifiedPartialRepairCases",
            "certifiedNonzeroLocalCases",
            "nearBoundaryLocalCases",
            "toleranceCrossoverGroups",
            "nonzeroLocalDatasets",
            "certificateViolationCount",
            "repairCertificateViolationCount",
        )
    },
    "reviewerReadinessGates": audit.get("readinessGates", {}),
}
status_path.parent.mkdir(parents=True, exist_ok=True)
status_path.write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(json.dumps(payload, indent=2, sort_keys=True))
if not ready:
    raise SystemExit(5)
PY

echo "==> [3/4] Rebuild manuscript with reviewer-v2 state"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
"$PYTHON" researchpaper/build_manuscript.py --build-dir "$BUILD_DIR"

echo "==> [4/4] Hash and package frozen submission artifacts"
"$PYTHON" - "$ROOT" "$OUT" "$STATUS" "$AUDIT" "$VISUALS" "$BUNDLE" <<'PY'
import hashlib
import json
import sys
import zipfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
status_path = Path(sys.argv[3]).resolve()
audit_path = Path(sys.argv[4]).resolve()
visuals_path = Path(sys.argv[5]).resolve()
bundle = Path(sys.argv[6]).resolve()

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

deliverables = [
    root / "researchpaper/MAVEB_manuscript.pdf",
    root / "researchpaper/MAVEB_supplement.pdf",
    root / "researchpaper/MAVEB_manuscript.docx",
    root / "researchpaper/main.tex",
    root / "researchpaper/supplement.tex",
    root / "researchpaper/references.bib",
    root / "researchpaper/generated/reviewer_v2_results.tex",
    root / "researchpaper/generated/reviewer_v2_state.tex",
    root / "researchpaper/generated/reviewer_v2_status.md",
    root / "research/results/CBRC_PAPER_GRADE_EVIDENCE_2026-09-24.json",
    root / "research/results/CBRC_CLAIM_LEDGER_2026-09-24.md",
    audit_path,
]
if visuals_path.is_file():
    deliverables.append(visuals_path)

missing = [str(path) for path in deliverables if not path.is_file()]
if missing:
    raise SystemExit("missing submission artifact(s):\n" + "\n".join(missing))

status = json.loads(status_path.read_text(encoding="utf-8"))
broad_summary_path = root / "research/results/CBRC_PAPER_GRADE_EVIDENCE_2026-09-24.json"
broad_summary = json.loads(broad_summary_path.read_text(encoding="utf-8"))
audit = json.loads(audit_path.read_text(encoding="utf-8"))

final_evidence_path = out / "FINAL_EVIDENCE_SUMMARY.json"
final_evidence = {
    "schemaVersion": 1,
    "artifact": "maveb-final-submission-evidence-summary",
    "submissionGitSha": status["gitSha"],
    "broadEvidence": {
        "source": str(broad_summary_path.relative_to(root)),
        "sha256": sha256(broad_summary_path),
        "evidenceGitSha": broad_summary.get("evidenceGitSha"),
        "overall": broad_summary.get("overall"),
        "byDataset": broad_summary.get("byDataset"),
        "byEditFamily": broad_summary.get("byEditFamily"),
        "byCoupling": broad_summary.get("byCoupling"),
        "interpretationBoundary": broad_summary.get("interpretationBoundary"),
    },
    "reviewerV2": {
        "source": str(audit_path),
        "sha256": sha256(audit_path),
        "reviewerEvidenceReady": bool(audit.get("reviewerEvidenceReady", False)),
        "recordCount": audit.get("recordCount"),
        "localCases": audit.get("localCases"),
        "fullFallbackCases": audit.get("fullFallbackCases"),
        "certifiedPartialRepairCases": audit.get("certifiedPartialRepairCases"),
        "certifiedNonzeroLocalCases": audit.get("certifiedNonzeroLocalCases"),
        "nearBoundaryLocalCases": audit.get("nearBoundaryLocalCases"),
        "toleranceCrossoverGroups": audit.get("toleranceCrossoverGroups"),
        "nonzeroLocalDatasets": audit.get("nonzeroLocalDatasets"),
        "certificateViolationCount": audit.get("certificateViolationCount"),
        "repairCertificateViolationCount": audit.get("repairCertificateViolationCount"),
        "readinessGates": audit.get("readinessGates"),
    },
    "claimBoundary": {
        "work": "Broad headline work/FULL remains calibrated heterogeneous work, not paired wall-clock speedup.",
        "broadFidelity": "Broad selected-to-FULL equality remains revision fidelity on audited views.",
        "reviewerV2": "Reviewer-v2 is a separately frozen partial-repair stress protocol and does not retroactively alter the broad campaign.",
    },
}
final_evidence_path.write_text(
    json.dumps(final_evidence, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

status["submissionReady"] = True
status["finalEvidenceSummary"] = {
    "path": str(final_evidence_path),
    "sha256": sha256(final_evidence_path),
}
deliverables.append(final_evidence_path)
status["deliverables"] = [
    {
        "path": str(path.relative_to(root)) if root in path.parents else str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }
    for path in deliverables
]

bundle.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in deliverables:
        if root in path.parents:
            arcname = str(path.relative_to(root))
        else:
            arcname = "frozen-evidence/" + path.name
        archive.write(path, arcname)
status["bundle"] = {
    "path": str(bundle),
    "bytes": bundle.stat().st_size,
    "sha256": sha256(bundle),
}
status_path.write_text(
    json.dumps(status, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(json.dumps(status, indent=2, sort_keys=True))
PY

echo
echo "============================================================"
echo "MAVEB SUBMISSION PACKAGE READY"
echo "============================================================"
echo "Status : $STATUS"
echo "Bundle : $BUNDLE"
echo
echo "Scientific rule:"
echo "  This script never retunes or filters the frozen reviewer-v2 protocol."
echo "  If a reviewer readiness gate is OPEN it exits non-zero and does not"
echo "  produce a submission-ready bundle."
