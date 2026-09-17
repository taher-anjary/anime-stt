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
import traceback
import uuid
import webbrowser

from flask import Flask, Response, jsonify, render_template, request

from core.audio import extract_audio, split_audio
from core.transcriber import transcribe_japanese, MAX_AUDIO_SEGMENT_SECONDS
from core.translator import translate_chunks
from core.srt_fix import build_and_fix_srt


def _log(message: str) -> None:
    print(f"[app] {message}", flush=True)


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
        segment_paths = []
        try:
            # ── Step 1: Extract audio ──────────────────────────────────────
            q.put({"type": "step", "step": "audio", "status": "running"})

            def audio_cb(msg):
                q.put({"type": "log", "step": "audio", "message": msg})

            temp_mp3 = extract_audio(video_path, progress_callback=audio_cb)
            q.put({"type": "step", "step": "audio", "status": "done"})

            # ── Steps 2-4: Upload / Wait for Gemini / Transcribe (Japanese) ──
            def progress_cb(evt):
                step, status, message = evt.get("step"), evt.get("status"), evt.get("message")
                if step and status:
                    q.put({"type": "step", "step": step, "status": status})
                if message:
                    q.put({"type": "log", "step": step, "message": message})

            # Gemini caps audio duration per request when word-level timestamps
            # are requested — split longer audio into segments, transcribe each
            # separately, then reassemble with the segment's time offset applied.
            segments = split_audio(temp_mp3, MAX_AUDIO_SEGMENT_SECONDS)
            segment_paths = [s["path"] for s in segments if s["path"] != temp_mp3]
            num_segments = len(segments)

            if num_segments > 1:
                q.put({
                    "type": "log", "step": "transcribe",
                    "message": (
                        f"Audio is longer than {MAX_AUDIO_SEGMENT_SECONDS // 60} min — "
                        f"split into {num_segments} segments for transcription."
                    ),
                })

            chunks = []
            for i, seg in enumerate(segments, start=1):
                label = f"segment {i}/{num_segments}" if num_segments > 1 else None
                if num_segments > 1:
                    q.put({
                        "type": "log", "step": "transcribe",
                        "message": f"Processing segment [{i}/{num_segments}]...",
                    })

                seg_chunks = transcribe_japanese(
                    api_key, seg["path"], progress_callback=progress_cb, segment_label=label
                )
                for c in seg_chunks:
                    c["start_ms"] += seg["offset_ms"]
                    c["end_ms"] += seg["offset_ms"]
                chunks.extend(seg_chunks)

            for idx, c in enumerate(chunks):
                c["id"] = idx

            # ── Step 5: Translate to English ─────────────────────────────────
            chunks = translate_chunks(api_key, chunks, progress_callback=progress_cb)

            # ── Step 6: Build SRT and fix timestamps ──────────────────────────
            q.put({"type": "step", "step": "srt_fix", "status": "running"})

            fixed_srt, num_fixed = build_and_fix_srt(chunks)

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

            # Ensure output directory exists and write the file
            try:
                out_dir = os.path.dirname(srt_path)
                if out_dir:
                    os.makedirs(out_dir, exist_ok=True)

                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(fixed_srt)
            except OSError as exc:
                _log(f"ERROR: failed to write '{srt_path}': {exc}")
                raise RuntimeError(
                    f"Couldn't save the subtitle file to '{srt_path}'. Check that the "
                    "folder exists and that you have permission to write there."
                ) from exc

            _log(f"Saved: {srt_path} ({len(fixed_srt)} chars)")
            q.put({"type": "step", "step": "srt_fix", "status": "done"})
            q.put({"type": "done", "message": f"Subtitles saved to: {srt_path}"})

        except RuntimeError as exc:
            # Raised by core.audio / core.transcriber / the write step above —
            # already logged to the terminal and worded for the end user.
            q.put({"type": "error", "message": str(exc)})

        except Exception as exc:
            _log(f"ERROR: unexpected {type(exc).__name__}: {exc}")
            traceback.print_exc()
            q.put({
                "type": "error",
                "message": "Something unexpected went wrong. Check the terminal for details.",
            })

        finally:
            if temp_mp3 and os.path.exists(temp_mp3):
                try:
                    os.remove(temp_mp3)
                except OSError:
                    pass
            for seg_path in segment_paths:
                if os.path.exists(seg_path):
                    try:
                        os.remove(seg_path)
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
