"""J.A.R.V.I.S. local server.

Serves the dashboard at http://localhost:8765 and exposes POST /ask:

  1. Accepts recorded audio (any audio/* body) or JSON {"text": "..."}.
  2. Audio is transcribed with Fish Audio ASR.
  3. The question runs through `claude -p` with a JARVIS persona
     (primed with the live jarvis_data.js contents).
  4. The reply is converted to speech with Fish Audio TTS (British voice)
     and returned as base64 MP3 alongside the text.

Usage:
    set FISH_API_KEY=your_key_here
    python server.py

Stdlib only — no pip installs.
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8765

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


def load_persona():
    data = ""
    try:
        with open(os.path.join(ROOT, "jarvis_data.js"), encoding="utf-8") as f:
            data = f.read()
    except OSError:
        pass
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


def ask_claude(question):
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("claude CLI not found on PATH")
    cmd = [exe, "-p", "--output-format", "text",
           "--model", CLAUDE_MODEL,
           "--allowedTools", ",".join(ALLOWED_TOOLS),
           "--append-system-prompt", PERSONA]
    if exe.lower().endswith((".cmd", ".bat")):
        cmd = ["cmd", "/c"] + cmd
    result = subprocess.run(
        cmd, input=question, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "claude -p failed").strip()[:400])
    return result.stdout.strip()


class Handler(SimpleHTTPRequestHandler):

    def end_headers(self):
        # live dashboard data — never let the browser serve stale files
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):
        if self.path.rstrip("/") != "/ask":
            self.send_error(404)
            return
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
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPowering down.")


if __name__ == "__main__":
    main()
