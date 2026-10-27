# Bot widget

An animated bot face that floats on the desktop, shows the latest answer in a speech bubble, and opens a chat window on click. It talks to the local OpenBot.

## Install

One command installs the widget and everything it needs, including the Qt toolkit.

```sh
uv tool install git+https://github.com/Menziess/bot-widget
```

uv is for the command line and for development. On Linux the face stays tied to that terminal, so closing the terminal quits the face. For a start from the app menu, use the Linux tar and `install.sh`. That command is `bot-widget`. To leave the terminal and keep the face: `nohup botwidget >/dev/null 2>&1 &`.

- Instead of uv, `pipx install git+https://github.com/Menziess/bot-widget` works the same way
- Python 3.10 or newer is the only requirement
- Linux, macOS and Windows use the same code
- On Linux the widget fetches the X11 libraries Qt needs into its own folder on first start, without root; offline, install them with `sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xkb1`

## Run

```sh
botwidget
```

- Point at the face to open the bubble, also when the pointer was already there: the latest message, and a field to type in
- After a restart the old conversation does not open the bubble by itself; only a message that comes after does
- The field is focused once the pointer stays on the face for a moment, press Enter to send
- Earlier messages load one at a time. Scroll up at the top of the bubble, or point at its top edge, and a thin line across the top of the bubble appears (the bubble grows by it, the text moves down) and stays there. On a page of the menu the same line is on top, and pulling it far enough goes back. The pointer on it makes the middle swell a little. Keep scrolling and the line is pulled: its middle swells into a soft blue glow with an arrow in it by the distance you scrolled, however fast or slow, and it shrinks again when you scroll back down. Pulled far enough (about 140 pixels), or clicked, the message before slides in; let go earlier and the line shoots back up. After a message came in, the scrolling that is still going on (coasting included) does nothing: the next message needs a new scroll. A message that comes in is shown from its end (its last lines in view, scroll up to read it), not from its top
- Names only show above the messages when there are several
- The bubble sits above the face, or to the right of it when there is no room above, then to the left, and below only when nothing else fits
- The bubble that pointing at a face opens next is laid out in advance (text, glass, shadow), while nobody waits, so it opens at once even for a long answer
- When the turn for your message fails (a provider that is signed out or spent, say), the thinking stops at once and the bubble says why; a failure from before you asked does not count
- Markdown tables are shown as columns (the header in bold with a line under it); the bubble gets wider for a table when it may, and words that still do not fit are cut short with an ellipsis
- The field for a message only shows while the pointer is on the bubble or its face (a bubble that opens by itself has none); it goes a moment after the pointer left, and stays while you have words in it
- Clicking the face while a page of the menu (or the command list) is open brings the chat bubble back
- The bubble opens at its full size, fading in and sliding out from the face, and closes as soon as the pointer leaves or you click into another window with nothing typed
- The bubble and the thinking cloud are glass: a white that turns faintly cool towards the bottom, with a bright inner edge, a faint outer line and a soft shadow that stays outside the shape. On macOS what is behind the bubble is blurred (frosted glass; the Glass transparency slider on the /settings page sets how much of it shows through, live), elsewhere the glass is almost opaque so the text stays easy to read
- Text that scrolls out of the bubble fades away at the edge instead of being cut off, on the sides where there is more of it
- After you send a message the bubble stays, with moving dots, until the bot has answered
- A new answer opens it by itself and it stays for as long as it takes to read, unless you point at it
- It also stays while you have typed words or selected words
- A hand shows over a message: click copies it as plain text, shift+click copies the markdown it was written in
- Drag over the words to select them, the selection is copied when you let go, and "Copied" shows over the message and its words fade behind it for a moment
- Clicking in the bubble never opens or closes it
- The answer sound is off by default, and when on it only plays while the face is out of view (covered or on another desktop)
- The eyes follow the pointer when it is near, and look at you when it is over the face
- Every face is drawn as a 3D body, built the way Grok Bot builds its avatars (extruded, turned on a lathe, lofted or rounded), so when it turns, its outline and shading turn with it, and its eyes lie on its surface, so they curve and get narrower towards the edge.
- Idle is calm: the face holds still and only now and then, after a random 8 to 30 seconds, blinks or looks around. When something happens it plays one of Grok Bot's own clips: a nod when your message goes out, an inspecting look while the bot thinks, a happy hop on the reply, surprise at a message nobody asked for, a sad face when a message is refused, confused and then sleepy when there is no route, and a bounce when you click it. While it holds still it draws only ten frames a second.
- While the bot works with nothing sent from the bubble, it turns into a thought cloud
- A message you send shows a small cloud with dots at once. Pointing at the face or the cloud opens the thought with the field; moving away shrinks it back to the dots, which go by themselves after a few seconds
- Right after you send, the cloud shows only its dots, with no field, even when the pointer is still on it; the thought and the field open when you leave the cloud and point at it again, or click the face
- Dots and thought, and chat and cloud, replace each other with a fade instead of growing into each other; a thought is read from the top while the cloud grows
- The cloud shows the thought as markdown, follows the end of it as it grows, and has the field below
- What you type while the bot works waits in a queue under the thought, a click on one puts it back in the field to edit, and one goes out per finished turn
- A question or approval from the bot shows in the cloud with a button per answer, and typing in the field answers the open question
- Shift+click a face to mute its thinking, a cross for a mouth shows it, and the choice is kept
- Only one bubble is open at a time when you point at or click a face
- Pointing at a face always wins its bubble, also when that face lies under the invisible border around another open bubble
- Dragging a face over another one does not open the bubble of that one, and two faces on top of each other do not fight over the bubble
- Turning off the bot whose bubble holds a page moves the page to the bubble of another bot
- Typing, sending, picking a command or attaching a file keeps the bubble open for a few seconds, also when the pointer is away
- A field that was typed in keeps the bubble open, also when you emptied it again, until you send, press Escape or click the face
- The field grows to five lines, then scrolls with the cursor, wrapped lines included, so what you type stays in view
- With Show on all desktops off, a bubble only opens on the desktop of its face; elsewhere you only hear the sound, and the bubble opens when you go there
- With Show on all desktops off, a face stays on the desktop it lives on and a bubble always opens on the desktop you are on, so showing it never takes you to another one; the key combination brings every face to the desktop you are on
- Spaces at the end of a line wrap with the text in the field, so it never scrolls sideways
- A bubble that opens by itself (another bot answers) never covers the one you are busy with: it takes another side, or waits out of sight and comes back once yours is gone
- Shift+Enter starts a new line in the field, and the field grows with its lines
- Paste a file or a picture in the field to send it along, it shows as a chip that you can remove, and the message gets a list of the files under the shared folder of OpenBot
- Drag the face to move it, it bounces off screen edges
- A small orange dot on the face means a message of yours is waiting for OpenBot or was refused
- Right-click the face, or start the field with a slash, and a list of commands opens above the field. /feedback opens a new GitHub issue in the browser, already filled with the version, the system and how it was installed
- Pick a command with the arrows and Return, Tab fills it in, and Escape closes the list and clears the command you typed (a message that was already there stays)
- A page (settings, bots, connections) goes away by itself like any bubble, and with Escape
- The /settings page holds sound, quiet hours, window stacking, desktops, start at login, update checks, switching version, and Quit
- The /bots page switches the face of each bot on or off, and mutes its thinking
- The /connections page has a switch per bot app, on when it was found, with whether the local API of OpenBot is on; turning one on that was not found opens its page and the switch stays on while it waits
- Each page opens in the bubble, with real switches and buttons, and the arrow on top goes back
- On macOS Control+Option+Space opens the chat from any app, and closes it again
- The face goes back to where you put it when its screen comes back
- On macOS the face and its bubble are on every desktop. With Settings, Show on all desktops off the face stays on one, and Control+Option+Space on another desktop brings it there, and a window cannot be dragged into a full-screen app's desktop

