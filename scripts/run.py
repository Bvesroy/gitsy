#!/usr/bin/env python3
"""gitup launcher - run any gitup script without polluting the skill directory.

Usage (from the skill root):
  python3 scripts/run.py project_scan.py --project ~/Developer/MyProject
  python3 scripts/run.py secret_scan.py  --project . --out audit/security.json
  python3 scripts/run.py --list

Why this exists: importing a module normally makes CPython write a __pycache__
next to it, and skill directories are frequently symlinked, read-only, shared
between agents, or inside a user's dotfiles repo. Running with -P / -I (or
PYTHONPYCACHEPREFIX on older interpreters) keeps the tree pristine. Launching one
extra process costs a few milliseconds and removes an entire class of surprise.
"""

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMP_CACHE = os.path.join(
    os.environ.get("TMPDIR") or "/tmp", "gitup-pycache-%s" % (
        os.getuid() if hasattr(os, "getuid") else "win")
)


def interpreter_flags():
    """Flags that stop bytecode writes without breaking script argv.

    -B is the only reliable one: it stops __pycache__ writes without touching
    sys.path, sys.argv, the environment, or PYTHONPYCACHEPREFIX. -P and -I are
    deliberately avoided; -P removes the script directory from sys.path, which
    would break `import _bootstrap`.
    """
    return ["-B"]


def launch(script: Path, args: list) -> int:
    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = TEMP_CACHE
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTHONPATH", None)

    flags = interpreter_flags()
    cmd = [sys.executable, *flags, str(script), *args]
    # Run from the caller's directory so relative paths (--template, --out,
    # --project) mean what the user typed, not what lives next to run.py.
    return subprocess.call(cmd, env=env, cwd=os.getcwd())


def main() -> int:
    args = sys.argv[1:]
    # Explicit help is success; a bare invocation is misuse. An agent that
    # branches on $? must not read "I forgot the script name" as "all fine".
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if not args:
        sys.stderr.write(
            "usage: python3 scripts/run.py <script.py> [args...]\n"
            "       python3 scripts/run.py --list\n"
            "       python3 scripts/run.py --help\n")
        return 2
    if args[0] in ("--list", "-l"):
        for path in sorted(HERE.glob("*.py")):
            if path.name.startswith("_"):
                continue
            print(path.name)
        return 0
    script = HERE / args[0]
    if not script.exists():
        script = HERE / (args[0] + ".py")
    if not script.exists():
        sys.stderr.write("no such gitup script: %s\n" % args[0])
        return 2
    return launch(script, args[1:])


if __name__ == "__main__":
    sys.exit(main())
