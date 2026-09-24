#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Fast research iteration preset. This never replaces the publication-scale campaign;
# it exists to catch implementation/regression problems in minutes rather than hours.
export MAVEB_BROAD_RESULTS_DIR="${MAVEB_BROAD_RESULTS_DIR:-$ROOT/build/broad-benchmark-fast}"
export MAVEB_BROAD_MAX_IMAGES="${MAVEB_BROAD_MAX_IMAGES:-32}"
export MAVEB_BROAD_CASES_PER_SCENE="${MAVEB_BROAD_CASES_PER_SCENE:-3}"
export MAVEB_BROAD_BOOTSTRAP_ITERATIONS="${MAVEB_BROAD_BOOTSTRAP_ITERATIONS:-300}"
export MAVEB_BROAD_SCENE_WORKERS="${MAVEB_BROAD_SCENE_WORKERS:-3}"
export MAVEB_BROAD_CASE_WORKERS="${MAVEB_BROAD_CASE_WORKERS:-4}"
export MAVEB_BROAD_BUILD_PRESET="${MAVEB_BROAD_BUILD_PRESET:-research}"
export MAVEB_ORACLE_BACKEND="${MAVEB_ORACLE_BACKEND:-auto}"
export MAVEB_BROAD_REUSE="${MAVEB_BROAD_REUSE:-1}"
export MAVEB_BROAD_ALLOW_PARTIAL="${MAVEB_BROAD_ALLOW_PARTIAL:-1}"
export MAVEB_BROAD_REUSE_PREPARED_WORLDS="${MAVEB_BROAD_REUSE_PREPARED_WORLDS:-1}"
export MAVEB_BROAD_PREPARED_WORLD_CANDIDATES="${MAVEB_BROAD_PREPARED_WORLD_CANDIDATES:-$ROOT/build/broad-benchmark-paper/worlds/BROAD_WORLDS.json:$ROOT/build/broad-benchmark-smoke/worlds/BROAD_WORLDS.json:$ROOT/build/broad-benchmark/worlds/BROAD_WORLDS.json}"
export MAVEB_PROGRESS="${MAVEB_PROGRESS:-1}"

exec "$ROOT/run_broad_benchmark_campaign.sh" "$@"
