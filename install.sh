#!/usr/bin/env bash
# Install herdr-spec-drafter.
#
#   curl -fsSL https://raw.githubusercontent.com/Kapital-B/herdr-spec-drafter/main/install.sh | bash
#   curl -fsSL .../install.sh | bash -s -- --version v0.1.0      # a specific release
#   ./install.sh                                                 # from a git clone
#
# Options:
#   --version REF   release tag or branch to install (default: latest release, else main)
#   --bin-dir DIR   where to link the command (default: ~/.local/bin)
#
# Piped from curl, it downloads the tool to ~/.local/share/herdr-spec-drafter
# (replacing an earlier download). Run from a clone, it links that clone instead.
# Either way it links the command, creates a config if you have none, and checks
# requirements. It never overwrites your config. Safe to re-run; re-running is
# how you update.

set -euo pipefail

REPO="${HSD_REPO:-Kapital-B/herdr-spec-drafter}"
INSTALL_DIR="${HSD_INSTALL_DIR:-$HOME/.local/share/herdr-spec-drafter}"
CONFIG_DIR="$HOME/.config/herdr-spec-drafter"  # where the tool looks by default
TMP_DIR=""

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$*"; }
die()  { fail "$*"; exit 1; }

# The checkout this script lives in, or nothing when it was piped in.
script_checkout() {
  local src="${BASH_SOURCE[0]:-}"
  [ -n "$src" ] && [ -f "$src" ] || return 0
  local dir
  dir="$(cd "$(dirname "$src")" && pwd)"
  [ -f "$dir/bin/herdr-spec-drafter" ] && [ -d "$dir/spec_drafter" ] && echo "$dir"
  return 0
}

latest_release() {
  curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null |
    sed -n 's/^ *"tag_name": *"\([^"]*\)".*/\1/p' | head -1
}

download() {
  local version="$1"
  echo "Download"
  command -v curl >/dev/null 2>&1 || die "curl is required"
  command -v tar >/dev/null 2>&1 || die "tar is required"
  if [ -z "$version" ]; then
    version="$(latest_release || true)"
    [ -n "$version" ] || version="main"
  fi
  if [ -d "$INSTALL_DIR/.git" ]; then
    die "$INSTALL_DIR is a git clone; update it with git pull and run its ./install.sh"
  fi

  local url="${HSD_ARCHIVE_URL:-https://github.com/$REPO/archive/$version.tar.gz}"
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "${TMP_DIR:-}"' EXIT
  local tmp="$TMP_DIR"
  curl -fsSL "$url" -o "$tmp/src.tar.gz" || die "could not download $url"
  mkdir "$tmp/src"
  tar -xzf "$tmp/src.tar.gz" -C "$tmp/src" --strip-components 1
  [ -f "$tmp/src/bin/herdr-spec-drafter" ] || die "download doesn't look like herdr-spec-drafter"
  echo "$version" > "$tmp/src/VERSION"

  mkdir -p "$(dirname "$INSTALL_DIR")"
  rm -rf "$INSTALL_DIR.old"
  [ -e "$INSTALL_DIR" ] && mv "$INSTALL_DIR" "$INSTALL_DIR.old"
  mv "$tmp/src" "$INSTALL_DIR"
  rm -rf "$INSTALL_DIR.old"
  ok "installed $REPO@$version to $INSTALL_DIR"
}

link_command() {
  local repo_dir="$1" bin_dir="$2"
  local target="$repo_dir/bin/herdr-spec-drafter" link="$bin_dir/herdr-spec-drafter"
  echo "Command"
  chmod +x "$target"
  mkdir -p "$bin_dir"
  if [ -L "$link" ] && [ "$(readlink "$link")" = "$target" ]; then
    ok "already linked: $link"
  elif [ -L "$link" ] && [ "$(basename "$(readlink "$link")")" = "herdr-spec-drafter" ]; then
    local old
    old="$(readlink "$link")"
    ln -sfn "$target" "$link"
    ok "relinked $link -> $target (was $old)"
  elif [ -e "$link" ] || [ -L "$link" ]; then
    die "$link already exists and isn't a herdr-spec-drafter link; leaving it alone"
  else
    ln -s "$target" "$link"
    ok "linked $link -> $target"
  fi
  case ":$PATH:" in
    *":$bin_dir:"*) ok "$bin_dir is on your PATH" ;;
    *) warn "$bin_dir is not on your PATH; add this to your shell profile:"
       echo "      export PATH=\"$bin_dir:\$PATH\"" ;;
  esac
}

ensure_config() {
  local repo_dir="$1"
  echo "Config"
  if [ -f "$CONFIG_DIR/config.json" ]; then
    ok "keeping your existing $CONFIG_DIR/config.json"
  else
    mkdir -p "$CONFIG_DIR"
    cp "$repo_dir/config.example.json" "$CONFIG_DIR/config.json"
    ok "created $CONFIG_DIR/config.json"
    warn "edit it: at least workspace_root (the folder holding your repos)"
  fi
}

check_requirements() {
  echo "Requirements"
  local missing=0 cmd
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
  return "$missing"
}

main() {
  local version="" bin_dir="${HSD_BIN_DIR:-$HOME/.local/bin}"
  while [ $# -gt 0 ]; do
    case "$1" in
      --version) version="${2:?--version needs a value}"; shift 2 ;;
      --bin-dir) bin_dir="${2:?--bin-dir needs a value}"; shift 2 ;;
      -h|--help) sed -n '2,17p' "${BASH_SOURCE[0]:-/dev/null}" 2>/dev/null || true; exit 0 ;;
      *) die "unknown option: $1 (see --help)" ;;
    esac
  done

  local repo_dir
  repo_dir="$(script_checkout)"
  if [ -n "$repo_dir" ] && [ -z "$version" ]; then
    echo "Using this clone: $repo_dir"
  else
    download "$version"
    repo_dir="$INSTALL_DIR"
  fi

  link_command "$repo_dir" "$bin_dir"
  ensure_config "$repo_dir"
  echo
  if check_requirements; then
    echo
    echo "Done. Try:  herdr-spec-drafter once --dry-run"
  else
    echo
    fail "installed, but some requirements are missing (see above)"
    exit 1
  fi
}

# Everything runs from here, so a partly downloaded script does nothing.
main "$@"
