# Setups — Tanki Online draft

A Discord bot that runs a full pick & ban between two players. The bot announces
the match in the channel and hands each player a private link; the draft itself
happens on a web page served by this project.

```
/draft start @opponent
   ↓
channel message: scoreboard, whose turn it is, "Open my draft" button
   ↓
each player opens THEIR link  →  log on the left, clickable options on the right
   ↓
at the end, the result becomes the match record in the channel
```

## Running it

```bash
npm install
npm run deploy     # registers the commands on the server (only when they change)
npm start
```

`.env`:

| key | what for |
|---|---|
| `DISCORD_TOKEN` | bot token |
| `CLIENT_ID` | application id |
| `GUILD_ID` | where the commands are registered |
| `TUNNEL` | `1` opens a public address on startup |
| `BASE_URL` | fixed address (hosting); takes precedence over the tunnel |
| `PORT` | server port (default 3000) |
| `MAX_DRAFTS` | cap on simultaneous drafts (default 100) |
| `DRAFT_TTL_MS` | how long without activity ends a draft (default 2h) |
| `DATA_DIR` | where the archive is written (default `data/`) |

Without `TUNNEL=1` or `BASE_URL`, links point at `localhost` and only open on
this machine.

## Architecture

```
node index.js
├── bot (discord.js)   → commands, buttons, final record in the channel
├── server (express)   → the page, the API and the state stream
├── tunnel (cloudflared)→ public address, optional
└── src/draft/         → the engine, shared — knows neither Discord nor HTTP
```

| module | role |
|---|---|
| `src/draft/` | 26 steps, rules, catalog. Pure reducer: `applyAction` returns a new state or an error, never mutates |
| `src/flow.js` | the only place that changes a draft, and propagates the change afterwards |
| `src/server/view.js` | translates the state into the JSON the page draws |
| `src/server/stream.js` | WebSocket: pushes the state to open screens |
| `src/store/sessions.js` | drafts in progress, indexed by id, player and token |
| `src/store/archive.js` | finished drafts, on disk (JSON Lines) |
| `src/discord/board.js` | the channel message |
| `web/` | the page. No build, no framework |

## Decisions worth knowing

**The engine knows nothing about presentation.** That is why the project
survived swapping a Discord panel for a web page without a single rule being
rewritten.

**The page is deliberately dumb.** It receives the list of legal items ready to
draw and returns an id. Whoever is off turn receives no list at all — the
protection does not depend on client JavaScript. A locked card is not even a
`<button>`, so there is no click target in the DOM to bypass.

**A click chooses, a second gesture sends.** In a 26 step draft a misclick is
irreversible without `/draft undo`, so a move asks for confirmation. Double
click is the shortcut for whoever already knows what they want.

**Identity is the link token, not a login.** The bot sends `/d/<id>/<token>`;
the server swaps the token for an HttpOnly cookie and redirects to `/d/<id>/`.
The match URL carries no secret: it stays out of browser history, screenshots
and links pasted by mistake.

Whoever holds the redemption link plays that side. For two players who know
each other, that is enough. A real login (Discord OAuth) is the next step if it
ever stops being enough.

**One draft per player at a time.** Several drafts run at once, even in the same
channel — but the index is the player, otherwise `/draft cancel` would not know
which one it is talking about.

**WebSocket, not SSE.** The flow is one way — the server tells, the move comes
back over POST — so Server-Sent Events was the obvious pick, and it was the
first one. It does not survive the tunnel: Cloudflare buffers an HTTP response
body until about 128 KB before releasing the first byte, and a view is ~3 KB.
The connection opened, the server counted the page as subscribed, and the screen
stayed on "Loading…" forever.

No header fixes it: `X-Accel-Buffering: no` is an nginx convention and
Cloudflare strips it; `no-transform` and `Content-Encoding: identity` change
nothing. Measured on the same tunnel: 3 KB and 64 KB do not come out within 15s,
256 KB comes out in 237ms, WebSocket delivers in 309ms. The protocol upgrade
escapes because there is no longer a response body to buffer.

What was lost is the automatic reconnection of `EventSource` — the page now
retries on its own, doubling the wait up to 15s, and gives up when the server
closes with a private code (draft ended or invalid link).

**What finishes goes to two files, not one.**

```
data/completed.jsonl    only the result: who played, when, the 14 setups
data/unfinished.jsonl   the whole state, with history and bans, plus the reason
```

Two different questions. From a draft that reached the end, what matters is what
came out of it — the path there is not recorded. From one that died halfway,
the path is exactly what matters: without the history there is no telling where
it stopped or why.

The destination comes from the state's `status`, not from the `reason` passed by
the caller: reason is free text, and a typo would send a result to the wrong
file.

`DATA_DIR` swaps the directory — that is what lets the tests archive into a
temporary folder instead of writing to the real history.

## Discarded paths

**A component panel on Discord.** An image is not an interaction target in any
component — not `MediaGallery`, not a `Section` thumbnail. Clicking one only
opens the lightbox. And one button per item does not reach 33 paints: five per
row, and the message's 40 component cap blows first.

**A Discord Activity.** It would solve the clickable image, but it opens in its
own panel, outside the message list — the draft would stop happening in chat.

## Tests

```bash
npm test
```

They cover the engine (including a 300 draft fuzz run), the view, the server
gate over HTTP, concurrency between drafts, the archive split and the sweep of
abandoned drafts.
