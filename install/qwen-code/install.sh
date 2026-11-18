#!/usr/bin/env bash
# Platform installer for qwen-code
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/../install.sh" --target qwen-code "$@"
