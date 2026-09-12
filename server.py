"""J.A.R.V.I.S. local server.

Serves the dashboard at http://localhost:8765 and exposes two endpoints.

POST /ask:

  1. Accepts recorded audio (any audio/* body) or JSON {"text": "..."}.
  2. Audio is transcribed with Fish Audio ASR.
  3. The question runs through `claude -p` with a JARVIS persona
     (primed with the live jarvis_data.js contents).
  4. The reply is converted to speech with Fish Audio TTS (British voice)
     and returned as base64 MP3 alongside the text.

POST /refresh:

  1. `claude -p` reads Gmail/Calendar/Drive/Notion through the same read-only
     tools and returns the dashboard feed as JSON.
  2. The JSON is sanitised and written to jarvis_data.js.
  3. The persona is reloaded and jarvis_brief.mp3 regenerated, so /ask and
     BRIEF ME both speak from the new data without a restart.

Usage:
    set FISH_API_KEY=your_key_here
    python server.py

Stdlib only — no pip installs.
"""
import base64
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8765
DATA_FILE = os.path.join(ROOT, "jarvis_data.js")
BRIEF_FILE = os.path.join(ROOT, "jarvis_brief.mp3")

FISH_TTS_URL = "https://api.fish.audio/v1/tts"
FISH_ASR_URL = "https://api.fish.audio/v1/asr"
FISH_MODEL = "s2.1-pro-free"
VOICE_ID = "36b6f66cfecf466caac7fcba1f8b59c8"  # British voice
FISH_KEY = os.environ.get("FISH_API_KEY", "").strip(" \t\r\n\"'")

# Model the JARVIS brain runs on. Pinned so JARVIS uses Opus regardless of the
# `claude` CLI's global default. Override with the JARVIS_MODEL env var if needed.
CLAUDE_MODEL = os.environ.get("JARVIS_MODEL", "claude-opus-4-8").strip(" \t\r\n\"'")

# Connector tools `claude -p` may use without an interactive permission prompt.
# Read-only on purpose: nothing here can send mail, change events, or edit
# pages. Add write tools (create_event, create_draft, ...) only if you accept
# that a voice command can then modify your accounts.
#
# WebSearch/WebFetch are Claude Code's own built-in tools (not MCP connectors),
# so they need no separate setup — they let JARVIS answer "what's the latest..."
# style questions. Both are read-only: they retrieve public web content and
# cannot change anything on your accounts.
ALLOWED_TOOLS = [
    "WebSearch",
    "WebFetch",
    "mcp__claude_ai_Gmail__search_threads",
    "mcp__claude_ai_Gmail__get_message",
    "mcp__claude_ai_Gmail__get_thread",
    "mcp__claude_ai_Gmail__list_drafts",
    "mcp__claude_ai_Gmail__list_labels",
    "mcp__claude_ai_Google_Calendar__list_calendars",
    "mcp__claude_ai_Google_Calendar__list_events",
    "mcp__claude_ai_Google_Calendar__get_event",
    "mcp__claude_ai_Google_Calendar__suggest_time",
    "mcp__claude_ai_Google_Drive__search_files",
    "mcp__claude_ai_Google_Drive__list_recent_files",
    "mcp__claude_ai_Google_Drive__read_file_content",
    "mcp__claude_ai_Google_Drive__get_file_metadata",
    "mcp__claude_ai_Notion__notion-search",
    "mcp__claude_ai_Notion__notion-fetch",
    "mcp__claude_ai_Notion__notion-query-data-sources",
    "mcp__claude_ai_Notion__notion-query-database-view",
    "mcp__claude_ai_Notion__notion-query-meeting-notes",
    "mcp__claude_ai_Notion__notion-get-comments",
]


def read_data_file():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def load_persona():
    data = read_data_file()
    return (
        "You are J.A.R.V.I.S., Tony Stark's AI butler, now assisting Henry. "
        "Reply in a composed, dryly witty British register; address the user as "
        "'sir' occasionally. Keep replies to 1-3 short sentences of plain prose — "
        "they will be spoken aloud, so no markdown, lists, or code. "
        "You have read-only access to Henry's Gmail, Google Calendar, Google "
        "Drive and Notion via your tools; consult them when the question calls "
        "for it, and summarise rather than reading entries verbatim. "
        "You can also search the web (WebSearch) and read web pages (WebFetch) "
        "for current information — use them when the question needs up-to-date "
        "facts you don't already know, and give a concise spoken answer. "
        "Current dashboard state follows; use it when relevant:\n\n" + data
    )


PERSONA = load_persona()


