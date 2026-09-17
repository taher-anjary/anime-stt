"""
Translates segmented Japanese subtitle chunks to English using Gemini's
structured JSON output. The model only ever returns translated text keyed
by chunk id — never timestamps — so it can't corrupt timing the way the old
free-text "write a whole .srt file" approach could.
"""

import json

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel


MODEL_ID = "gemini-2.5-flash"

# USD per 1M tokens for MODEL_ID (see https://ai.google.dev/gemini-api/docs/pricing).
PRICE_PER_M_INPUT_TEXT = 0.30
PRICE_PER_M_OUTPUT = 2.50


def _log(message: str) -> None:
    print(f"[translate] {message}", flush=True)


class _TranslatedChunk(BaseModel):
    id: int
    en: str


PROMPT = """\
You are an expert Japanese-to-English translator specializing in classic anime.

You will receive a JSON array of subtitle chunks, each with an "id" and \
Japanese text "ja". Translate each chunk's "ja" text into natural, \
contextually accurate, era-appropriate English dialogue.

CRITICAL RULES:
- Return exactly one translated entry per input id. Do not add, drop, split, \
  or merge entries.
- Translate only — do not add stage directions, notes, or commentary.
- Keep the tone appropriate for a 1990s Japanese anime.

Input chunks:
{chunks_json}\
"""


def translate_chunks(api_key: str, chunks: list[dict], progress_callback=None) -> list[dict]:
    """
    chunks: [{"id", "start_ms", "end_ms", "text"}, ...] with Japanese "text".

    Returns the same chunks with "text" replaced by the English translation.
    Raises RuntimeError (with a human-readable message) on failure.
    """
    def emit(message=None, step=None, status=None):
        if progress_callback:
            progress_callback({"step": step, "status": status, "message": message})

    payload = [{"id": c["id"], "ja": c["text"]} for c in chunks]

    client = genai.Client(api_key=api_key)
    prompt = PROMPT.format(chunks_json=json.dumps(payload, ensure_ascii=False))

    emit(step="translate", status="running", message=f"Translating {len(chunks)} line(s) to English...")
    _log(f"Sending generate_content request (model={MODEL_ID}, {len(chunks)} chunks)...")

    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=list[_TranslatedChunk],
            ),
        )
    except genai_errors.APIError as exc:
        _log(f"ERROR: Gemini API error (status={exc.code}): {exc.message}")
        raise RuntimeError(
            f"Translation request to Gemini failed ({exc.code}). Check the terminal for details."
        ) from exc
    except Exception as exc:
        _log(f"ERROR: {type(exc).__name__}: {exc}")
        raise RuntimeError(
            "Something went wrong talking to Gemini during translation. Check the terminal "
            "for the full error."
        ) from exc

    usage = getattr(response, "usage_metadata", None)
    if usage is not None:
        cost = (
            (usage.prompt_token_count or 0) / 1_000_000 * PRICE_PER_M_INPUT_TEXT
            + (usage.candidates_token_count or 0) / 1_000_000 * PRICE_PER_M_OUTPUT
        )
        _log(
            f"Response received | tokens: prompt={usage.prompt_token_count}, "
            f"output={usage.candidates_token_count} | est. cost=${cost:.4f} USD"
        )

    translated: list[_TranslatedChunk] = response.parsed or []

    if not translated:
        raise RuntimeError(
            "Gemini's translation response was empty or couldn't be parsed as structured JSON. "
            "Check the terminal for details."
        )

    by_id = {t.id: t.en for t in translated}

    result = []
    missing = 0
    for c in chunks:
        en = by_id.get(c["id"])
        if en is None:
            missing += 1
            en = c["text"]  # fall back to the original Japanese rather than drop the line
        result.append({**c, "text": en})

    if missing:
        _log(f"WARNING: {missing} chunk(s) had no matching translation; kept original Japanese text.")

    emit(step="translate", status="done", message="Translation complete.")
    return result
