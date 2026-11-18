#!/usr/bin/env bash
# GITSY Standalone CLI Runner (Generic Adapter for any terminal or agent)
# Usage: ./gitsy-runner.sh <project-location> [--apply-watermarks] [--version v0.1.0]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ $# -lt 1 ]; then
  echo "Usage: $0 <project-location> [--apply-watermarks] [--version v0.1.0]" >&2
  exit 1
fi

PROJECT_PATH="$1"
shift

APPLY_WM=0
REL_VERSION="v0.1.0"

while [ $# -gt 0 ]; do
  case "$1" in
    --apply-watermarks) APPLY_WM=1; shift ;;
    --version) REL_VERSION="$2"; shift 2 ;;
    *) shift ;;
  esac
done

OUT_DIR="${TMPDIR:-/tmp}/gitsy_run_$$"
mkdir -p "$OUT_DIR"

echo "==> [1/6] Detecting environment..."
python3 "$SKILL_ROOT/scripts/detect_environment.py" --json > "$OUT_DIR/environment.json"

echo "==> [2/6] Running Phase A & B: Project Discovery & Audit..."
python3 "$SKILL_ROOT/scripts/discover_and_audit.py" "$PROJECT_PATH" --run-tests --output "$OUT_DIR/audit.json" >/dev/null

echo "==> [3/6] Running Phase C: Security & Hygiene Audit..."
python3 "$SKILL_ROOT/scripts/scan_secrets_and_hygiene.py" "$PROJECT_PATH" --fix-gitignore --output "$OUT_DIR/security.json" >/dev/null

if [ "$APPLY_WM" -eq 1 ]; then
  python3 "$SKILL_ROOT/scripts/watermark_audit.py" "$PROJECT_PATH" --apply --output "$OUT_DIR/watermarks.json" >/dev/null
else
  python3 "$SKILL_ROOT/scripts/watermark_audit.py" "$PROJECT_PATH" --output "$OUT_DIR/watermarks.json" >/dev/null
fi

echo "==> [4/6] Running Visual Presentation Engine (SVG Diagrams & Assets)..."
python3 "$SKILL_ROOT/scripts/capture_and_brand.py" "$PROJECT_PATH" --audit-json "$OUT_DIR/audit.json" > "$OUT_DIR/visuals.json"

echo "==> [5/6] Preparing Release Artifacts ($REL_VERSION)..."
python3 "$SKILL_ROOT/scripts/prepare_release.py" "$PROJECT_PATH" --version "$REL_VERSION" > "$OUT_DIR/release.json"

echo "==> [6/6] Running Final Quality Gate..."
python3 "$SKILL_ROOT/scripts/verify_publication.py" "$PROJECT_PATH" --output "$OUT_DIR/verification.json"

echo "GITSY pipeline execution completed. Reports saved in: $OUT_DIR"
