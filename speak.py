"""Generate jarvis_brief.mp3: send the brief text to Fish Audio TTS.

The brief is composed live from jarvis_data.js (greeting, revenue numbers,
priorities, closer), so regenerating after a data update keeps the spoken
brief in sync with the dashboard.

Usage:
    set FISH_API_KEY=your_key_here
    python speak.py                       # speaks the composed briefing
    python speak.py --no-play             # generate the file only
    python speak.py "Custom text here."   # speaks whatever you pass

Saves the audio as jarvis_brief.mp3 next to dashboard.html, so the
BRIEF ME button picks up the real narration automatically.
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
API_URL = "https://api.fish.audio/v1/tts"
MODEL = "s2.1-pro-free"                          # Fish Audio's free tier model
VOICE_ID = "36b6f66cfecf466caac7fcba1f8b59c8"    # British voice
OUT_FILE = os.path.join(ROOT, "jarvis_brief.mp3")

FALLBACK_TEXT = (
    "Good evening, Henry. Monthly recurring revenue stands at nine thousand, "
    "eight hundred sixty-eight dollars — ninety-eight point seven percent of the "
    "ten thousand dollar target. Four items need your attention, starting with "
    "the Oscorp contract, which has held up legal review for two days. "
    "That's everything that needs your attention, sir. I'll keep watch on the rest."
)


def load_data():
    """Evaluate jarvis_data.js with Node and return JARVIS_DATA as a dict."""
    node = shutil.which("node")
    js_file = os.path.join(ROOT, "jarvis_data.js")
    if not node or not os.path.exists(js_file):
        return None
    script = ("const fs=require('fs');const window={};"
              "eval(fs.readFileSync(process.argv[1],'utf8'));"
              "console.log(JSON.stringify(window.JARVIS_DATA||null));")
    try:
        result = subprocess.run([node, "-e", script, js_file],
                                capture_output=True, text=True,
                                encoding="utf-8", timeout=30)
        return json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def compose_brief(d):
    """Turn JARVIS_DATA into the spoken morning brief."""
    parts = [d.get("greeting", "Good day.")]

    h = d.get("headline") or {}
    if h.get("target"):
        pct = h.get("current", 0) / h["target"] * 100
        parts.append(
            "Revenue stands at %s dollars against the %s dollar goal — "
            "%.1f percent of the way there, with %s dollars currently due."
            % ("{:,}".format(h.get("current", 0)), "{:,}".format(h["target"]),
               pct, "{:,}".format(h.get("due", 0))))

    funnel = {f["label"]: f for f in (d.get("content") or {}).get("funnel", [])}
    if "REACH" in funnel and "SIGNUPS" in funnel:
        parts.append("The funnel drew a reach of %s, converting to %s sign-ups."
                     % ("{:,}".format(funnel["REACH"]["value"]),
                        "{:,}".format(funnel["SIGNUPS"]["value"])))

    offline = [c["name"].title() for c in d.get("connectors", [])
               if c.get("status") != "online"]
    if offline:
        parts.append("Note: the %s connector%s offline."
                     % (" and ".join(offline), " is" if len(offline) == 1 else "s are"))

    prios = d.get("priorities") or []
    if prios:
        parts.append("%d item%s need%s your attention." %
                     (len(prios), "s" if len(prios) != 1 else "",
                      "" if len(prios) != 1 else "s"))
        ordinals = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth"]
        for i, p in enumerate(prios):
            label = ordinals[i] if i < len(ordinals) else "Also"
            parts.append("%s: %s" % (label, p))

    if d.get("closer"):
        parts.append(d["closer"])
    return " ".join(parts)


def main():
    # strip whitespace and quotes — `set FISH_API_KEY="key"` in cmd keeps the quotes
    api_key = os.environ.get("FISH_API_KEY", "").strip(" \t\r\n\"'")
    if not api_key:
        sys.exit("Set the FISH_API_KEY environment variable first.")

    args = [a for a in sys.argv[1:] if a != "--no-play"]
    play = "--no-play" not in sys.argv

    if args:
        text = args[0]
    else:
        data = load_data()
        text = compose_brief(data) if data else FALLBACK_TEXT

    print("Brief text:\n  " + text + "\n")
    body = json.dumps({"text": text, "reference_id": VOICE_ID, "format": "mp3"})
    req = urllib.request.Request(
        API_URL,
        data=body.encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "model": MODEL,
        },
        method="POST",
    )
    print(f"Requesting TTS ({MODEL}, voice {VOICE_ID[:8]}…)…")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            audio = resp.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except OSError:
            pass
        print(f"Fish Audio returned HTTP {e.code}: {detail}")
        if e.code == 401:
            sys.exit(
                "401 means the API key was rejected. Check that:\n"
                "  - it's the API key from fish.audio -> account -> API keys "
                "(not the voice/model ID or a session token)\n"
                "  - there are no quotes or trailing spaces in the `set` "
                "command: use  set FISH_API_KEY=abc123  with no quotes\n"
                f"  - key being sent right now: {api_key[:4]}…{api_key[-4:]} "
                f"({len(api_key)} chars)")
        sys.exit(1)

    with open(OUT_FILE, "wb") as f:
        f.write(audio)
    print(f"Saved {len(audio):,} bytes -> {OUT_FILE}")

    if not play:
        return
    # Play it (Windows: default player; mac: afplay; linux: mpg123/ffplay)
    if sys.platform == "win32":
        os.startfile(OUT_FILE)
    elif sys.platform == "darwin":
        subprocess.run(["afplay", OUT_FILE])
    else:
        for player in ("mpg123", "ffplay -nodisp -autoexit"):
            if subprocess.run(f"{player} {OUT_FILE}", shell=True).returncode == 0:
                break


if __name__ == "__main__":
    main()
