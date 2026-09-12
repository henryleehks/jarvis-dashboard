# J.A.R.V.I.S. Dashboard

A cinematic Iron Man–style voice command center that runs entirely on your machine.
A glowing 3D energy sphere, HUD panels fed by live data, and a full voice loop:
speak to it, it thinks with [Claude Code](https://claude.com/claude-code), and it
answers aloud in a British butler voice.

## Features

- **Animated HUD** — ~680-point Fibonacci sphere with pulsing core, orbital ring,
  rotating dashed arcs, tick ring, scanlines and vignette. Pure canvas, no libraries.
- **BRIEF ME** — plays a spoken morning brief composed live from `jarvis_data.js`
  (revenue, funnel, offline connectors, priorities).
- **ASK JARVIS** — click, speak, get a spoken answer. The browser's Web Speech API
  transcribes for free; the question runs through `claude -p` with a JARVIS persona;
  the reply is voiced by [Fish Audio](https://fish.audio) TTS.
- **Connector access** — Claude can consult Gmail, Google Calendar, Google Drive and
  Notion (read-only) to answer questions like *"what's on my calendar tomorrow?"*
- **REFRESH** — pulls your real unread mail and next seven days of calendar through
  those same read-only connectors, rewrites `jarvis_data.js`, re-records the brief
  and reloads the HUD. Point a scheduled task at it for a dashboard that wakes up
  current every morning.
- The sphere pulses to a synthetic speech envelope while JARVIS talks.

## Requirements

- Python 3 (stdlib only — no pip installs)
- Node.js (used to evaluate `jarvis_data.js`)
- [Claude Code](https://claude.com/claude-code) CLI, logged in
- A [Fish Audio](https://fish.audio) API key (TTS uses the free `s2.1-pro-free` model)

## Quick start

```
copy jarvis_data.example.js jarvis_data.js   # then edit with your own data
set FISH_API_KEY=your_key_here
python speak.py      # generate jarvis_brief.mp3 (the BRIEF ME narration)
python server.py     # serve the dashboard + the /ask and /refresh endpoints
```

Open http://localhost:8765/dashboard.html — it must be served from localhost
(not opened as a file) for the microphone to work.

To refresh the data on a schedule rather than by clicking REFRESH, point a task
at the endpoint while the server is running — on Windows, a Task Scheduler entry
running `powershell -Command "Invoke-RestMethod -Method Post http://localhost:8765/refresh"`.
A refresh takes a minute or two, since Claude is reading your mail and calendar
before it answers.

## How it fits together

```
dashboard.html ── mic/speech ──> POST /ask ─────> server.py
                                                    ├─ claude -p  (the brain, with persona + live data)
                                                    └─ Fish Audio TTS  (the voice)
dashboard.html ── REFRESH ─────> POST /refresh ──> server.py
                                                    ├─ claude -p  (read-only Gmail/Calendar -> JSON)
                                                    └─ rewrites jarvis_data.js + jarvis_brief.mp3
jarvis_data.js ── feeds the HUD, the brief (speak.py) and the persona
```

- `jarvis_data.js` — single data feed (copy of `jarvis_data.example.js`,
  git-ignored since it may hold personal Gmail/Calendar details). Edit it by hand
  or let REFRESH generate it; the brief and persona pick it up automatically.
  Each refresh keeps the previous version as `jarvis_data.js.bak`.
- `speak.py` — composes the brief text from the data and synthesizes the MP3.
- `server.py` — stdlib HTTP server: serves statics, transcribes audio (fallback
  path, Fish ASR), runs `claude -p`, returns the reply plus base64 MP3, and
  rewrites the feed on `/refresh`.

## Notes

- The API key is read from the `FISH_API_KEY` environment variable only — never
  committed. `.env` is git-ignored.
- Connector access is deliberately **read-only** (`ALLOWED_TOOLS` in `server.py`):
  JARVIS can search mail and read your calendar, but nothing on the whitelist can
  send, create, edit or delete. Add write tools there only if you accept that a
  voice command can then modify your accounts.
- `/refresh` is the only thing that writes: the connectors stay read-only, and
  what comes back is parsed, bounded and re-serialised before it reaches
  `jarvis_data.js`. Still, the values originate in email subject lines and
  calendar titles, so read the HUD as a display, not as a source of truth.
- Speech-to-text uses the browser's built-in recognition (free, Chrome/Edge).
  Browsers without it fall back to recording audio for server-side Fish ASR,
  which is a paid Fish Audio feature.
