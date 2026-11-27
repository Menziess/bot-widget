# Bot widget

An animated bot face that floats on the desktop, shows the latest answer in a speech bubble, and opens a chat window on click. It talks to a bot of your own over ACP, such as the agent that comes with it, and to OpenBot or Grok Bot when you use them (see A bot of your own).

## Install

One command installs the widget and everything it needs, including the Qt toolkit.

```sh
uv tool install git+https://github.com/Menziess/bot-widget
```

uv is for the command line and for development. On Linux the face stays tied to that terminal, so closing the terminal quits the face. For a start from the app menu, use the Linux tar and `install.sh`. That command is `bot-widget`. To leave the terminal and keep the face: `nohup botwidget >/dev/null 2>&1 &`.

- On a Mac with Apple Silicon, `curl -fsSL https://bot-widget.com/install.sh | sh` puts the app in `~/Applications` and opens it. A download from Terminal is not quarantined, so macOS does not show its warning for apps that are not notarized. The script is `packaging/install-macos.sh`: it checks the download against the release's SHA256SUMS.txt and the app's signature, and never asks for sudo. `BOTWIDGET_VERSION=0.2.7` installs that version instead of the latest
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
- Earlier messages load one at a time. Scroll up at the top of the bubble, or point at its top edge, and a thin line across the top of the bubble appears (the bubble grows by it, the text moves down) and stays there. On a page of the menu, and on the command list, the same line takes no room at all until you scroll up at the top, point at the top edge or press there (a touch): then it slides in, the page moves down, and it stays. Pulling it far enough goes back. The pointer on it makes the middle swell a little. Keep scrolling and the line is pulled: its middle swells into a soft blue glow with an arrow in it by the distance you scrolled, however fast or slow, and it shrinks again when you scroll back down. Pulled far enough (about 140 pixels), or clicked, the message before slides in; let go earlier and the line shoots back up. After a message came in, the scrolling that is still going on (coasting included) does nothing: the next message needs a new scroll. A message that comes in is shown from its end (its last lines in view, scroll up to read it), not from its top
- Names only show above the messages when there are several
- The bubble sits above the face, or to the right of it when there is no room above, then to the left, and below only when nothing else fits
- The bubble that pointing at a face opens next is laid out in advance (text, glass, shadow), while nobody waits, so it opens at once even for a long answer
- When the turn for your message fails (a provider that is signed out or spent, say), the thinking stops at once and the bubble says why; a failure from before you asked does not count
- Markdown tables are shown as columns (the header in bold with a line under it); the bubble gets wider for a table when it may, and words that still do not fit are cut short with an ellipsis
- The field for a message only shows while the pointer is on the bubble or its face (a bubble that opens by itself has none); it goes a moment after the pointer left, and stays while you have words in it
- Clicking the face while a page of the menu (or the command list) is open brings the chat bubble back
- The next hover after the pointer leaves a page opens that same page again, for page_memory_s seconds (60 when widget.json has no such key). After that the next hover opens the normal chat. The page is not written to config. A click outside closes the bubble and forgets the page. Escape on a page returns to the chat and forgets the page. The page takes the keyboard when it opens under the pointer, so that key arrives. A click on the face, or the line back to the command list, also forgets it
- The bubble opens at its full size, fading in and sliding out from the face, and closes shortly after the pointer leaves (a little longer while the pointer still moves fast) or when you click into another window with nothing typed
- The bubble and the thinking cloud are glass: a white that turns faintly cool towards the bottom, with a bright inner edge, a faint outer line and a soft shadow that stays outside the shape. On macOS what is behind the bubble is blurred (frosted glass; the Glass transparency slider on the /settings page sets how much of it shows through, live), elsewhere the glass is almost opaque so the text stays easy to read
- Text that scrolls out of the bubble fades away at the edge instead of being cut off, on the sides where there is more of it
- After you send a message the bubble stays, with moving dots, until the bot has answered
- A new answer opens it by itself and it stays for as long as it takes to read, unless you point at it
- It also stays while you have typed words or selected words
- A hand shows over a message: click copies it as plain text, shift+click copies the markdown it was written in
- Drag over the words to select them, the selection is copied when you let go, and "Copied" shows over the message and its words fade behind it for a moment
- Clicking in the bubble never opens or closes it
- Clicking the face while its bubble is open pins the bubble. It stays when the pointer leaves or another window is clicked, and the face keeps looking straight at you. Clicking the face again lets it go, and it then closes the usual way
- The answer sound is off by default, and when on it only plays while the face is out of view (covered or on another desktop)
- The eyes follow the pointer wherever it is, with a squint when it is near, and look at you when it is over the face
- Every face is drawn as a 3D body, built the way Grok Bot builds its avatars (extruded, turned on a lathe, lofted or rounded), so when it turns, its outline and shading turn with it, and its eyes lie on its surface, so they curve and get narrower towards the edge.
- Idle is calm: the face holds still and only now and then, after a random 8 to 30 seconds, blinks or looks around. When something happens it plays one of Grok Bot's own clips: a nod when your message goes out, an inspecting look while the bot thinks, a happy hop on the reply, surprise at a message nobody asked for, a sad face when a message is refused, confused and then sleepy when there is no route, a bounce when you click it, a finish hop when a background job ends, a head shake when you reset it, a nod and a wink when you accept what it asked, dazed eyes when you throw it, narrowed eyes while a tool runs, and sleepy eyes after five quiet minutes (anything wakes it). While it holds still it draws only ten frames a second.
- While the bot works with nothing sent from the bubble, it turns into a thought cloud
- While a bot is working and its thinking cloud is muted or closed, a small line under its face says Thinking (Watching while you select what to screenshot), on a faint glass chip so it can be read on any wallpaper. The line stays away while that cloud is open, and while a question, an approval or the browser is waiting
- A message you send shows a small cloud with dots at once. Pointing at the face or the cloud opens the thought with the field; moving away shrinks it back to the dots, which go by themselves after a few seconds
- Right after you send, the cloud shows only its dots, with no field, even when the pointer is still on it; the thought and the field open when you leave the cloud and point at it again, or click the face
- Dots and thought, and chat and cloud, replace each other with a fade instead of growing into each other; a thought is read from the top while the cloud grows
- The cloud shows the thought as markdown, follows the end of it as it grows, and has the field below
- What you type while the bot works waits in a queue under the thought, a click on one puts it back in the field to edit, and one goes out per finished turn
- A turn that a restart cut off before it was answered is picked up again when the widget is back, and says so in the cloud. The bot sees what it already did and asks again for what needs permission
- Double-click a face, or choose /screenshot from the right-click list, to take a screenshot: every screen goes dark, drag a rectangle on one of them, and the picture waits in the field as an attachment, so you can write something before you send it. Escape or a right-click cancels
- A question or approval from the bot shows in the cloud with a button per answer, and typing in the field answers the open question. The buttons of an approval sit side by side, and the dots stay away while it waits for you. The cloud opens by itself when it comes and goes by itself after the time it takes to read, unless the pointer is on it; the dot stays until it is answered
- Shift+click a face to mute its thinking, it falls asleep (lids mostly shut) to show it, and the choice is kept
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
- Paste a file or a picture in the field to send it along, it shows as a chip that you can remove, and the message gets a list of the files in a `botwidget-transfers` folder in the system temp folder, which the system cleans up by itself
- Drag the face to move it, it bounces off screen edges
- A small orange dot on the face means a message of yours is waiting for OpenBot or was refused
- /demo runs the chat demo (the tasks go through the chat, and code checks the outcome). The checklist opens in the bubble when the last task is checked; there is no separate window. It is in the list only while the widget was started with --dev
- The chat input field has a "/" button at the far right. Clicking it, typing "/" in the field, or right-clicking the face all open the same slash-command list inline under the field. A skill takes arguments: while the first word is the skill, its row stays and shows what you type behind it, up to the width of the bubble. /feedback opens a new GitHub issue in the browser, already filled with the version, the system and how it was installed
- Pick a command with the arrows and Return, Tab fills it in, and Escape closes the list and clears the command you typed (a message that was already there stays). While the command list is visible, the bubble's chat messages are hidden; they return when the list closes
- A page (settings, bots, connections) goes away by itself like any bubble. Escape returns straight to the chat, also when the page was opened again because the pointer came back. A click outside closes it. A left click on its face brings the chat back, and the line at the top (scrolling up past the top of the page) goes one level up (a page to the command list) in the same bubble, with the field to type in
- The /settings page holds sound, quiet hours, window stacking, desktops, start at login, update checks, switching version, and Quit
- The /bots page switches the face of each bot on or off, and mutes its thinking. Reset on a bot clears its conversation and restarts it (a bot of your own starts a fresh session; the others are looked at again, and a stuck pin or thought is cleared). The buttons of a bot sit under its name. There is no /refresh any more
- A longer command list scrolls inside the bubble, up to 45% of the screen height; the / button hides while the list is open
- The /connections page has two parts. Apps (OpenBot, Grok Bot, Hermes Bot) have a switch and one grey line on where each stands; turning one on that was not installed opens its page and the switch stays on while it waits. Models are the AI services your own bots think with, one switch each, with Edit and Remove below it. New connection has a Provider button that fills the address of xAI, OpenAI, OpenRouter, Google Gemini, GitHub Models or Anthropic (its own Messages API; the address tells the bot which API to speak), and keeps what you typed. No model names are built in: List models asks the service itself (`GET {address}/models`, with the key from the key file) and Next model steps through what it offers. You can also type a name. The key still comes from a file (keep it private: `chmod 600`, the bot says so when others can read it), and a hosted service needs its own
- Each page opens in the bubble, with real switches and buttons, and the line on top goes one level back: chat, then the command list, then Settings, Bots or Connections, then a form
- On macOS Control+Option+Space opens the chat from any app, and closes it again
- The face goes back to where you put it when its screen comes back
- On macOS the face and its bubble are on every desktop. With Settings, Show on all desktops off the face stays on one, and Control+Option+Space on another desktop brings it there, and a window cannot be dragged into a full-screen app's desktop

