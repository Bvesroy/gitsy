"""Import shim for every gitup script.

    import _bootstrap  # noqa: F401  (must be the first import)

Two jobs:
  1. put scripts/lib on sys.path so `import gitup_common` works regardless of cwd;
  2. redirect bytecode caches to a temp dir so nothing is written into the skill
     directory (it may be a symlinked, shared, or read-only install).

It also refuses obviously-broken interpreters with a clear message instead of the
cryptic SyntaxError an older python3 would raise on `X | None` annotations.
"""

import os
import sys
import tempfile

if sys.version_info < (3, 9):  # pragma: no cover - environment guard
    sys.exit(
        "gitup requires Python 3.9 or newer (found %d.%d). "
        "On macOS run it with: uv run --python 3.11 scripts/<script>.py"
        % sys.version_info[:2]
    )

sys.pycache_prefix = os.path.join(
    tempfile.gettempdir(), "gitup-pycache-%d" % os.getuid()
) if hasattr(os, "getuid") else os.path.join(tempfile.gettempdir(), "gitup-pycache")

_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
