"""
Gemini-based transcription using the google-genai SDK.
"""

import time
from google import genai


MODEL_ID = "gemini-2.5-flash-preview-04-17"

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

    if progress_callback:
        progress_callback("Uploading audio to Gemini Files API...")

    audio_file = client.files.upload(file=audio_path)

    if progress_callback:
        progress_callback(f"Upload complete (file={audio_file.name}). Waiting for processing...")

    poll_count = 0
    while audio_file.state.name != "ACTIVE":
        if audio_file.state.name == "FAILED":
            raise RuntimeError(
                f"Gemini file processing failed (state={audio_file.state.name}). "
                "Check your API key and try again."
            )
        time.sleep(5)
        audio_file = client.files.get(name=audio_file.name)
        poll_count += 1
        if progress_callback:
            progress_callback(f"Still processing... (poll #{poll_count}, state={audio_file.state.name})")

    if progress_callback:
        progress_callback("File ready. Sending generation request to Gemini...")

    response = client.models.generate_content(
        model=MODEL_ID,
        contents=[PROMPT, audio_file],
    )

    # Clean up the remote file (also auto-expires after 48 h)
    try:
        client.files.delete(name=audio_file.name)
    except Exception:
        pass  # Non-fatal

    if progress_callback:
        progress_callback("Generation complete.")

    return response.text
