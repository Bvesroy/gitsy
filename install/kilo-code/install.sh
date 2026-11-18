#!/usr/bin/env bash
# Platform installer for kilo-code
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/../install.sh" --target kilo-code "$@"
