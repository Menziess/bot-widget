#!/bin/sh
# Zet Bot Widget in je gebruikersmap en maakt een menu-item; geen root nodig.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
target="$HOME/.local/share/botwidget"
mkdir -p "$target" "$HOME/.local/bin" "$HOME/.local/share/applications"
rm -rf "$target/app"
cp -R "$here/app" "$target/app"
cp "$here/icon.png" "$target/icon.png"
# Niet "botwidget": zo heet ook het commando van een uv- of pip-installatie.
ln -sf "$target/app/Bot Widget" "$HOME/.local/bin/bot-widget"
cat > "$HOME/.local/share/applications/botwidget.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Bot Widget
Comment=Animated bot face for OpenBot and Grok Bot
Exec=$target/app/Bot Widget
Icon=$target/icon.png
Categories=Utility;
Terminal=false
DESKTOP
echo "Installed. Search for 'Bot Widget' in your app menu, or run: bot-widget"

# Ontbrekende systeembibliotheken nu melden, niet als een crash bij de eerste start.
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
