# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local Iron Man–style voice dashboard: a canvas HUD in the browser, `claude -p` as the brain, and Fish Audio for the voice. No build system, no tests, no pip installs — `server.py` and `speak.py` are deliberately **Python stdlib only**; keep them that way. Node.js is used only to evaluate `jarvis_data.js`.

## Commands

```
copy jarvis_data.example.js jarvis_data.js   # first-time setup; edit with real data
set FISH_API_KEY=your_key_here               # no quotes — both scripts strip them, but don't rely on it
python speak.py                              # regenerate jarvis_brief.mp3 from jarvis_data.js
python speak.py --no-play                    # same, without playing it
python speak.py "Custom text."               # speak arbitrary text
python server.py                             # serve dashboard + POST /ask on port 8765
```

Open http://localhost:8765/dashboard.html — must be served from localhost, not opened as a file, or the microphone won't work. To test `/ask` without a mic or API key, POST JSON: `{"text": "question"}` (text-only works with no `FISH_API_KEY`; you just get no audio back).

## Architecture

Everything hangs off one data file, `jarvis_data.js` (git-ignored — may contain personal Gmail/Calendar data; `jarvis_data.example.js` is the schema and stays fictional). Three independent consumers read it:

1. **`dashboard.html`** — single self-contained file (CSS + canvas HUD + all JS). Renders the HUD panels from `window.JARVIS_DATA`, drives the ~680-point Fibonacci sphere animation, and handles both voice paths: browser Web Speech API (free, preferred) with a MediaRecorder→server-side Fish ASR fallback.
2. **`server.py`** — stdlib `ThreadingHTTPServer`. `POST /ask` pipeline: transcribe (Fish ASR, only for the fallback path) → `ask_claude()` runs `claude -p` with the JARVIS persona → Fish TTS → JSON reply with base64 MP3.
3. **`speak.py`** — composes the "BRIEF ME" narration text from the data (evaluated via `node -e`) and writes `jarvis_brief.mp3` (git-ignored), which the dashboard's BRIEF ME button plays.

Things that follow from this shape:

- The persona (`load_persona()` in `server.py`) embeds the raw contents of `jarvis_data.js` and is loaded **once at import time** — restart `server.py` after editing the data, and rerun `speak.py` to keep the spoken brief in sync.
- `FISH_MODEL`/`MODEL` and `VOICE_ID` are duplicated in `server.py` and `speak.py`; change both together.
- Data-shape changes must be reflected in three places: the HUD rendering in `dashboard.html`, `compose_brief()` in `speak.py`, and `jarvis_data.example.js`.

## Security constraint

`ALLOWED_TOOLS` in `server.py` is the whitelist of MCP connector tools `claude -p` may call without a permission prompt. It is **read-only on purpose** (search/get/list only — nothing that sends, creates, edits, or deletes), because anything on it can be triggered by a voice command. Do not add write-capable tools unless the user explicitly asks and understands that trade-off. Similarly, the Fish API key comes only from the `FISH_API_KEY` env var — never hardcode it.
