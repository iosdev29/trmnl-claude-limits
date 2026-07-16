#!/usr/bin/env bash
# Claude UNLMTD — one-command installer for Linux and macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/iosdev29/trmnl-claude-limits/main/scripts/bootstrap.sh | bash
#
# Downloads the repo into ~/.local/share/trmnl-claude-limits, drops a
# `trmnl-claude-limits` shim into ~/.local/bin, then runs the interactive
# installer (which prompts for your TRMNL webhook URL and schedules the
# push job via launchd/systemd).
#
# Override the source repo (for forks): REPO=you/your-fork bash bootstrap.sh
set -euo pipefail

REPO="${REPO:-iosdev29/trmnl-claude-limits}"
BRANCH="${BRANCH:-main}"
PREFIX="${PREFIX:-$HOME/.local/share/trmnl-claude-limits}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
PYTHON="${PYTHON:-python3}"

log()   { printf '\033[1;36m→\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m!\033[0m %s\n' "$*" >&2; }
die()   { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# Refuse to run if someone (or a mistake) points PREFIX at "/" or another
# directory outside the user's home — we mirror files into it and any wildcard
# cleanup could otherwise nuke the wrong tree.
case "$PREFIX" in
    "$HOME"/*) ;;
    *) die "refusing: PREFIX=$PREFIX must be inside \$HOME." ;;
esac
case "$BIN_DIR" in
    "$HOME"/*) ;;
    *) die "refusing: BIN_DIR=$BIN_DIR must be inside \$HOME." ;;
esac

command -v "$PYTHON" >/dev/null 2>&1 \
    || die "python3 not found. Install Python 3.8+ and retry."

command -v curl >/dev/null 2>&1 || die "curl not found."
command -v tar  >/dev/null 2>&1 || die "tar not found."

log "downloading $REPO@$BRANCH → $PREFIX"

# Refuse to mirror over a directory that isn't a prior install of ours —
# the --delete step would otherwise blow away user files if $PREFIX collides
# with something like ~/Documents.
MARKER="$PREFIX/.trmnl-claude-limits-install"
if [ -d "$PREFIX" ] && [ -n "$(ls -A "$PREFIX" 2>/dev/null || true)" ] && [ ! -f "$MARKER" ]; then
    die "refusing: $PREFIX exists and isn't a prior install (no marker file).
    Remove it manually or set PREFIX to an empty/nonexistent directory."
fi

mkdir -p "$PREFIX"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fsSL "https://codeload.github.com/${REPO}/tar.gz/refs/heads/${BRANCH}" \
    | tar -xz -C "$tmp"
# tarball extracts to <repo>-<branch>/ — strip that top level.
src="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -n1)"
[ -d "$src" ] || die "download failed — no source directory found"
# Prefer rsync so files removed upstream (e.g. renamed scripts) get pruned
# from an existing install. Fall back to cp only if rsync isn't available —
# any other rsync failure is a real error and should surface.
if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "$src/" "$PREFIX/"
else
    # First-time install path is clean by the marker guard above, so cp can't
    # leave stale files. Upgrades without rsync may leave old artifacts;
    # warn so the user knows to `rm -rf` and reinstall if it matters.
    warn "rsync not found — using cp (won't prune files removed since last install)"
    cp -a "$src/." "$PREFIX/"
fi
touch "$MARKER"

log "installing shim → $BIN_DIR/trmnl-claude-limits"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/trmnl-claude-limits" <<SH
#!/usr/bin/env bash
set -e
PREFIX="$PREFIX"
PYTHON="\${PYTHON:-python3}"
case "\${1:-}" in
  push)
    shift
    exec "\$PYTHON" "\$PREFIX/scripts/push_usage.py" "\$@"
    ;;
  *)
    exec "\$PYTHON" "\$PREFIX/scripts/install.py" "\$@"
    ;;
esac
SH
chmod +x "$BIN_DIR/trmnl-claude-limits"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not on your PATH — add this to your shell rc:"
       warn "    export PATH=\"$BIN_DIR:\$PATH\""
       ;;
esac

log "starting interactive setup..."
echo
# stdin is the pipe from curl, so hand the installer a real TTY.
if [ -t 0 ]; then
    exec "$BIN_DIR/trmnl-claude-limits"
elif [ -r /dev/tty ]; then
    exec "$BIN_DIR/trmnl-claude-limits" </dev/tty
else
    warn "no TTY available — skipping interactive setup."
    warn "run this next:  $BIN_DIR/trmnl-claude-limits"
fi
