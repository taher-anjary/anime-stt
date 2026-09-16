"""
Anime STT — Flask web server.

Routes:
  GET  /                serve the UI
  GET  /browse/video    open native OS file picker, return {path, srt_path}
  GET  /browse/srt      open native OS save dialog, return {path}
  POST /generate/start  validate input, kick off the pipeline, return {job_id}
  GET  /generate/stream SSE stream of progress for a given job_id
"""

import json
import os
import queue
import re
import tempfile
import threading
import uuid
import webbrowser

from flask import Flask, Response, jsonify, render_template, request

from core.audio import extract_audio
from core.transcriber import transcribe
from core.srt_fix import fix_overlaps


app = Flask(__name__)

# Single job at a time
_job_running = False
_job_lock = threading.Lock()

# job_id -> Queue, populated by /generate/start, consumed by /generate/stream
_jobs: dict = {}
_jobs_lock = threading.Lock()


# ── Helpers ─────────────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _strip_fence(text: str) -> str:
    """Remove ```srt ... ``` or ``` ... ``` wrappers Gemini sometimes adds."""
    text = text.strip()
    if text.startswith("```"):
        # Drop the opening fence line (e.g. "```srt")
        text = text.split("\n", 1)[1] if "\n" in text else ""
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/browse/video")
def browse_video():
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Select Video File",
            filetypes=[
                ("Video files", "*.mp4 *.mkv *.avi *.mov *.webm *.flv *.m4v *.ts"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()
    except Exception as exc:
        return jsonify({"path": "", "srt_path": "", "error": str(exc)})

    if not path:
        return jsonify({"path": "", "srt_path": ""})

    base, _ = os.path.splitext(path)
    return jsonify({"path": path, "srt_path": base + ".en.srt"})


@app.route("/browse/srt")
def browse_srt():
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.asksaveasfilename(
            title="Save SRT File As",
            defaultextension=".srt",
            filetypes=[("SRT subtitle files", "*.srt"), ("All files", "*.*")],
        )
        root.destroy()
    except Exception as exc:
        return jsonify({"path": "", "error": str(exc)})

    return jsonify({"path": path or ""})


@app.route("/generate/start", methods=["POST"])
def generate_start():
    """Validate input and kick off the pipeline. Body: JSON {api_key, video_path, srt_path}."""
    global _job_running

    body = request.get_json(silent=True) or {}
    api_key    = (body.get("api_key") or "").strip()
    video_path = (body.get("video_path") or "").strip()
    srt_path   = (body.get("srt_path") or "").strip()

    errors = []
    if not api_key:
        errors.append("Gemini API key is required.")
    if not video_path:
        errors.append("Video file path is required.")
    elif not os.path.isfile(video_path):
        errors.append(f"Video file not found: {video_path}")
    if not srt_path:
        errors.append("SRT output path is required.")

    if errors:
        return jsonify({"errors": errors}), 400

    with _job_lock:
        if _job_running:
            return jsonify({"errors": ["A job is already running. Please wait."]}), 409
        _job_running = True

    job_id = uuid.uuid4().hex
    q: queue.Queue = queue.Queue()
    with _jobs_lock:
        _jobs[job_id] = q

    def pipeline():
        global _job_running
        temp_mp3 = None
        try:
            # ── Step 1: Extract audio ──────────────────────────────────────
            q.put({"type": "step", "step": "audio", "status": "running"})

            def audio_cb(msg):
                q.put({"type": "log", "step": "audio", "message": msg})

            temp_mp3 = extract_audio(video_path, progress_callback=audio_cb)
            q.put({"type": "step", "step": "audio", "status": "done"})

            # ── Step 2: Transcribe ─────────────────────────────────────────
            q.put({"type": "step", "step": "transcribe", "status": "running"})

            def transcribe_cb(msg):
                q.put({"type": "log", "step": "transcribe", "message": msg})

            raw_srt = transcribe(api_key, temp_mp3, progress_callback=transcribe_cb)
            raw_srt = _strip_fence(raw_srt)
            q.put({"type": "step", "step": "transcribe", "status": "done"})

            # ── Step 3: Fix SRT timestamps ─────────────────────────────────
            q.put({"type": "step", "step": "srt_fix", "status": "running"})

            fixed_srt, num_fixed = fix_overlaps(raw_srt)

            if num_fixed > 0:
                q.put({
                    "type": "log", "step": "srt_fix",
                    "message": f"Fixed {num_fixed} overlapping end-timestamp(s).",
                })
            else:
                q.put({
                    "type": "log", "step": "srt_fix",
                    "message": "No overlapping timestamps detected.",
                })

            # Ensure output directory exists
            out_dir = os.path.dirname(srt_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)

            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(fixed_srt)

            q.put({"type": "step", "step": "srt_fix", "status": "done"})
            q.put({"type": "done", "message": f"Subtitles saved to: {srt_path}"})

        except Exception as exc:
            q.put({"type": "error", "message": str(exc)})

        finally:
            if temp_mp3 and os.path.exists(temp_mp3):
                try:
                    os.remove(temp_mp3)
                except OSError:
                    pass
            with _job_lock:
                _job_running = False
            q.put(None)  # sentinel — end of stream

    thread = threading.Thread(target=pipeline, daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/generate/stream")
def generate_stream():
    """SSE endpoint. Reads query param: job_id (not sensitive — the API key never appears here)."""
    job_id = request.args.get("job_id", "")

    with _jobs_lock:
        q = _jobs.pop(job_id, None)

    if q is None:
        def _missing_gen():
            yield _sse({"type": "error", "message": "Unknown or already-consumed job_id."})
        return Response(_missing_gen(), mimetype="text/event-stream")

    def event_stream():
        while True:
            item = q.get()
            if item is None:
                return
            yield _sse(item)

    return Response(event_stream(), mimetype="text/event-stream")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    url = "http://127.0.0.1:5001"
    timer = threading.Timer(1.5, lambda: webbrowser.open(url))
    timer.daemon = True
    timer.start()
    print(f"Starting Anime STT at {url}")
    app.run(host="127.0.0.1", port=5001, use_reloader=False)
