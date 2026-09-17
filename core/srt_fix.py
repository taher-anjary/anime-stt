"""
Builds .srt text directly from structured subtitle chunks, clipping any
entry's end-timestamp that exceeds the next entry's start-timestamp.

Timestamps come from real word-level ASR offsets (core/transcriber.py), not
from a model formatting them as text — so there's no free-text SRT parsing
involved here, only rendering.
"""

from dataclasses import dataclass
from typing import List, Tuple


def _log(message: str) -> None:
    print(f"[srt_fix] {message}", flush=True)


@dataclass
class _Entry:
    index: int
    start_ms: int
    end_ms: int
    text: str


def _ms_to_ts(ms: int) -> str:
    ms = max(0, ms)
    h = ms // 3_600_000
    ms %= 3_600_000
    mn = ms // 60_000
    ms %= 60_000
    s = ms // 1_000
    ms %= 1_000
    return f"{h:02d}:{mn:02d}:{s:02d},{ms:03d}"


def _render(entries: List[_Entry]) -> str:
    parts = []
    for e in entries:
        parts.append(
            f"{e.index}\n"
            f"{_ms_to_ts(e.start_ms)} --> {_ms_to_ts(e.end_ms)}\n"
            f"{e.text}"
        )
    return "\n\n".join(parts) + "\n"


def build_and_fix_srt(chunks: list[dict]) -> Tuple[str, int]:
    """
    chunks: [{"id", "start_ms", "end_ms", "text"}, ...] (already translated).

    Builds 1-indexed SRT entries directly from the chunks, clipping each
    entry's end timestamp to the next entry's start timestamp if it would
    otherwise overlap.

    Returns (srt_text, num_entries_fixed).
    """
    entries = [
        _Entry(index=i + 1, start_ms=c["start_ms"], end_ms=c["end_ms"], text=c["text"].strip())
        for i, c in enumerate(chunks)
    ]

    num_fixed = 0
    for i in range(len(entries) - 1):
        curr = entries[i]
        nxt = entries[i + 1]
        if curr.end_ms > nxt.start_ms:
            curr.end_ms = nxt.start_ms
            num_fixed += 1

    srt_text = _render(entries)
    _log(f"Built {len(entries)} entries, fixed {num_fixed} overlap(s).")

    return srt_text, num_fixed