The placeholder bot is the face you get before you have added a bot. Without OpenBot or Grok Bot, it says so once: type /bots and choose New bot to add one of your own, or install either app. It links to both apps. A bot with a backend of its own, like the harness, never says it.

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
- The widget can also read live status from a relay. The channel is `grok_relay` in widget.json, either a topic name or a full URL. With that key missing or blank, the widget does not subscribe. A roster on the channel lists each bot by name, plus team, color, face and chat_url when they are sent, and each bot gets a Grok face whose shape and colour come from face and color. A status line for that bot (`start`, `done`, `stuck` or `needs_you`) is shown on its face. Stuck and needs_you also light the notification dot; start and done do not. The bubble shows that summary, and Accept or Decline only when a question or approval is actually waiting. Connections → Link Grok bots creates the channel and copies one chief prompt for General.

## A bot of your own

The widget can show a face for an agent that speaks ACP, such as the lean agent in `harness/`, with no OpenBot and no Grok Bot behind it. Each bot is one entry in `acp_bots` in `widget.json` (`~/.config/botwidget/widget.json` on Linux).

```json
{
  "acp_bots": [
    {
      "name": "Local Bot",
      "command": "env PYTHONPATH=/home/you/Projects/bot-widget /home/you/Projects/bot-widget/.venv/bin/python -m harness.agent",
      "env": {
        "HARNESS_BOT": "Local Bot",
        "HARNESS_MODEL_BASE_URL": "http://127.0.0.1:8080/v1",
        "HARNESS_MODEL": "local"
      },
      "key_file": "~/.config/llm/key"
    }
  ]
}
```