def fish_request(url, data, headers):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def transcribe(audio_bytes, mime):
    if not FISH_KEY:
        raise RuntimeError("FISH_API_KEY not set — cannot transcribe audio")
    boundary = uuid.uuid4().hex
    body = b"".join([
        ("--%s\r\nContent-Disposition: form-data; name=\"audio\"; "
         "filename=\"question.webm\"\r\nContent-Type: %s\r\n\r\n"
         % (boundary, mime)).encode(),
        audio_bytes,
        ("\r\n--%s--\r\n" % boundary).encode(),
    ])
    raw = fish_request(FISH_ASR_URL, body, {
        "Authorization": "Bearer " + FISH_KEY,
        "Content-Type": "multipart/form-data; boundary=" + boundary,
    })
    return json.loads(raw).get("text", "").strip()


def synthesize(text):
    if not FISH_KEY:
        return None
    body = json.dumps({"text": text, "reference_id": VOICE_ID, "format": "mp3"})
    return fish_request(FISH_TTS_URL, body.encode("utf-8"), {
        "Authorization": "Bearer " + FISH_KEY,
        "Content-Type": "application/json",
        "model": FISH_MODEL,
    })


def run_claude(prompt, system_prompt, timeout=180):
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("claude CLI not found on PATH")
    cmd = [exe, "-p", "--output-format", "text",
           "--model", CLAUDE_MODEL,
           "--allowedTools", ",".join(ALLOWED_TOOLS),
           "--append-system-prompt", system_prompt]
    if exe.lower().endswith((".cmd", ".bat")):
        cmd = ["cmd", "/c"] + cmd
    result = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "claude -p failed").strip()[:400])
    return result.stdout.strip()


def ask_claude(question):
    return run_claude(question, PERSONA)


# ----------------------------------------------------------------------------
# Data refresh — the same read-only tools, writing the dashboard feed
# ----------------------------------------------------------------------------

REFRESH_TIMEOUT = 300  # gathering mail + calendar takes longer than a question
REFRESH_LOCK = threading.Lock()

COLLECTOR_SYSTEM = (
    "You are the data collector for the J.A.R.V.I.S. dashboard. Gather the "
    "facts with your read-only Gmail, Google Calendar, Google Drive and Notion "
    "tools, then reply with one JSON object and nothing else — no prose, no "
    "markdown fences, no commentary before or after."
)


def build_refresh_prompt():
    """The collector brief: what to gather, and the shape to return it in.

    The previous feed is the schema by example — far more reliable than
    describing the shape in prose, and it keeps the HUD's house style stable
    across refreshes.
    """
    previous = read_data_file() or "(no previous feed — use your judgement)"
    return (
        "Refresh the dashboard feed. Local time is now %s.\n\n"
        "Gather:\n"
        "  - Gmail: how many unread threads sit in the inbox, and which of "
        "them are genuinely actionable (real people, deadlines, security "
        "alerts) rather than newsletters, promotions and job alerts.\n"
        "  - Google Calendar: events on the primary calendar from today "
        "through seven days out.\n"
        "  - Any hard deadline mentioned in the mail that is not on the "
        "calendar — carry it until it has passed or is clearly done.\n\n"
        "Then return the feed as a single JSON object. The previous version "
        "follows: keep its exact shape and key names, and its house style — "
        "short uppercase labels, and JARVIS's dry, composed British register "
        "in `greeting`, `priorities` and `closer`. Replace every value with "
        "what you just found, and drop whatever has passed. `headline` should "
        "track the single most pressing commitment, and each `content.funnel` "
        "bar needs a sensible `max` so it reads as a proportion. Omit "
        "`generated`; it is stamped on write.\n\n"
        "=== previous feed ===\n%s"
        % (time.strftime("%A %d %B %Y, %H:%M"), previous)
    )


