"""
Japanese speech-to-text using Gemini 3.5 Transcribe (Interactions API).

Returns word-level timestamps from Google's ASR model directly — the model
is never asked to format timestamps as text, so it can't corrupt them the
way free-text SRT generation could (see core/srt_fix.py history).
"""

import os
import time
import traceback

from google import genai
from google.genai import errors as genai_errors

from core.segmenter import segment_words


MODEL_ID = "gemini-3.5-transcribe"

# USD per 1M tokens for MODEL_ID (see https://ai.google.dev/gemini-api/docs/pricing).
# Update these if MODEL_ID changes.
PRICE_PER_M_INPUT = 2.00
PRICE_PER_M_OUTPUT = 12.00

# Gemini caps audio at 30 minutes per request when word-level timestamps are
# requested (vs. 1 hour without). Stay under that with a safety margin —
# audio longer than this gets split into multiple requests (see app.py).
MAX_AUDIO_SEGMENT_SECONDS = 25 * 60


def _log(message: str) -> None:
    print(f"[transcribe] {message}", flush=True)


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _offset_to_ms(offset) -> int:
    """Parse a protobuf-Duration-style offset string (e.g. '12.352s') into milliseconds."""
    if offset is None:
        return 0
    s = str(offset).strip()
    if s.endswith("s"):
        s = s[:-1]
    try:
        return round(float(s) * 1000)
    except ValueError:
        return 0


def _estimate_cost_usd(usage) -> float:
    if usage is None:
        return 0.0
    input_tokens = getattr(usage, "total_input_tokens", 0) or 0
    output_tokens = getattr(usage, "total_output_tokens", 0) or 0
    return (
        input_tokens / 1_000_000 * PRICE_PER_M_INPUT
        + output_tokens / 1_000_000 * PRICE_PER_M_OUTPUT
    )


def _friendly_api_error(exc: genai_errors.APIError) -> str:
    """Translate a Gemini APIError into a short, human-readable message for the UI."""
    code = exc.code
    if code in (401, 403):
        return (
            "Your Gemini API key was rejected. Double-check that you copied it correctly "
            "and that it's still active, then try again."
        )
    if code == 429:
        return (
            "Gemini is rate-limiting or you've hit your usage quota. Wait a bit and try "
            "again, or check your plan's limits at aistudio.google.com."
        )
    if code and code >= 500:
        return "Google's Gemini service is temporarily unavailable. Please try again in a few minutes."
    if code == 400:
        return (
            "Gemini rejected the request — this can happen with unusual audio files. "
            "Try a different clip, or check the terminal for the exact reason."
        )
    return f"Gemini API error ({code}). Check the terminal for details."


def _extract_words(interaction) -> list[dict]:
    """Pull word_info annotations out of an Interaction's model_output steps."""
    words = []
    for step in getattr(interaction, "steps", None) or []:
        if getattr(step, "type", None) != "model_output":
            continue
        for item in getattr(step, "content", None) or []:
            if getattr(item, "type", None) != "text":
                continue
            for ann in getattr(item, "annotations", None) or []:
                if getattr(ann, "type", None) != "word_info":
                    continue
                text = getattr(ann, "text", None)
                if not text:
                    continue
                words.append({
                    "text": text,
                    "start_ms": _offset_to_ms(getattr(ann, "start_offset", None)),
                    "end_ms": _offset_to_ms(getattr(ann, "end_offset", None)),
                })
    return words