You can add a bot from the widget instead of editing this file. `/bots`, then New bot, asks for the name, the face, the colour, the model address, the model name and the key file. It starts filled in for the llama.cpp server above (`http://127.0.0.1:8080/v1`, model `local`, key file `~/.config/llm/key`). Edit and Remove are on the same page, so the face, the name and the colour can be changed later, and two bots can use one model. Edit widget.json on that page is the same file for everything the form does not show: the text is checked before it is saved, the previous file is kept as `widget.json.bak`, and a key pasted into the text is refused. Saving restarts only the bot that changed. The widget does not write an older copy of this file when it quits.

- `name` is what the face is called. The face id stays as it was when the bot was added, so renaming it keeps its conversation
- `command` starts the agent on stdio, from the bot's own folder under `~/.local/share/botwidget/harness/`. The example runs the lean agent from a checkout of this repository; any ACP agent works here
- `env` holds `HARNESS_*` settings only: the model server, the model name, the bot's name, and the background-job hooks below
- `key_file` is the path to a file with the API key, read at start and passed as `HARNESS_MODEL_API_KEY`. The key itself never goes in `widget.json`
- The conversation is kept per bot; after a widget restart the face loads the same session and shows the history again
- A write the bot asks about shows Accept and Decline in the bubble, and Always allow when the agent offers to remember the command. A running turn can be cancelled
- The context meter under the conversation shows how full the context is, and a pin_fact tool keeps a fact through compaction. After an answer is finished, older turns are folded in the background when that answer used at least 80 percent of the model's context window, and also when the conversation holds more than 40 messages. The window is the size the model server reports, or 32000 tokens when it reports none. The fill is the model's own prompt token count when it sent one, and otherwise about four characters per token. The next message waits up to 20 seconds only when that fold is still running. A fold that already finished does not delay it. After the wait the message goes out, and the fold is kept for a later turn. The line Compacted older turns shows then. It does not show while an answer is still arriving, and a fold does not start while an answer is still arriving
- What the bot remembers with its memory tools is on the `/memory` page, with Edit and Forget on every row and New memory below the list. Edit changes the text and the topic, and the memory keeps its scope and its time
- What you accepted for good (Permission `allow`) is in `approvals.json`, on the `/approvals` page (Memory and Approvals lead back to the command list). It is one file for every bot, edited like widget.json. See below

