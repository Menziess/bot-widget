# Bot widget

An animated bot face that floats on the desktop, shows the latest answer in a speech bubble, and opens a chat window on click. It talks to the local OpenBot.

## Install

One command installs the widget and everything it needs, including the Qt toolkit.

```sh
uv tool install git+https://github.com/Menziess/bot-widget
```

- Instead of uv, `pipx install git+https://github.com/Menziess/bot-widget` works the same way
- Python 3.10 or newer is the only requirement
- Linux, macOS and Windows use the same code

## Run

```sh
botwidget
```

- Click the face to open the chat bubble, type, press Enter
- While the bot works the bubble turns into a thought cloud
- Drag the face to move it, it bounces off screen edges
- Right-click the face to see which bot apps were found, switch bots on and off, and reach Settings
- Settings holds sound, window stacking, start at login and update checks, and Quit

The widget needs OpenBot or Grok Bot. Without either, the face says so and links to both.

## Updates

On each start the widget asks GitHub whether a newer release exists, and the right-click menu then shows a link to the download page.

- The request is anonymous and sends no data about you beyond what any web request carries
- Turn it off under Settings, Check for updates

## Develop

Run it from a checkout with a virtual environment.

```sh
uv venv && uv pip install -e .
.venv/bin/botwidget
```

- Unit tests need no display and no Qt, run them with `python3 -m unittest discover -s tests -t .`
- Everything that differs per operating system lives in `botwidget/system/`, one module per OS with the same function names
- Everything that touches Qt lives in `botwidget/qt_ui/`
- `BOT_WIDGET_OPENBOT_DIR` points the widget at another OpenBot data folder, handy for testing

## Signing the downloads

Unsigned apps make macOS and Windows warn on first launch. The release workflow signs them as soon as certificates exist as repository secrets.

```sh
gh secret set MACOS_CERTIFICATE < certificate.p12.base64
```

- macOS needs MACOS_CERTIFICATE (a base64 Developer ID .p12), MACOS_CERTIFICATE_PASSWORD and MACOS_SIGN_IDENTITY
- Notarization also needs APPLE_ID, APPLE_TEAM_ID and APPLE_APP_PASSWORD
- Windows needs WINDOWS_CERTIFICATE (a base64 .pfx) and WINDOWS_CERT_PASSWORD
- Without these secrets the workflow still builds, just unsigned
