"""
Gemini-based transcription using the google-genai SDK.
"""

import os
import time
import traceback

from google import genai
from google.genai import errors as genai_errors


MODEL_ID = "gemini-2.5-flash"

# USD per 1M tokens for MODEL_ID (see https://ai.google.dev/gemini-api/docs/pricing).
# Update these if MODEL_ID changes.
PRICE_PER_M_INPUT_TEXT = 0.30
PRICE_PER_M_INPUT_AUDIO = 1.00
PRICE_PER_M_OUTPUT = 2.50


def _log(message: str) -> None:
    print(f"[gemini] {message}", flush=True)


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _estimate_cost_usd(usage_metadata) -> float:
    """Estimate USD cost from usage_metadata, splitting input tokens by modality."""
    if usage_metadata is None:
        return 0.0

    input_text_tokens = 0
    input_audio_tokens = 0
    details = getattr(usage_metadata, "prompt_tokens_details", None) or []
    for entry in details:
        modality = str(getattr(entry, "modality", "")).upper()
        count = getattr(entry, "token_count", 0) or 0
        if "AUDIO" in modality:
            input_audio_tokens += count
        else:
            input_text_tokens += count

    # Fallback if the API didn't return a per-modality breakdown.
    prompt_total = getattr(usage_metadata, "prompt_token_count", 0) or 0
    if not details and prompt_total:
        input_text_tokens = prompt_total

    output_tokens = getattr(usage_metadata, "candidates_token_count", 0) or 0

    return (
        input_text_tokens / 1_000_000 * PRICE_PER_M_INPUT_TEXT
        + input_audio_tokens / 1_000_000 * PRICE_PER_M_INPUT_AUDIO
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


PROMPT = """\
You are an expert Japanese-to-English translator specializing in classic anime.

TASK:
1. Listen to the audio from the beginning to the end.
2. Transcribe the Japanese dialogue and Translate it into natural, contextually accurate, era-appropriate English.
4. Output ONLY a valid .srt file format.

CRITICAL RULES:
- DO NOT skip any dialogue, even if there is background music.
- DO NOT produce Japanese subtitles. We only want English
- Timestamps MUST synchronized with the audio dialogue.
- Output ONLY the SRT content. No conversational text.\
"""


def transcribe(api_key: str, audio_path: str, progress_callback=None) -> str:
    """
    Upload audio_path to the Gemini Files API, wait for processing,
    generate English SRT subtitles, and return the raw SRT text.

    Raises RuntimeError on upload failure or generation error.
    """
    client = genai.Client(api_key=api_key)

    filename = os.path.basename(audio_path)
    filesize = os.path.getsize(audio_path)

    try:
        if progress_callback:
            progress_callback("Uploading audio to Gemini Files API...")
        _log(f"Uploading: {filename} ({_human_size(filesize)})")

        audio_file = client.files.upload(file=audio_path)
        _log(f"Upload complete: file={audio_file.name}, mime_type={audio_file.mime_type}")

        if progress_callback:
            progress_callback(f"Upload complete (file={audio_file.name}). Waiting for processing...")

        poll_count = 0
        while audio_file.state.name != "ACTIVE":
            if audio_file.state.name == "FAILED":
                _log(f"ERROR: file processing failed (state={audio_file.state.name}, file={audio_file.name})")
                raise RuntimeError(
                    "Gemini couldn't process the uploaded audio. This is usually temporary — "
                    "please try again."
                )
            time.sleep(5)
            audio_file = client.files.get(name=audio_file.name)
            poll_count += 1
            _log(f"Processing... (poll #{poll_count}, state={audio_file.state.name})")
            if progress_callback:
                progress_callback(f"Still processing... (poll #{poll_count}, state={audio_file.state.name})")

        if progress_callback:
            progress_callback("File ready. Sending generation request to Gemini...")
        _log(f"Sending generate_content request (model={MODEL_ID})...")

        response = client.models.generate_content(
            model=MODEL_ID,
            contents=[PROMPT, audio_file],
        )

        usage = getattr(response, "usage_metadata", None)
        cost = _estimate_cost_usd(usage)
        response_chars = len(response.text or "")
        if usage is not None:
            _log(
                f"Response received: {response_chars} chars | "
                f"tokens: prompt={usage.prompt_token_count}, "
                f"output={usage.candidates_token_count}, "
                f"total={usage.total_token_count} | "
                f"est. cost=${cost:.4f} USD"
            )
        else:
            _log(f"Response received: {response_chars} chars (no usage_metadata returned)")

    except genai_errors.APIError as exc:
        _log(f"ERROR: Gemini API error (status={exc.code}): {exc.message}")
        raise RuntimeError(_friendly_api_error(exc)) from exc
    except RuntimeError:
        raise  # Already logged and human-readable (e.g. the FAILED-state case above).
    except Exception as exc:
        _log(f"ERROR: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise RuntimeError(
            "Something went wrong talking to Gemini. This could be a network problem or an "
            "unexpected response. Check the terminal output for the full error."
        ) from exc

    # Clean up the remote file (also auto-expires after 48 h)
    try:
        client.files.delete(name=audio_file.name)
        _log(f"Deleted remote file: {audio_file.name}")
    except Exception as exc:
        _log(f"WARNING: failed to delete remote file {audio_file.name}: {exc}")  # Non-fatal

    if progress_callback:
        progress_callback("Generation complete.")

    return response.text