The bot can leave a shell command running and keep talking. `shell_background` starts it (the same permission question as `shell`), `jobs` lists what is still running, and `job_cancel` stops one. When the command exits, the same session gets the exit code and a short tail of the output, and the bot answers that. The job keeps running when the bubble closes, and when the agent restarts: its output goes to files in `jobs/` under the bot's folder, and the agent that starts next adopts it, tells the session in one line that it is still running (so the bot does not start it again), and delivers the result when it ends. A job that ended while the agent was away reports itself the same way. Only `job_cancel` or the job's own timeout stops one. While one is running, the line under the conversation says so.

The bot can look itself up. `about_me` answers one topic at a time (skills, bot, commands, settings), so none of it sits in the prompt until the bot asks. `run_command` starts any slash command in the list, and `change_setting` changes one plain setting. Both ask for Accept in the bubble first. Keys never show. `remote_control`, and the lists on /bots and /connections, cannot be changed this way.

On macOS the bot can do what a user does with the OS: `accessibility` lists the running apps and their windows (title, place, size), and `computer_click`, `computer_type`, `computer_key`, `computer_scroll`, `computer_drag`, `computer_move` (the window of another app, to a place and a size) and `computer_window` (minimize, restore or maximize that window) act on them, each after Accept in the bubble. macOS has to allow it once: Accessibility for the app that runs the widget (a prompt shows the first time), and Automation for System Events. Until then the tool says what to allow. `move_me` moves this widget itself, and is asked of the widget, because only the widget may touch its own windows.

Secrets live in the OS keychain (`/vault` adds, lists by id and deletes them). The bot never sees a value: `vault_list` gives ids and variable names, and a shell command that names one, such as `$VAULT_GITHUB_TOKEN` for the id `github-token`, runs with the value in its environment after an Accept that names the secret (every time, no Always allow). Output and errors have the value replaced by the variable name before the bot reads them. A command that encodes the value before printing it gets around that replacement, so read the command before you accept. Only `shell` gets secrets, not `shell_background`.

What the bot says while it works is not its answer. A step that calls tools is progress: its text goes to the cloud as a thought line. Only the text of the step that ends the turn is the answer, one message with its own id, and a notice from the harness (a loop it stopped, the step limit) is another message, so nothing glues together. A closing message is sent back once per reason when it promises work, claims work that no tool in the turn could have done, ignores a failed tool, or skips a tool the user named; `harness/agent/turn.py` holds those checks, each with a limit so a turn always ends. Chrome asks the user to Allow every new connection and cannot remember the answer, so a connection is kept and shared: the browser tools use the browser-use daemon's when it runs (it outlives the agent, so one Allow serves `browser_exec` and `browser_tabs` until the daemon stops), else one of their own per agent, and the demo asks the agent to count Chrome's tabs instead of connecting itself.

```json
"env": {
  "HARNESS_JOB_HOOK": "python3 -c 'import sys; sys.stdin.read()'",
  "HARNESS_JOB_HOOK_URL": "http://127.0.0.1:9/hook",
  "HARNESS_JOB_HOOK_KEY_FILE": "~/.config/llm/hook-token"
}
```

