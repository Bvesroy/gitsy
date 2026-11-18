#!/usr/bin/env bash
# Universal Installer for the GITSY Agent Skill
# Supports: --target all|opencode|claude-code|gemini-cli|qwen-code|kilo-code|generic
#           --scope global|project (default: global)
#           --dest-root <path> (optional custom root directory for testing/sandboxes)

set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_SRC="$(cd "$INSTALL_DIR/.." && pwd)"

TARGET="all"
SCOPE="global"
DEST_ROOT="$HOME"

while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET="$2"; shift 2 ;;
    --scope) SCOPE="$2"; shift 2 ;;
    --dest-root) DEST_ROOT="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

copy_skill_tree() {
  local dest="$1"
  mkdir -p "$dest"
  local abs_dest
  abs_dest="$(cd "$dest" 2>/dev/null && pwd || true)"
  local abs_src
  abs_src="$(cd "$SKILL_SRC" && pwd)"
  if [ "$abs_dest" != "$abs_src" ]; then
    cp -R "$SKILL_SRC/SKILL.md" "$SKILL_SRC/README.md" "$SKILL_SRC/LICENSE" \
          "$SKILL_SRC/scripts" "$SKILL_SRC/templates" "$SKILL_SRC/references" \
          "$SKILL_SRC/adapters" "$dest/"
  fi
  echo "  [+] Installed GITSY skill bundle -> $dest"
}

install_universal_standard() {
  local base="$1"
  copy_skill_tree "$base/.agents/skills/gitsy"
}

install_claude_code() {
  local base="$1"
  copy_skill_tree "$base/.claude/skills/gitsy"
  mkdir -p "$base/.claude/commands"
  cp "$SKILL_SRC/adapters/claude-code/gitsy.md" "$base/.claude/commands/gitsy.md"
  echo "  [+] Installed Claude Code slash command -> $base/.claude/commands/gitsy.md"
}

install_gemini_cli() {
  local base="$1"
  copy_skill_tree "$base/.gemini/skills/gitsy"
  mkdir -p "$base/.gemini/commands"
  cp "$SKILL_SRC/adapters/gemini-cli/gitsy.toml" "$base/.gemini/commands/gitsy.toml"
  echo "  [+] Installed Gemini CLI custom command -> $base/.gemini/commands/gitsy.toml"
}

install_opencode() {
  local base="$1"
  copy_skill_tree "$base/.opencode/skills/gitsy"
  mkdir -p "$base/.opencode/commands"
  cp "$SKILL_SRC/adapters/opencode/gitsy.md" "$base/.opencode/commands/gitsy.md"
  echo "  [+] Installed OpenCode slash command -> $base/.opencode/commands/gitsy.md"
}

install_qwen_code() {
  local base="$1"
  copy_skill_tree "$base/.qwen/skills/gitsy"
  mkdir -p "$base/.qwen/commands"
  cp "$SKILL_SRC/adapters/qwen-code/gitsy.md" "$base/.qwen/commands/gitsy.md"
  echo "  [+] Installed Qwen Code slash command -> $base/.qwen/commands/gitsy.md"
}

install_kilo_code() {
  local base="$1"
  copy_skill_tree "$base/.kilo/skills/gitsy"
  mkdir -p "$base/.kilo/commands"
  cp "$SKILL_SRC/adapters/kilo-code/gitsy.md" "$base/.kilo/commands/gitsy.md"
  if [ "$SCOPE" = "global" ]; then
    mkdir -p "$base/.config/kilo/commands"
    cp "$SKILL_SRC/adapters/kilo-code/gitsy.md" "$base/.config/kilo/commands/gitsy.md"
  fi
  echo "  [+] Installed Kilo Code skill & workflow -> $base/.kilo/commands/gitsy.md"
}

if [ "$SCOPE" = "project" ] && [ "$DEST_ROOT" = "$HOME" ]; then
  DEST_ROOT="$(pwd)"
fi

echo "Installing GITSY (target=$TARGET, scope=$SCOPE, root=$DEST_ROOT)..."
install_universal_standard "$DEST_ROOT"

case "$TARGET" in
  all)
    install_claude_code "$DEST_ROOT"
    install_gemini_cli "$DEST_ROOT"
    install_opencode "$DEST_ROOT"
    install_qwen_code "$DEST_ROOT"
    install_kilo_code "$DEST_ROOT"
    ;;
  claude-code) install_claude_code "$DEST_ROOT" ;;
  gemini-cli)  install_gemini_cli "$DEST_ROOT" ;;
  opencode)    install_opencode "$DEST_ROOT" ;;
  qwen-code)   install_qwen_code "$DEST_ROOT" ;;
  kilo-code)   install_kilo_code "$DEST_ROOT" ;;
  generic)     echo "  [+] Generic standard installed under $DEST_ROOT/.agents/skills/gitsy" ;;
  *) echo "Unsupported target: $TARGET" >&2; exit 1 ;;
esac

echo "GITSY installation complete. Invoke with: /gitsy <project-location>"
