# What the widget needs from a backend

The widget never asks a backend for much. This page lists the calls that exist today, read from the code, and maps each to an ACP event so that a new adapter knows what to produce.

## The conversation

Every backend hands the widget one dictionary to draw from.

```python
{
    "messages": [{"role": "user", "text": "Klaar?"}, {"role": "bot", "text": "Ja."}],
    "activity": "Reading the tests",
    "failed": "",
}
```

Three keys are all the bubble needs.

- Messages, the lines of the conversation, oldest first, with a role of user or bot
- Activity, one short line while the bot works, empty when it is idle
- Failed, a short reason when the last turn failed, such as a spent provider

How the keys are used.

- A non-empty activity is what makes a face count as working, and so shows the thinking cloud
- The last bot message that differs from the one before triggers the answer sound
- The newest message decides whether the bubble opens by itself
- Messages are shown one at a time, and older ones load on request, so a backend returns a window of recent lines rather than everything

## Sending

A message goes out through one call that says whether it worked.

```python
ok, error = link.send("Hello")
```

Here the pair is the whole contract.

- Ok, true when the backend accepted the text
- Error, a short sentence in plain words when it did not

A few related facts.

- The widget keeps unsent lines in its own outbox and retries, so send has to be safe to call again with the same text
- Attachments travel as text, a list of file paths under a shared folder, appended to the message
- A message typed while the bot works is queued by the widget and sent after the turn, so the backend sees one turn at a time

## Staying in sync

The widget polls rather than listens, and only when there is a reason.

```python
link.due()          # is it time to look again
link.active()       # is a turn running
link.request_fetch()  # look once now, when the bubble opens
link.note()         # why the link stopped, or that a send is unsure
link.resume()       # a new message is a fresh attempt
```

Each call has a narrow job.

- Due and active keep the poll rate low while nothing is happening
- A fetch request is the one look when a bubble opens
- Note is a grey line under the conversation
- Resume lets a link that stopped try again

An event stream makes this simpler, because a pushed update replaces polling. The widget can keep the poll shape and fill the same dictionary from pushed events.

## Questions and approvals

Besides the conversation, OpenBot reports what waits for the user.

```python
{
    "prompts": [{"requestId": "r1", "questions": [{"id": "q1", "question": "Push?", "options": [...]}]}],
    "approvals": [{"requestId": "r2"}],
    "browserTakeovers": [],
}
```

The widget turns these into buttons.

- A prompt shows its options as buttons, or takes a typed answer from the field
- An approval shows Accept and Decline
- A takeover says that the user is needed in a browser, and stays OpenBot specific

The answer goes back by request id.

## Mapping to ACP

| Widget concept | ACP event or method |
| - | - |
| messages, bot | agent_message_chunk, joined by message id |
| messages, user | user_message_chunk on replay, or what the client itself sent |
| activity | agent_thought_chunk, or the title of a running tool_call |
| failed | The stop reason of the prompt response, or an error |
| send | session/prompt |
| stop a turn | session/cancel |
| approvals | session/request_permission |
| prompts | Elicitation |
| note | notice, when the client advertises it, else a message |
| older messages | Session replay when a session is loaded or resumed |
| context size | usage_update |

Gaps to decide on.

- ACP has no field for a short activity line, so the adapter derives it from the latest thought chunk or tool call title, cut to the length the bubble allows
- Browser takeovers have no ACP equivalent and stay with OpenBot
- A session needs a working directory, and the widget has none, so the adapter has to supply a fixed one per bot
- Permission requests for file and shell tools are common in coding agents, so a bot meant for chat should be started with those tools off

## What a new backend must do, as a checklist

- Accept text, and say plainly whether it was accepted
- Report the conversation so far, as a window of recent lines
- Say when it is working, with one short line
- Say when a turn failed and why
- Ask the user questions and for permission through the same channel
- Keep going when the widget is closed, and be there with the conversation when it opens again
