#!/bin/sh
# Puts Bot Widget in your user folder and creates a menu entry; no root needed.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
target="$HOME/.local/share/botwidget"
mkdir -p "$target" "$HOME/.local/bin" "$HOME/.local/share/applications"
rm -rf "$target/app"
cp -R "$here/app" "$target/app"
cp "$here/icon.png" "$target/icon.png"
# Not "botwidget": that is also the command name of a uv or pip install.
ln -sf "$target/app/Bot Widget" "$HOME/.local/bin/bot-widget"
# Quoted Exec so the app menu finds the installed app (not the unpacked folder).
app_path="$target/app/Bot Widget"
cat > "$HOME/.local/share/applications/botwidget.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Bot Widget
Comment=Animated bot face for OpenBot and Grok Bot
Exec="$app_path"
Icon=$target/icon.png
Categories=Utility;
Terminal=false
DESKTOP
echo "Installed. Search for 'Bot Widget' in your app menu, or run: bot-widget"

# Report missing system libraries now, instead of as a crash on first start.
if command -v ldd >/dev/null 2>&1; then
  plugin="$target/app/_internal/PySide6/Qt/plugins/platforms/libqxcb.so"
  missing="$(LD_LIBRARY_PATH="$target/app/_internal:$target/app/_internal/PySide6/Qt/lib" ldd "$plugin" 2>&1 | grep 'not found')"
  if [ -n "$missing" ]; then
    echo
    echo "Warning: this system is missing something Bot Widget needs:"
    echo "$missing"
    echo "On Debian or Ubuntu try: sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libxcb-xkb1 libegl1 libgl1"
    echo "If the lines mention GLIBC, this system is too old for this build."
  fi
fi
