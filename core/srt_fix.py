"""
SRT timestamp post-processor.

Detects entries whose end-timestamp exceeds the next entry's start-timestamp
and clips them. Returns the fixed SRT text and a count of corrections.
"""

import re
from dataclasses import dataclass
from typing import List, Tuple


_TS_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")

_BLOCK_RE = re.compile(
    r"(\d+)\s*\n"
    r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})"
    r"(.*)",
    re.DOTALL,
)


@dataclass
class _Entry:
    index: int
    start_ms: int
    end_ms: int
    text: str


def _ts_to_ms(ts: str) -> int:
    m = _TS_RE.match(ts.strip())
    if not m:
        raise ValueError(f"Invalid SRT timestamp: {ts!r}")
    h, mn, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    return h * 3_600_000 + mn * 60_000 + s * 1_000 + ms


def _ms_to_ts(ms: int) -> str:
    ms = max(0, ms)
    h = ms // 3_600_000
    ms %= 3_600_000
    mn = ms // 60_000
    ms %= 60_000
    s = ms // 1_000
    ms %= 1_000
    return f"{h:02d}:{mn:02d}:{s:02d},{ms:03d}"


def _parse(raw: str) -> List[_Entry]:
    raw = raw.strip().replace("\r\n", "\n").replace("\r", "\n")
    entries = []
    for block in re.split(r"\n{2,}", raw):
        block = block.strip()
        if not block:
            continue
        m = _BLOCK_RE.match(block)
        if not m:
            continue
        entries.append(_Entry(
            index=int(m.group(1)),
            start_ms=_ts_to_ms(m.group(2)),
            end_ms=_ts_to_ms(m.group(3)),
            text=m.group(4).strip(),
        ))
    return entries


def _render(entries: List[_Entry]) -> str:
    parts = []
    for e in entries:
        parts.append(
            f"{e.index}\n"
            f"{_ms_to_ts(e.start_ms)} --> {_ms_to_ts(e.end_ms)}\n"
            f"{e.text}"
        )
    return "\n\n".join(parts) + "\n"


def fix_overlaps(raw_srt: str) -> Tuple[str, int]:
    """
    Clip each entry's end timestamp to the next entry's start timestamp
    if it would otherwise overlap.

    Returns:
        (fixed_srt_text, num_entries_fixed)
    """
    entries = _parse(raw_srt)
    num_fixed = 0

    for i in range(len(entries) - 1):
        curr = entries[i]
        nxt = entries[i + 1]
        if curr.end_ms > nxt.start_ms:
            curr.end_ms = nxt.start_ms
            num_fixed += 1

    return _render(entries), num_fixed
