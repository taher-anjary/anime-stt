import subprocess
import tempfile
import os


def _log(message: str) -> None:
    print(f"[ffmpeg] {message}", flush=True)


def extract_audio(video_path: str, progress_callback=None) -> str:
    """
    Extract audio from video_path to a temporary MP3 optimized for speech.

    Settings:
      -vn              strip video stream
      -codec:a libmp3lame  LAME MP3 encoder
      -qscale:a 7      VBR ~100 kbps — good speech quality, small file
      -ac 1            mono — halves file size, fine for dialogue
      -ar 22050        22 kHz sample rate — sufficient for speech

    Returns the path to the temp MP3. Caller must delete it when done.
    Raises RuntimeError (with a human-readable message) on failure. Full
    ffmpeg command/output is always printed to the terminal.
    """
    temp_mp3 = tempfile.mktemp(suffix=".mp3")

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-codec:a", "libmp3lame",
        "-qscale:a", "7",
        "-ac", "1",
        "-ar", "22050",
        temp_mp3,
    ]

    src_size = os.path.getsize(video_path) if os.path.isfile(video_path) else 0
    _log(f"Extracting audio from: {video_path} ({src_size / (1024 * 1024):.1f} MB)")
    _log(f"Command: {' '.join(cmd)}")

    if progress_callback:
        progress_callback(f"ffmpeg command: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        _log(f"ERROR: {exc}")
        raise RuntimeError(
            "ffmpeg isn't installed or isn't on your system PATH. Install ffmpeg, "
            "then try again."
        ) from exc

    if result.returncode != 0:
        # Clean up empty file if ffmpeg created one
        if os.path.exists(temp_mp3):
            try:
                os.remove(temp_mp3)
            except OSError:
                pass
        _log(f"ERROR: ffmpeg exited with code {result.returncode}")
        _log(f"ffmpeg stderr:\n{result.stderr}")
        raise RuntimeError(
            "Couldn't extract audio from this video — it may be corrupted, missing an "
            "audio track, or in a format ffmpeg doesn't support. Check the terminal for "
            "the exact ffmpeg error, or try a different file."
        )

    size_mb = os.path.getsize(temp_mp3) / (1024 * 1024)
    _log(f"Audio extracted: {temp_mp3} ({size_mb:.1f} MB)")

    if progress_callback:
        progress_callback(f"Audio extracted ({size_mb:.1f} MB)")

    return temp_mp3


def get_duration_seconds(audio_path: str) -> float:
    """Read an audio file's duration via ffprobe. Raises RuntimeError on failure."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffprobe isn't installed or isn't on your system PATH. It ships with ffmpeg — "
            "reinstall ffmpeg, then try again."
        ) from exc

    if result.returncode != 0 or not result.stdout.strip():
        _log(f"ERROR: ffprobe failed on {audio_path}: {result.stderr}")
        raise RuntimeError("Couldn't determine the audio's duration. Check the terminal for the ffprobe error.")

    return float(result.stdout.strip())


def split_audio(audio_path: str, chunk_seconds: int) -> list[dict]:
    """
    Split audio_path into pieces no longer than chunk_seconds (mp3 stream
    copy — fast, no re-encode). If audio_path is already short enough,
    returns it unsplit.

    Returns [{"path", "offset_ms", "duration_ms"}, ...] in chronological
    order. Any path that isn't audio_path itself is a new temp file the
    caller must delete when done.
    """
    total_seconds = get_duration_seconds(audio_path)
    if total_seconds <= chunk_seconds:
        return [{"path": audio_path, "offset_ms": 0, "duration_ms": round(total_seconds * 1000)}]

    segments = []
    start = 0.0
    while start < total_seconds:
        duration = min(chunk_seconds, total_seconds - start)
        chunk_path = tempfile.mktemp(suffix=".mp3")

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", audio_path,
            "-t", str(duration),
            "-c", "copy",
            chunk_path,
        ]
        _log(f"Splitting chunk {len(segments) + 1}: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            _log(f"ERROR: ffmpeg split failed: {result.stderr}")
            raise RuntimeError(
                "Couldn't split the audio into chunks for processing. Check the terminal "
                "for the ffmpeg error."
            )

        segments.append({
            "path": chunk_path,
            "offset_ms": round(start * 1000),
            "duration_ms": round(duration * 1000),
        })
        start += chunk_seconds

    _log(f"Split {audio_path} ({total_seconds:.1f}s) into {len(segments)} chunk(s) of up to {chunk_seconds}s")
    return segments
