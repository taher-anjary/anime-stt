"""
Groups word-level ASR timestamps into subtitle-sized chunks.

Pure, deterministic, no API calls. Mirrors common subtitle-segmentation
heuristics: break on sentence-ending punctuation, on a pause between words,
or once a chunk gets too long / too long-lived.
"""

_SENTENCE_END_CHARS = ("。", "！", "？", "!", "?")


def segment_words(
    words: list[dict],
    max_chars: int = 42,
    max_duration_ms: int = 7000,
    pause_break_ms: int = 400,
) -> list[dict]:
    """
    words: [{"text": str, "start_ms": int, "end_ms": int, ...}, ...] in order.

    Returns: [{"id": int, "start_ms": int, "end_ms": int, "text": str}, ...]
    """
    chunks: list[dict] = []
    current: list[dict] = []

    def flush():
        if not current:
            return
        chunks.append({
            "id": len(chunks),
            "start_ms": current[0]["start_ms"],
            "end_ms": current[-1]["end_ms"],
            "text": "".join(w["text"] for w in current),
        })
        current.clear()

    for i, word in enumerate(words):
        current.append(word)
        text_so_far = "".join(w["text"] for w in current)
        duration = word["end_ms"] - current[0]["start_ms"]

        ends_sentence = text_so_far.rstrip().endswith(_SENTENCE_END_CHARS)
        next_word = words[i + 1] if i + 1 < len(words) else None
        pause_ahead = (
            next_word is not None
            and (next_word["start_ms"] - word["end_ms"]) >= pause_break_ms
        )
        too_long = len(text_so_far) >= max_chars or duration >= max_duration_ms

        if ends_sentence or pause_ahead or too_long:
            flush()

    flush()
    return chunks
