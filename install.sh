#!/usr/bin/env bash
# Install herdr-spec-drafter: link the command, create a config if missing, check requirements.
# Usage: ./install.sh [BIN_DIR]     (default: $HSD_BIN_DIR or ~/.local/bin)
# Safe to re-run: it never overwrites your config or an unrelated file.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${1:-${HSD_BIN_DIR:-$HOME/.local/bin}}"
CONFIG_DIR="$HOME/.config/herdr-spec-drafter"  # where the tool looks by default
TARGET="$REPO_DIR/bin/herdr-spec-drafter"
LINK="$BIN_DIR/herdr-spec-drafter"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$*"; }

echo "Command"
chmod +x "$TARGET"
mkdir -p "$BIN_DIR"
if [ -L "$LINK" ] && [ "$(readlink "$LINK")" = "$TARGET" ]; then
  ok "already linked: $LINK"
elif [ -e "$LINK" ] || [ -L "$LINK" ]; then
  fail "$LINK already exists and is not this repo's command; leaving it alone"
  exit 1
else
  ln -s "$TARGET" "$LINK"
  ok "linked $LINK -> $TARGET"
fi
case ":$PATH:" in
  *":$BIN_DIR:"*) ok "$BIN_DIR is on your PATH" ;;
  *) warn "$BIN_DIR is not on your PATH; add this to your shell profile:"
     echo "      export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac

echo "Config"
if [ -f "$CONFIG_DIR/config.json" ]; then
  ok "keeping your existing $CONFIG_DIR/config.json"
else
  mkdir -p "$CONFIG_DIR"
  cp "$REPO_DIR/config.example.json" "$CONFIG_DIR/config.json"
  ok "created $CONFIG_DIR/config.json"
  warn "edit it: at least workspace_root (the folder holding your repos)"
fi

echo "Requirements"
missing=0
for cmd in python3 claude hc herdr-app git; do
  if command -v "$cmd" >/dev/null 2>&1; then ok "$cmd"; else fail "$cmd not found"; missing=1; fi
done
if command -v python3 >/dev/null 2>&1 &&
   ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
  fail "python3 is older than 3.9"; missing=1
fi

echo "Linear"
if [ -n "${LINEAR_API_KEY:-}" ] || [ -s "$CONFIG_DIR/linear-api-key" ]; then
  ok "API key found"
else
  warn "no API key; it will fall back to asking Claude (slower, less exact)."
  echo "      Create a read-only personal key in Linear (Settings > Account > Security & access),"
  if command -v pbpaste >/dev/null 2>&1; then
    echo "      copy it, then:  pbpaste > $CONFIG_DIR/linear-api-key && chmod 600 $CONFIG_DIR/linear-api-key"
  else
    echo "      save it in $CONFIG_DIR/linear-api-key, then:  chmod 600 $CONFIG_DIR/linear-api-key"
  fi
fi

echo
if [ "$missing" -ne 0 ]; then
  fail "install finished, but some requirements are missing (see above)"
  exit 1
fi
echo "Done. Try:  herdr-spec-drafter once --dry-run"
