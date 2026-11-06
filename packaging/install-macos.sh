#!/bin/sh
# Bot Widget for macOS (Apple Silicon): curl -fsSL https://bot-widget.com/install.sh | sh
# Downloads the macOS release, checks it against the release's SHA256SUMS.txt, puts
# "Bot Widget.app" in ~/Applications (or updates an existing copy in /Applications) and opens it.
# Never asks for sudo. A download from Terminal is not quarantined; any quarantine flag is removed.
# BOTWIDGET_VERSION=0.2.7 installs that version instead of the latest.
# BOTWIDGET_NO_OPEN=1 installs without opening the app.
set -eu

REPO="https://github.com/Menziess/bot-widget"
ASSET="BotWidget-macOS.zip"
APP="Bot Widget.app"

fail() {
  echo "Bot Widget: $*" >&2
  exit 1
}

[ "$(uname -s)" = "Darwin" ] || fail "this installer is for macOS. For Windows and Linux, see https://bot-widget.com"

# A Terminal under Rosetta reports x86_64 on an Apple Silicon Mac, so also ask the hardware.
if [ "$(uname -m)" != "arm64" ] && [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" != "1" ]; then
  fail "this Mac has an Intel processor. The macOS app is built for Apple Silicon (M1 or newer) only. On an Intel Mac, install it with uv instead: uv tool install git+$REPO"
fi

version="${BOTWIDGET_VERSION:-}"
if [ -n "$version" ]; then
  base="$REPO/releases/download/v${version#v}"
else
  base="$REPO/releases/latest/download"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT INT TERM

echo "Downloading Bot Widget${version:+ $version}..."
curl -fsSL -o "$tmp/$ASSET" "$base/$ASSET" || fail "download failed: $base/$ASSET"
curl -fsSL -o "$tmp/SHA256SUMS.txt" "$base/SHA256SUMS.txt" || fail "download failed: $base/SHA256SUMS.txt"

want="$(awk -v f="$ASSET" '$2 == f || $2 == "*" f { print $1 }' "$tmp/SHA256SUMS.txt")"
[ -n "$want" ] || fail "$ASSET is not listed in SHA256SUMS.txt"
have="$(shasum -a 256 "$tmp/$ASSET" | awk '{ print $1 }')"
[ "$want" = "$have" ] || fail "checksum mismatch for $ASSET (expected $want, got $have)"

mkdir "$tmp/unpacked"
ditto -x -k "$tmp/$ASSET" "$tmp/unpacked" || fail "could not unpack $ASSET"
[ -d "$tmp/unpacked/$APP" ] || fail "$APP is missing from $ASSET"

xattr -dr com.apple.quarantine "$tmp/unpacked/$APP" 2>/dev/null || true
# The release is ad-hoc signed; Apple Silicon runs nothing without a valid signature.
if ! codesign --verify --deep --strict "$tmp/unpacked/$APP" 2>/dev/null; then
  echo "The app's signature did not verify; signing it ad hoc on this Mac."
  codesign --force --deep --sign - "$tmp/unpacked/$APP" || fail "could not sign $APP"
fi

# Update a copy already in /Applications when we may write there; otherwise ~/Applications.
if [ -d "/Applications/$APP" ] && [ -w "/Applications" ] && [ -w "/Applications/$APP" ]; then
  dest="/Applications"
else
  dest="$HOME/Applications"
fi
mkdir -p "$dest"

# Quit a running copy first (only if one runs: telling a closed app to quit would start it).
if pgrep -f "$APP/Contents/MacOS/" >/dev/null 2>&1; then
  osascript -e 'tell application "Bot Widget" to quit' >/dev/null 2>&1 || true
  sleep 1
fi
rm -rf "$dest/$APP.old"
[ ! -e "$dest/$APP" ] || mv "$dest/$APP" "$dest/$APP.old"
mv "$tmp/unpacked/$APP" "$dest/$APP" || { [ ! -e "$dest/$APP.old" ] || mv "$dest/$APP.old" "$dest/$APP"; fail "could not install into $dest"; }
rm -rf "$dest/$APP.old"

echo "Installed: $dest/$APP"
if [ "${BOTWIDGET_NO_OPEN:-}" != "1" ]; then
  open "$dest/$APP"
fi
