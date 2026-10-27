#!/bin/sh
# Puts Bot Widget in your user folder and creates a menu entry; no root needed.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
target="$HOME/.local/share/botwidget"
mkdir -p "$target" "$HOME/.local/bin" "$HOME/.local/share/applications"
rm -rf "$target/app"
cp -R "$here/app" "$target/app"
cp "$here/icon.png" "$target/icon.png"
# The icon theme is where the app menu, the dock and search look for it; the copy next to the app is the fallback.
icon_dir="$HOME/.local/share/icons/hicolor/512x512/apps"
mkdir -p "$icon_dir"
cp "$here/icon.png" "$icon_dir/botwidget.png"
# Not "botwidget": that is also the command name of a uv or pip install.
ln -sf "$target/app/Bot Widget" "$HOME/.local/bin/bot-widget"
# Quoted Exec so the app menu finds the installed app (not the unpacked folder).
app_path="$target/app/Bot Widget"
# StartupWMClass makes the running window find this entry: without it the dock shows a generic icon.
cat > "$HOME/.local/share/applications/botwidget.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Bot Widget
GenericName=Bot Face Widget
Comment=Animated bot face for OpenBot and Grok Bot
Exec="$app_path"
TryExec="$app_path"
Icon=botwidget
Terminal=false
Categories=Utility;Network;
Keywords=bot;widget;openbot;grok;face;
StartupWMClass=botwidget
StartupNotify=false
DESKTOP
# Without this the menu and search may not see the entry until the next login.
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$HOME/.local/share/applications" || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" || true
fi
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