- The hook command (`HARNESS_JOB_HOOK`) runs when a job exits. The JSON payload is its standard input. Leave it out and no command runs
- The webhook (`HARNESS_JOB_HOOK_URL`) receives the same JSON. Leave it out and nothing is called
- The key file (`HARNESS_JOB_HOOK_KEY_FILE`) is a path to a file with the bearer token for that webhook. The token stays out of this config
- The job limit (`HARNESS_JOB_MAX`) is how many jobs may run at once. Unset means 4
- The tail (`HARNESS_JOB_TAIL`) is how many characters of output are kept, from the end. Unset means 4000
- The timeout (`HARNESS_JOB_TIMEOUT`) is an optional number of seconds after which a job is killed. Unset means it runs until it exits or the bot cancels it

A hook set here is trusted, because you wrote it, the same way the bot's start command is. It still cannot run a command the shell tool always refuses. A hook the bot adds on one job is part of the permission question for that job. A hook that fails is logged and the bot keeps going. The payload is the job id, the command, the exit code, how long it ran, and a short tail of the output.

The bot asks before it writes, edits or deletes a file and before a shell command that is not read-only. Reading is free in any folder, except private files such as `.env` and `.ssh`. The Permission button on the edit page sets what an Accept leaves behind.

```json
"env": {
  "HARNESS_WORKSPACE_PERMISSIONS": "allow"
},
"approve": {
  "/^shell git (status|diff|log)\\b/": true,
  "write_file /home/you/notes/": true,
  "/\\.env\\b/i": false,
  "shell rm": false
}
```

- Permission `ask` asks every time
- Permission `allow_session` remembers an Accept until the agent stops
- Permission `allow` remembers it for good, in `approvals.json`. It is the default for a new bot
- Remembering covers the same tool in the same folder and the folders below it. For a shell command it covers the same command prefix, such as `git status`
- A write or delete outside the workspace folder is allowed too, and its question says so
- The `approve` object is written by hand. Each key is a start of the text `tool target`, such as `shell git status` or `write_file /home/you/notes/a.md`
- Wrapped in slashes a key is a regular expression searched in that text, and `/i` ignores case
- Always allow is never offered for a program that runs other code or other commands, in any version: `python3.12`, `node`, `uv`, `timeout`, `kill` and the like. Allow one of those by hand with an anchored regex, for example this key in `approvals.json`, where a backslash is written twice: `"/^shell python3 scripts/parking\\.py book \\d{4}-\\d{2}-\\d{2}( |$)/": true`
- Value `true` runs without asking. Value `false` always asks, and it wins over `true` and over anything that was remembered
- A shell command with several parts, such as `a && b`, is approved only when each part is
- Always allow on such a command saves every part, and is offered only when each part can be saved. A part such as `python` or a redirect takes the offer away. `cd` never needs saving

```json
{
  "*": {"shell git status": true, "shell rm": false},
  "Local Bot": {"browser_exec": true}
}
```

- The file is `approvals.json` in `~/.local/share/botwidget/harness`
- The key `*` holds the rules of every bot. Any other key is the name of one bot, as in `HARNESS_BOT`
- Value `true` runs without asking. Value `false` always asks, and it wins over `true`
- Always allow and Permission `allow` add `true` rules under the bot's name
- Instead of `approved.json` per bot, which older versions wrote, one file holds it all. The old files are moved in at the next start and renamed to `approved.json.migrated`
- Rules from `approve` in the bot's `widget.json` entry still count. `shell-allow.json` is separate and not on the page

Extra instructions and skills come from folders and files of your choice, set in the `env` of the bot.

```json
"env": {
  "HARNESS_CONTEXT_PATHS": "~/.agents/skills:~/notes/bot-rules.md"
}
```