def transcribe_japanese(
    api_key: str,
    audio_path: str,
    progress_callback=None,
    segment_label: str | None = None,
) -> list[dict]:
    """
    Upload audio_path to the Gemini Files API, then transcribe it verbatim in
    Japanese with word-level timestamps via gemini-3.5-transcribe.

    Returns subtitle-ready chunks (Japanese text; translation happens in a
    later stage): [{"id", "start_ms", "end_ms", "text"}, ...] — timestamps
    are relative to the start of audio_path.

    segment_label, if given (e.g. "segment 2/3"), is prefixed onto every log
    line and progress message — used when the caller has split a longer
    audio file into multiple pieces (see MAX_AUDIO_SEGMENT_SECONDS).

    progress_callback, if given, is called with a dict:
      {"step": "upload"|"waiting"|"transcribe", "status": "running"|"done", "message": str|None}
    "step"/"status" may be omitted for plain log lines that don't change stage.

    Raises RuntimeError (with a human-readable message) on failure.
    """
    prefix = f"[{segment_label}] " if segment_label else ""

    def log(message: str) -> None:
        _log(f"{prefix}{message}")

    def emit(message=None, step=None, status=None):
        if progress_callback:
            progress_callback({
                "step": step,
                "status": status,
                "message": f"{prefix}{message}" if message else message,
            })

    client = genai.Client(api_key=api_key)

    filename = os.path.basename(audio_path)
    filesize = os.path.getsize(audio_path)

    try:
        emit(step="upload", status="running", message="Uploading audio to Gemini Files API...")
        log(f"Uploading: {filename} ({_human_size(filesize)})")

        audio_file = client.files.upload(file=audio_path)
        log(f"Upload complete: file={audio_file.name}, mime_type={audio_file.mime_type}")
        emit(step="upload", status="done", message=f"Upload complete (file={audio_file.name}).")

        emit(step="waiting", status="running", message="Waiting for Gemini to process the file...")
        poll_count = 0
        while audio_file.state.name != "ACTIVE":
            if audio_file.state.name == "FAILED":
                log(f"ERROR: file processing failed (state={audio_file.state.name}, file={audio_file.name})")
                raise RuntimeError(
                    "Gemini couldn't process the uploaded audio. This is usually temporary — "
                    "please try again."
                )
            time.sleep(5)
            audio_file = client.files.get(name=audio_file.name)
            poll_count += 1
            log(f"Processing... (poll #{poll_count}, state={audio_file.state.name})")
            emit(message=f"Still processing... (poll #{poll_count}, state={audio_file.state.name})")
        emit(step="waiting", status="done")

        emit(step="transcribe", status="running", message="Transcribing Japanese audio...")
        log(f"Sending interactions.create request (model={MODEL_ID})...")

        interaction = client.interactions.create(
            model=MODEL_ID,
            input=[{"type": "audio", "uri": audio_file.uri, "mime_type": audio_file.mime_type}],
            generation_config={
                "transcription_config": {
                    "language_codes": ["ja-JP"],
                    "mode": {
                        "type": "verbatim",
                        "timestamp_granularities": ["word"],
                    },
                },
            },
        )

        status = getattr(interaction, "status", None)
        if status == "failed":
            errors = getattr(interaction, "errors", None) or []
            log(f"ERROR: interaction failed: {errors}")
            raise RuntimeError(
                "Gemini's transcription request failed. Check the terminal for details."
            )

        words = _extract_words(interaction)
        log(f"Transcription received: {len(words)} words (status={status})")

        usage = getattr(interaction, "usage", None)
        cost = _estimate_cost_usd(usage)
        if usage is not None:
            log(
                f"Usage: input={usage.total_input_tokens}, output={usage.total_output_tokens}, "
                f"total={usage.total_tokens} | est. cost=${cost:.4f} USD"
            )

        emit(step="transcribe", status="done", message=f"Transcription complete ({len(words)} words).")

    except genai_errors.APIError as exc:
        log(f"ERROR: Gemini API error (status={exc.code}): {exc.message}")
        raise RuntimeError(_friendly_api_error(exc)) from exc
    except RuntimeError:
        raise  # Already logged and human-readable (e.g. the FAILED-state case above).
    except Exception as exc:
        log(f"ERROR: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise RuntimeError(
            "Something went wrong talking to Gemini. This could be a network problem or an "
            "unexpected response. Check the terminal output for the full error."
        ) from exc

    # Clean up the remote file (also auto-expires after 48 h)
    try:
        client.files.delete(name=audio_file.name)
        log(f"Deleted remote file: {audio_file.name}")
    except Exception as exc:
        log(f"WARNING: failed to delete remote file {audio_file.name}: {exc}")  # Non-fatal

    if not words:
        raise RuntimeError(
            "Gemini returned no transcribed words for this audio. The clip may be silent, "
            "non-speech, or in a format/language it couldn't process."
        )

    chunks = segment_words(words)
    log(f"Segmented into {len(chunks)} subtitle chunks")

    return chunks
