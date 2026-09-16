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