The widget needs OpenBot or Grok Bot. Without either, the face says so and links to both.

## Grok Bot

The widget can also talk to one bot of Grok Bot. It does that with the `gbot` command, so the Grok Bot app on this computer has to be running and signed in.

- The bot is the one named in `grokbot_target` in widget.json, General without it
- After you send a message the widget asks for the answer every 5 seconds, for 10 minutes at the most, then stops asking
- Opening the bubble looks once for what came in; with nothing to wait for it does not ask at all
- The first look shows only the latest 5 answers as history
- Only sending may start the Grok Bot app; looking for answers never starts or focuses it
- A message that got no answer from gbot in time shows with (?) after it: it may or may not have gone out
- When gbot says there is no route, or is not there at all, the widget stops and says so
- The next message you send tries again
- /bots switches the Grok face on or off, like the faces of the other bots
- The Grok face wears the avatar Grok Bot gives the bot: its own shape (blob, hex, cloud, clover, sparkle, house, square and the rest) and colour; it moves and blinks like the other faces
- Without an answer from Grok Bot the face takes `grokbot_avatars` in widget.json, e.g. `{"General": {"shape": "blob", "color": "black"}}`, and else the avatar Grok Bot gave last time

## Updates

The widget updates itself, and you can switch that off. At each start, and every 6 hours after, it asks GitHub whether a newer release exists.

- It downloads the new version in the background and checks it against the SHA256SUMS.txt published with the release
- The widget restarts into the new version as soon as nobody is using a face, or straight away through Restart to update on the /settings page
- /settings has two switches, Check for updates and Install updates automatically
- With checking off nothing is requested, with automatic installing off the page only links to the download page
- The request is anonymous and sends no data about you beyond what any web request carries

Automatic installing needs the packaged app. Installs through uv or pip only show the link.

A widget that runs from a git checkout (the local version) does not look for releases. With Install updates automatically on it fetches `origin main` at the start and every 15 minutes, and pulls when that is a plain fast-forward. It leaves the checkout alone when you are on another branch, have changes of your own or commits that are not pushed, or when there is no network. The dev mode (`botwidget --dev`) then restarts the widget by itself on the new code.

## Start at login

The first start turns on starting at login and says so in a bubble. /settings, Start at login, turns it off, and the choice then stays off.

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

Keep the installed app next to your checkout and hop between them from the /settings page.

- /settings, Switch to local version starts the checkout, and Switch to stable version starts the installed app
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

### Windows Authenticode (SmartScreen)

Unsigned Windows builds show SmartScreen. There is no code bypass; a signed installer earns reputation over time.

1. Buy a **standard** Authenticode code-signing certificate from a public CA (Sectigo, DigiCert, SSL.com, and similar). An **EV** certificate is optional: it can skip SmartScreen sooner, but a standard cert is enough once reputation builds.
2. Export a password-protected `.pfx`. Do not commit it.
3. Base64-encode the file and set GitHub Actions secrets on `Menziess/bot-widget`: `WINDOWS_CERTIFICATE` (the base64) and `WINDOWS_CERT_PASSWORD`.
4. Push a new tag so the release workflow signs both `Bot Widget.exe` and `BotWidget-Windows-Setup.exe`.

Do not invent a certificate or spend money from this repo. Until those secrets exist, Windows downloads stay unsigned: in SmartScreen choose **More info**, then **Run anyway**.
