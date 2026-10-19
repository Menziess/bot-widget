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
- Settings holds the sound and window options, and Quit

The widget needs OpenBot or Grok Bot. Without either, the face says so and links to both.

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
