import subprocess
import tempfile
import os


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
    Raises RuntimeError if ffmpeg exits non-zero.
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

    if progress_callback:
        progress_callback(f"ffmpeg command: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        # Clean up empty file if ffmpeg created one
        if os.path.exists(temp_mp3):
            try:
                os.remove(temp_mp3)
            except OSError:
                pass
        raise RuntimeError(
            f"ffmpeg failed (exit code {result.returncode}):\n{result.stderr[-2000:]}"
        )

    if progress_callback:
        size_mb = os.path.getsize(temp_mp3) / (1024 * 1024)
        progress_callback(f"Audio extracted ({size_mb:.1f} MB)")

    return temp_mp3