def extract_json(text):
    """Pull the JSON object out of a model reply, fences and all."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise RuntimeError("collector reply contained no JSON object")
    return json.loads(text[start:end + 1])


# Bounds for sanitize(). Generous enough for a real feed, tight enough that a
# runaway reply can't produce a multi-megabyte data file.
MAX_STRING = 400
MAX_ITEMS = 64
MAX_DEPTH = 8


def sanitize(value, depth=0):
    """Rebuild the collector's output as plain, bounded JSON data.

    The result is written to a .js file the browser executes, and its values
    come from email subject lines and calendar titles — text other people
    write. Reconstructing it here (rather than trusting the reply) is what
    guarantees only inert data reaches the page.
    """
    if depth > MAX_DEPTH:
        return None
    if isinstance(value, str):
        return value[:MAX_STRING]
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        return [sanitize(v, depth + 1) for v in value[:MAX_ITEMS]]
    if isinstance(value, dict):
        return {str(k)[:MAX_STRING]: sanitize(v, depth + 1)
                for k, v in list(value.items())[:MAX_ITEMS]}
    return None


def write_data_file(data):
    """Write jarvis_data.js, keeping the previous copy as .bak.

    The feed is git-ignored, so a bad refresh would otherwise be unrecoverable.
    json.dumps escapes non-ASCII (U+2028 included), which keeps the file
    byte-safe however the browser guesses its encoding; the angle brackets are
    escaped on top of that so a subject line reading "</script>..." stays inert
    even if this data is ever inlined into the page rather than linked.
    """
    body = (json.dumps(data, indent=2)
            .replace("<", "\\u003c").replace(">", "\\u003e"))
    js = ("// J.A.R.V.I.S. command center - data feed.\n"
          "// Written by POST /refresh at %s. Hand edits are overwritten.\n"
          "// NOTE: contains personal data - never commit this file.\n"
          "window.JARVIS_DATA = %s;\n"
          % (time.strftime("%Y-%m-%d %H:%M:%S"), body))
    if os.path.exists(DATA_FILE):
        shutil.copyfile(DATA_FILE, DATA_FILE + ".bak")
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(js)
    os.replace(tmp, DATA_FILE)  # atomic: the browser never sees a half-file


def regenerate_brief(data):
    """Re-record jarvis_brief.mp3 so BRIEF ME matches the new data."""
    try:
        import speak  # local module; optional, so imported at point of use
        audio = synthesize(speak.compose_brief(data))
        if not audio:
            return False
        with open(BRIEF_FILE, "wb") as f:
            f.write(audio)
        return True
    except Exception as e:  # a silent brief beats a failed refresh
        print("  brief regeneration failed:", e)
        return False


def refresh_data():
    """Pull fresh data, rewrite the feed, and resync everything that reads it."""
    if not REFRESH_LOCK.acquire(blocking=False):
        raise RuntimeError("a refresh is already running")
    try:
        reply = run_claude(build_refresh_prompt(), COLLECTOR_SYSTEM,
                           REFRESH_TIMEOUT)
        data = sanitize(extract_json(reply))
        if not isinstance(data, dict) or not data:
            raise RuntimeError("collector returned no usable data")
        # Stamped here rather than taken from the reply: the clock is ours.
        data["generated"] = time.strftime("%d %b %Y · %H:%M").upper()
        write_data_file(data)
        global PERSONA
        PERSONA = load_persona()  # /ask answers from the new feed, no restart
        return data, regenerate_brief(data)
    finally:
        REFRESH_LOCK.release()


class Handler(SimpleHTTPRequestHandler):

    def end_headers(self):
        # live dashboard data — never let the browser serve stale files
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):
        path = self.path.rstrip("/")
        if path == "/ask":
            self.handle_ask()
        elif path == "/refresh":
            self.handle_refresh()
        else:
            self.send_error(404)

    def handle_ask(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()

            if ctype == "application/json":
                question = json.loads(raw).get("text", "").strip()
            else:
                question = transcribe(raw, ctype or "audio/webm")

            if not question:
                raise RuntimeError("could not make out the question")

            print("  Q:", question)
            reply = ask_claude(question)
            print("  A:", reply)

            audio = None
            try:
                audio = synthesize(reply)
            except (urllib.error.URLError, OSError) as e:
                print("  TTS failed:", e)

            payload = {
                "question": question,
                "reply": reply,
                "audio_b64": base64.b64encode(audio).decode() if audio else None,
            }
            self._json(200, payload)
        except Exception as e:  # keep the server alive on any pipeline failure
            print("  /ask error:", e)
            self._json(500, {"error": str(e)})

    def handle_refresh(self):
        try:
            print("  refreshing dashboard data...")
            data, brief = refresh_data()
            print("  data refreshed:", len(data), "sections;",
                  "brief re-recorded" if brief else "brief unchanged")
            self._json(200, {
                "generated": data.get("generated"),
                "greeting": data.get("greeting"),
                "brief": brief,
            })
        except Exception as e:  # keep the server alive on any pipeline failure
            print("  /refresh error:", e)
            self._json(500, {"error": str(e)})

    def _json(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))


def main():
    if not FISH_KEY:
        print("WARNING: FISH_API_KEY not set — /ask will work for typed text "
              "only, with no voice input or spoken replies.")
    handler = partial(Handler, directory=ROOT)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    print("J.A.R.V.I.S. online -> http://localhost:%d/dashboard.html" % PORT)
    print("  POST /ask      ask a question")
    print("  POST /refresh  pull fresh data into jarvis_data.js")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPowering down.")


if __name__ == "__main__":
    main()
