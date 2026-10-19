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