- Paths are separated like `PATH`: a colon on macOS and Linux, a semicolon on Windows
- A bot added from the widget starts with none: skills and instructions cost context in every request, so add the paths you want. A bot that already exists keeps what it has. A path that is not there is skipped
- A file is read as instructions and goes into every request
- A folder gives its `AGENTS.md`, `CLAUDE.md` or `.clinerules` as instructions
- A folder that holds a `SKILL.md`, or folders that each hold one, gives skills
- A skill is listed by name, description and path. The bot reads its `SKILL.md` when the task matches
- Each skill is also a slash command, such as `/parking`. Typing it starts the skill in a session of its own: the skill's whole text and a short brief of the conversation, picked out by the model (a short conversation goes along as it is), not the conversation itself. What you type after the name stays in the message
- What the skill says shows in the same chat and is kept in the conversation of the bot. A question of the skill is answered by typing in the chat; your answers go to the skill until it is done
- A skill ends by itself: when the bot calls `done`, when your message has nothing to do with it (the bot calls `not_for_me` and the chat answers it), when you cancel the turn, or after ten minutes of waiting for you. You never have to say that you are done. A background command that finishes while the skill runs reports to the skill
- A skill can name tools it must not get, with `deny-tools: browser_*, shell_background` in its front matter (names or globs, comma separated). The bot does not see them while that skill runs and has them back in the chat. Only this agent reads that line; other programs that read the same `SKILL.md` ignore it
- While a skill runs the bot has three extra tools, `done`, `wait_for_user` and `not_for_me`. A message that ends without a tool call, such as only "let me look", is not the end of the skill: the bot is told twice to go on, or to call one of them
- The text of the instructions is cut at `HARNESS_RULES_MAX_CHARS`, and the skill list at 4000 characters
- The bot reads the skill file itself, which it may do in any folder. Nothing in a skill runs by itself
- Edit widget.json on the `/bots` page saves this and restarts only that bot

A model server for the example above is llama.cpp:

```sh
llama-server -m ~/models/qwen2.5-7b-instruct-q4_k_m.gguf --port 8080 --alias local \
  --ctx-size 32768 --api-key "$(cat ~/.config/llm/key)"
```

The server then answers on `http://127.0.0.1:8080/v1`, and the model name to ask for is `local`. Without `--api-key` the same URL works with an empty key file. With no `HARNESS_MODEL_BASE_URL` the widget assumes exactly this server and model; when nothing answers there, the turn stops with a line that says the server could not be reached instead of waiting.

## The browser

A bot that runs the lean agent can read the tabs of the Chrome that is already open, with your logins. Chrome has to allow it once.

```text
chrome://inspect/#remote-debugging
```

- Tick the box on that page
- Chrome shows Allow remote debugging when the bot first connects. Answer Allow
- The bot keeps that one connection, so Chrome asks once and not for every message
- Instead of a permanent Allow, Chrome has no such setting, so it asks again after the widget restarts
- Chrome and Chromium work. Edge, Brave and Firefox do not yet

Then ask the bot, for example, which tabs are open. The tool behind that is `browser_tabs`, and `browser_read` gives the text of one tab, picked by a part of its title. Both only read. Neither opens a window or a page.

On macOS the widget finds Chrome through the system, so it needs no Full Disk Access. Linux and Windows read Chrome's `DevToolsActivePort` file instead, and are not tried yet.

Clicking, filling in forms and scrolling are not built in. Rather than waiting for that, add browser-use as the MCP server of the bot, in the `env` of its entry in `widget.json`.

```json
"env": {
  "HARNESS_MCP_SERVER": "uvx --python 3.12 browser-use@latest --cli-mcp"
}
```

- The command starts on your machine and drives the same Chrome. A cloud browser only starts after `browser_login`
- The server adds `browser_exec`, `browser_screenshot`, `browser_login` and `browser_feedback`
- Python that the model writes runs in `browser_exec`, so each call asks first. Leave `HARNESS_MCP_READ_ONLY` out
- Decline `browser_login` and `browser_feedback`. The first is for the cloud, and the second sends text to the vendor
- Each bot takes one MCP server. Instead of a second one for the same bot, add another bot with its own server
- The `uvx` command comes with uv, and `@latest` fetches the newest version at every start
- Instead of `uvx` alone, write its full path when the widget starts at login, because it may not have your shell's PATH
- Edit widget.json on the `/bots` page saves this and restarts only that bot
- A small local model may not pick these tools by itself. Name the tool in the question, such as "use browser_exec to scroll down"

## Talking to a bot from a shell

With remote control on, a running widget answers a few commands in a terminal, so a script or another agent can talk to the bot you see in the bubble. It is the same session and the same conversation. It is off until `widget.json` has `"remote_control": true` (edit it on the /settings page, or in the file) and the widget has restarted.

