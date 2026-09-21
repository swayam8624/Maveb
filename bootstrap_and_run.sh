#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${MAVEB_REPO_URL:-https://github.com/swayam8624/Maveb.git}"
TARGET_DIR="${MAVEB_DIR:-Maveb}"
INSTALL_DEPS=0
LAUNCH_STUDIO=0

usage() {
  cat <<'EOF'
MAVEB bootstrap + complete run

Usage:
  ./bootstrap_and_run.sh [--install-deps] [--launch-studio] [--help]

The script can run from inside a MAVEB clone. It can also be downloaded/piped
from the raw GitHub URL; when no clone is present it clones MAVEB first.

Options:
  --install-deps
      Install missing Homebrew packages (cmake, ninja, python) and request the
      Xcode Metal Toolchain when absent. Homebrew itself is never installed
      automatically.

  --launch-studio
      Launch AetherStudio after every validation gate passes.

Environment:
  MAVEB_DIR=/path/or/name
      Clone destination when running outside a repository. Default: Maveb

  MAVEB_CAMPAIGN=/absolute/path/campaign.json
      Optional frozen real captured-world campaign.

  MAVEB_WORK_COST=/absolute/path/frozen-work-cost.json
      Optional frozen work-cost model existence check.

  MAVEB_RESULTS_DIR=/absolute/path/results
      Optional results directory forwarded to run_all.sh.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-deps)
      INSTALL_DEPS=1
      shift
      ;;
    --launch-studio)
      LAUNCH_STUDIO=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

find_existing_repo() {
  local candidate

  candidate="$PWD"
  if [[ -d "$candidate/.git" && -f "$candidate/CMakeLists.txt" ]]; then
    printf '%s\n' "$candidate"
    return 0
  fi

  if [[ -n "${BASH_SOURCE[0]:-}" && -e "${BASH_SOURCE[0]}" ]]; then
    candidate="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
    if [[ -n "$candidate" && -d "$candidate/.git" && -f "$candidate/CMakeLists.txt" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  fi

  return 1
}

ROOT="$(find_existing_repo || true)"
if [[ -z "$ROOT" ]]; then
  command -v git >/dev/null 2>&1 || {
    echo "git is required before MAVEB can be cloned." >&2
    exit 2
  }

  if [[ -e "$TARGET_DIR" && ! -d "$TARGET_DIR/.git" ]]; then
    echo "Clone destination exists but is not a Git repository: $TARGET_DIR" >&2
    exit 2
  fi

  if [[ ! -d "$TARGET_DIR/.git" ]]; then
    echo "==> Cloning MAVEB"
    git clone --recurse-submodules "$REPO_URL" "$TARGET_DIR"
  fi
  ROOT="$(cd "$TARGET_DIR" && pwd)"
fi

cd "$ROOT"

echo "============================================================"
echo "MAVEB bootstrap"
echo "============================================================"
echo "Repository : $ROOT"
echo "Remote     : $REPO_URL"
echo

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "MAVEB's complete native/Metal validation path requires macOS." >&2
  exit 2
fi

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "MAVEB's supported complete path requires Apple Silicon (arm64)." >&2
  exit 2
fi

if ! command -v xcodebuild >/dev/null 2>&1; then
  echo "Xcode command-line tools/Xcode are required." >&2
  exit 2
fi

if (( INSTALL_DEPS )); then
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew is required for --install-deps but is not installed." >&2
    echo "Install Homebrew from https://brew.sh, then rerun this script." >&2
    exit 2
  fi

  for package in cmake ninja python; do
    if ! brew list "$package" >/dev/null 2>&1; then
      echo "==> Installing $package"
      brew install "$package"
    fi
  done

  if ! xcrun -f metal >/dev/null 2>&1; then
    echo "==> Requesting Xcode Metal Toolchain"
    xcodebuild -downloadComponent metalToolchain
  fi
fi

missing=0
for command_name in git cmake ninja python3; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    missing=1
  fi
done
if (( missing )); then
  echo "Rerun with --install-deps or install the missing tools manually." >&2
  exit 2
fi

python3 - "$(cmake --version | awk 'NR==1 {print $3}')" "$(sw_vers -productVersion)" "$(xcodebuild -version | awk 'NR==1 {print $2}')" <<'PY'
import sys

def parts(value):
    out = []
    for token in value.split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)

cmake, macos, xcode = map(parts, sys.argv[1:4])
if cmake < (3, 28):
    raise SystemExit(f"CMake >= 3.28 required, found {sys.argv[1]}")
if macos < (15,):
    raise SystemExit(f"macOS >= 15 required, found {sys.argv[2]}")
if xcode < (26,):
    raise SystemExit(f"Xcode >= 26 required, found {sys.argv[3]}")
PY

echo "==> Synchronizing submodules"
git submodule update --init --recursive

echo "==> Preparing isolated Python environment"
if [[ ! -x .venv-maveb/bin/python ]]; then
  python3 -m venv .venv-maveb
fi
.venv-maveb/bin/python -m pip install --disable-pip-version-check --upgrade pip
.venv-maveb/bin/python -m pip install --disable-pip-version-check numpy pillow scipy

chmod +x run_all.sh
export MAVEB_PYTHON="$ROOT/.venv-maveb/bin/python"

args=()
if (( LAUNCH_STUDIO )); then
  args+=(--launch-studio)
fi

echo "==> Starting complete MAVEB verification"
exec "$ROOT/run_all.sh" "${args[@]}"
