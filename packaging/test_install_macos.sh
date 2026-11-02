#!/bin/sh
# shellcheck disable=SC2016  # the stubs and checks are meant to expand later, in their own shell
# Tests for install-macos.sh with stubbed macOS tools (uname, sysctl, curl, shasum, ditto,
# codesign, xattr, open, pgrep, osascript), so they run on Linux. Run: sh packaging/test_install_macos.sh
set -u

here="$(cd "$(dirname "$0")" && pwd)"
script="$here/install-macos.sh"
pass=0
failed=0

setup() {
  t="$(mktemp -d)"
  mkdir -p "$t/bin" "$t/home" "$t/release"
  printf 'zip' > "$t/release/BotWidget-macOS.zip"
  printf '%s  BotWidget-macOS.zip\n' "$(sha256sum "$t/release/BotWidget-macOS.zip" | awk '{print $1}')" > "$t/release/SHA256SUMS.txt"
  stub uname 'case "$1" in -s) echo "${STUB_OS:-Darwin}";; -m) echo "${STUB_ARCH:-arm64}";; esac'
  stub sysctl 'echo "${STUB_HW_ARM64:-0}"'
  # curl -fsSL -o OUT URL: copies the release file named by the URL, logs the URL.
  stub curl 'out="$3"; url="$4"; echo "$url" >> "$T/curl.log"; cp "$T/release/${url##*/}" "$out"'
  stub shasum 'sha256sum "$3"'
  stub ditto 'mkdir -p "$4/Bot Widget.app/Contents/MacOS"'
  stub codesign 'echo "$*" >> "$T/codesign.log"; [ "$1" != "--verify" ] || [ "${STUB_SIG_OK:-1}" = "1" ]'
  stub xattr 'echo "$*" >> "$T/xattr.log"'
  stub open 'echo "$*" >> "$T/open.log"'
  stub pgrep 'exit 1'
  stub osascript 'exit 0'
}

stub() {
  printf '#!/bin/sh\n%s\n' "$2" > "$t/bin/$1"
  chmod +x "$t/bin/$1"
}

run() {
  env PATH="$t/bin:$PATH" HOME="$t/home" T="$t" "$@" "${SHELL_UNDER_TEST:-sh}" "$script" > "$t/out" 2>&1
}

check() {
  name="$1"
  shift
  if "$@"; then
    pass=$((pass + 1))
  else
    failed=$((failed + 1))
    echo "FAIL: $name"
    sed 's/^/  | /' "$t/out"
  fi
  rm -rf "$t"
}

app() { [ -d "$t/home/Applications/Bot Widget.app" ]; }

setup; run
check "installs the latest into ~/Applications and opens it" \
  sh -c 'app() { [ -d "$1/home/Applications/Bot Widget.app" ]; }; app "$1" && grep -q "releases/latest/download/BotWidget-macOS.zip" "$1/curl.log" && grep -q "Bot Widget.app" "$1/open.log" && grep -q com.apple.quarantine "$1/xattr.log"' _ "$t"

setup; run STUB_ARCH=x86_64
check "refuses an Intel Mac with a clear message" \
  sh -c '! [ -d "$1/home/Applications/Bot Widget.app" ] && grep -q "Intel processor" "$1/out" && ! [ -e "$1/curl.log" ]' _ "$t"

setup; run STUB_ARCH=x86_64 STUB_HW_ARM64=1
check "a Rosetta Terminal on Apple Silicon still installs" app

setup; run STUB_OS=Linux
check "refuses other systems" sh -c 'grep -q "for macOS" "$1/out" && ! [ -e "$1/curl.log" ]' _ "$t"

setup; printf 'other' > "$t/release/BotWidget-macOS.zip"; run
check "refuses a checksum mismatch" sh -c '! [ -d "$1/home/Applications/Bot Widget.app" ] && grep -q "checksum mismatch" "$1/out"' _ "$t"

setup; run BOTWIDGET_VERSION=v0.2.7 BOTWIDGET_NO_OPEN=1
check "a pinned version, not opened" sh -c 'grep -q "releases/download/v0.2.7/BotWidget-macOS.zip" "$1/curl.log" && ! [ -e "$1/open.log" ]' _ "$t"

setup; run STUB_SIG_OK=0 BOTWIDGET_NO_OPEN=1
check "signs ad hoc when the signature does not verify" sh -c 'grep -q -- "--force --deep --sign -" "$1/codesign.log" && [ -d "$1/home/Applications/Bot Widget.app" ]' _ "$t"

setup; mkdir -p "$t/home/Applications/Bot Widget.app/old-marker"; run BOTWIDGET_NO_OPEN=1
check "replaces an earlier install" sh -c '[ -d "$1/home/Applications/Bot Widget.app/Contents" ] && ! [ -e "$1/home/Applications/Bot Widget.app/old-marker" ] && ! [ -e "$1/home/Applications/Bot Widget.app.old" ]' _ "$t"

echo "install-macos.sh: $pass passed, $failed failed"
[ "$failed" -eq 0 ]