```bash
botwidget bots
botwidget ask acp:local "Say pong"
botwidget read acp:local
botwidget approve acp:local REQUEST_ID --as stefan
botwidget decline acp:local REQUEST_ID --as stefan
```

- Bots lists the ids of the bots that are running
- Ask sends the text, waits until the bot is done (at most 5 minutes) and prints what it said
- Read prints the conversation, the activity, the approvals that wait and the grey note under the conversation, as JSON
- Approve and decline answer a question that waits, by the request id that Read and Ask show
- The argument --as is required and names who answered

Instead of a command line interface of its own, the widget serves these calls on 127.0.0.1 from a thread. The port and a token are in `bot_widget_remote.json` in the temp folder, readable by you only.

- Ask stops and says so when the bot needs an approval, and prints the command that answers it
- A question that nobody answers within 10 minutes is declined
- The bubble does not animate for a message sent this way, the conversation is there when you open it
- With the widget not running the commands say so and exit

Every answer to a question is logged, whoever gave it.

```json
{"at": "2026-11-11 22:40:03", "request": "write_file /tmp/bot-probe/hello.txt", "decision": "accepted", "source": "cli", "by": "claude"}
```

- The file is `approvals.jsonl` in `~/.local/share/botwidget/harness`
- The source is bubble, cli or timeout
- The widget writes the file, the bot has an approval_log tool that only reads it

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
- A crash retries with backoff and fast-forwards origin/main first when the checkout is clean
- Starting at login from a checkout starts it in this mode too, so each login shows the latest iteration

Without a virtual environment, `uv venv && uv pip install -e .` and `.venv/bin/botwidget --dev` do the same.

### Switching between stable and local

Keep the installed app next to your checkout and hop between them from the /settings page.

- /settings, Switch to local version starts the checkout, and Switch to stable version starts the installed app
- The stable app learns how to start your checkout the first time you run it with `botwidget --dev`
- Start at login follows whichever version you switch to, so only one of them starts at login
- The installed app is found in Applications on macOS, in the local share folder on Linux and in the Start menu folder on Windows

On Linux the installer names its command `bot-widget` so it does not clash with the `botwidget` command from `uv tool install`.

- Unit tests need no display and no Qt, run them with `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -t .`, or `.venv/bin/python scripts/test-fast` for the same tests in parallel (about 50 seconds instead of 3 minutes on 10 cores; `TEST_JOBS` sets the number of processes)
- A repeated answer, a leaked tool name, or a skill-nudge sentence is fixed in one place, `harness/stream_text.py`. Each of those is also a fixture under `tests/replay/`: the raw events a backend emitted, and the bubble text they must become. The replay test runs every fixture through the agent

To replay a real chat without committing it, point the log outside the checkout and turn that log into a fixture. The fixture lands in `/tmp/botwidget-replay/` unless you pass another path, and a path inside the checkout is refused.

```sh
BOTWIDGET_REPLAY_LOG=/tmp/botwidget-replay/live.jsonl botwidget --dev
.venv/bin/python scripts/replay_capture /tmp/botwidget-replay/live.jsonl
BOTWIDGET_REPLAY_DIR=/tmp/botwidget-replay QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.replay.test_replay
```

- The log is one JSON object per line: a model step, a text chunk, a tool name, or the text the bubble received. The widget passes `BOTWIDGET_REPLAY_LOG` through to the agent. Leave it unset and nothing is written
- The source can also be a harness session folder. That folder keeps the stored answer, not the chunks, so each bot line becomes one final event
- The bubble field in the written file is what the stage shows today. Change it when that text is wrong, then run the replay again. Copy a fixture into `tests/replay/` only after the text is synthetic
- `git config core.hooksPath .githooks` runs that command before a push of main and rejects the push when the tests fail
- Everything that differs per operating system lives in `botwidget/system/`, one module per OS with the same function names
- Everything that touches Qt lives in `botwidget/qt_ui/`
- `BOT_WIDGET_OPENBOT_DIR` points the widget at another OpenBot data folder, handy for testing

### Testing on Linux from a Mac

Some tests are skipped on macOS and only run on Linux and Windows, so a green run on your Mac can still fail on GitHub. When the GitHub run shows a failing Linux test, run the Linux job in Docker to reproduce it and to check the fix before you push again.

