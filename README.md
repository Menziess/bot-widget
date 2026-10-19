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
- On Linux the widget fetches the X11 libraries Qt needs into its own folder on first start, without root; offline, install them with `sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xkb1`

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

The widget updates itself, and you can switch that off. On each start it asks GitHub whether a newer release exists.

- It downloads the new version in the background and checks it against the SHA256SUMS.txt published with the release
- The new version installs the next time the widget starts, or straight away through Restart to update in the right-click menu
- Settings has two switches, Check for updates and Install updates automatically
- With checking off nothing is requested, with automatic installing off the menu only links to the download page
- The request is anonymous and sends no data about you beyond what any web request carries

Automatic installing needs the packaged app. Installs through uv or pip, and checkouts, only show the link.

## Start at login

The first start turns on starting at login and says so in a bubble. Settings, Start at login, turns it off, and the choice then stays off.

- On macOS the app registers itself, so Login Items shows Bot Widget with its icon
- From a checkout the item is named Bot Widget (dev) instead of python
- On macOS the switch in System Settings and the one in the widget stay in step

## Develop

Run it from a checkout and keep the latest code on screen.

```sh
uv tool install --editable .
botwidget --dev
```

- The editable install makes the botwidget command run the code in this folder
- With --dev the widget restarts a moment after any .py file changes
- A crash waits for the next change instead of looping
- Starting at login from a checkout starts it in this mode too, so each login shows the latest iteration

Without a virtual environment, `uv venv && uv pip install -e .` and `.venv/bin/botwidget --dev` do the same.

### Switching between stable and local

Keep the installed app next to your checkout and hop between them from the right-click menu.

- Settings, Switch to local version starts the checkout, and Switch to stable version starts the installed app
- The stable app learns how to start your checkout the first time you run it with `botwidget --dev`
- Start at login follows whichever version you switch to, so only one of them starts at login
- The installed app is found in Applications on macOS, in the local share folder on Linux and in the Start menu folder on Windows

On Linux the installer names its command `bot-widget` so it does not clash with the `botwidget` command from `uv tool install`.

- Unit tests need no display and no Qt, run them with `python3 -m unittest discover -s tests -t .`
- Everything that differs per operating system lives in `botwidget/system/`, one module per OS with the same function names
- Everything that touches Qt lives in `botwidget/qt_ui/`
- `BOT_WIDGET_OPENBOT_DIR` points the widget at another OpenBot data folder, handy for testing

## Releasing

The git tag is the version. Push a tag and the release workflow builds and publishes everything.

```sh
git tag v0.1.1
git push origin v0.1.1
```

- The version is read from the tag at build time, so there is no number to edit in the code
- A build from a tag reports exactly that number, a build between tags reports a dev number such as 0.1.2.dev3
- The workflow stops if the number baked into the app is not the tag
- `botwidget --version` prints it

## Signing the downloads

Unsigned apps make macOS and Windows warn on first launch. The release workflow signs them as soon as certificates exist as repository secrets.

```sh
gh secret set MACOS_CERTIFICATE < certificate.p12.base64
```

- macOS needs MACOS_CERTIFICATE (a base64 Developer ID .p12), MACOS_CERTIFICATE_PASSWORD and MACOS_SIGN_IDENTITY
- Notarization also needs APPLE_ID, APPLE_TEAM_ID and APPLE_APP_PASSWORD
- Windows needs WINDOWS_CERTIFICATE (a base64 .pfx) and WINDOWS_CERT_PASSWORD
- Without these secrets the workflow still builds, just unsigned