```sh
scripts/test-linux
```

- Docker needs a running engine, for example OrbStack (`orb start`), which you stop afterwards with `orb stop`
- Rather than start or stop OrbStack while the script runs, wait until it has finished: an engine that stops in the middle shows up as `Error waiting for container: Canceled: grpc: the client connection is closing`, which is no failing test
- It tests the last commit (`git archive HEAD`), so what is not committed is not in it
- The container is `python:3.12` with the Qt libraries from the ubuntu job in ci.yml, and the package is installed like a user would
- The output is the failing tests and the summary line, and the script exits with the status of the tests
- Windows cannot run this way, only GitHub runs it

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

### Windows through SignPath

Bot Widget is applying to SignPath Foundation for free code signing of open-source projects. The release workflow is ready for it and does nothing until it is set up:

- Secret `SIGNPATH_API_TOKEN`; variables `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG`, `SIGNPATH_SIGNING_POLICY_SLUG`, `SIGNPATH_FILES_CONFIG_SLUG` and `SIGNPATH_SETUP_CONFIG_SLUG`
- The two artifact configurations to create in SignPath are in `packaging/signpath/`
- Request 1 signs `Bot Widget.exe` and Inno Setup's uninstaller, then the installer is built around them; request 2 signs `BotWidget-Windows-Setup.exe`
- Only our own binaries are signed. Files from other projects (Python, Qt) keep the signature they come with
- Every signing request is approved by hand in SignPath before the release goes out

### Microsoft Store (MSIX)

An unsigned MSIX package can be built with:

```sh
python packaging/build.py --msix
```

It reads `packaging/msix.json` (identity, publisher, version) and produces
`dist/BotWidget-Windows.msix` from the PyInstaller app folder. The Microsoft
Store signs the package, so this is unsigned and ready for upload to Partner
Center.

Before building, set three repository variables (Settings > Secrets and
variables > Actions > Variables) from Partner Center > Product identity:

- `MSIX_IDENTITY_NAME` – e.g. `MyCorp.BotWidget`
- `MSIX_PUBLISHER` – e.g. `CN=xxxxxxxx-...`
- `MSIX_PUBLISHER_DISPLAY_NAME` – e.g. `MyCorp`

The release workflow builds the MSIX on tag pushes and publishes
`dist/BotWidget-Windows.msix` as the `BotWidget-Windows.msix` artifact.
Upload it in Partner Center as a new submission.

The website keeps distributing the Inno Setup installer (or zip if Inno is
missing) for direct download; the MSIX is a Store-only channel.

### Windows Authenticode (SmartScreen)

Unsigned Windows builds show SmartScreen. There is no code bypass; a signed installer earns reputation over time.

1. Buy a **standard** Authenticode code-signing certificate from a public CA (Sectigo, DigiCert, SSL.com, and similar). An **EV** certificate is optional: it can skip SmartScreen sooner, but a standard cert is enough once reputation builds.
2. Export a password-protected `.pfx`. Do not commit it.
3. Base64-encode the file and set GitHub Actions secrets on `Menziess/bot-widget`: `WINDOWS_CERTIFICATE` (the base64) and `WINDOWS_CERT_PASSWORD`.
4. Push a new tag so the release workflow signs both `Bot Widget.exe` and `BotWidget-Windows-Setup.exe`.

Do not invent a certificate or spend money from this repo. Until those secrets exist, Windows downloads stay unsigned: in SmartScreen choose **More info**, then **Run anyway**.

## Code signing policy

Windows releases are to be signed with free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by [SignPath Foundation](https://signpath.org/). Until approved, Windows downloads are unsigned.

- Committers and reviewers: [Stefan Schenk (Menziess)](https://github.com/Menziess)
- Approvers: [Stefan Schenk (Menziess)](https://github.com/Menziess)

Every signed file is built by GitHub Actions from this repository (`.github/workflows/release.yml`), and each signing request is approved by hand.

### Privacy

Bot Widget talks to the bot apps on your own computer (OpenBot, Grok Bot). On its own it only asks GitHub (`api.github.com`) whether there is a newer release, and downloads that release from GitHub Releases; Check for updates on the /settings page switches that off. [GitHub's privacy statement](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement) applies to those requests. Anything else, such as /feedback opening a GitHub issue in your browser, only happens when you ask for it.
