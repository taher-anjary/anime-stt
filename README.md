<div align="center">

# 🎌 Anime STT

### Japanese anime audio → English subtitles, in minutes

*No coding. No fuss. Just drop in a video and walk away.*

<br>

![Demo — Macross Plus (1995)](macross_demo.gif)

*Macross Plus (1995) — subtitles generated with Anime STT*

<br>

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Powered by Gemini](https://img.shields.io/badge/powered%20by-Gemini-8e44ff?style=flat-square&logo=google&logoColor=white)](https://aistudio.google.com)
[![uv](https://img.shields.io/badge/env-uv-orange?style=flat-square)](https://docs.astral.sh/uv/)
[![Windows · macOS · Linux](https://img.shields.io/badge/platform-Windows%20%C2%B7%20macOS%20%C2%B7%20Linux-lightgrey?style=flat-square)](#getting-started)

</div>

---

Anime STT extracts audio from your video, sends it to Google Gemini for Japanese-to-English transcription, and saves a clean `.srt` subtitle file you can load in any media player. All from a simple browser UI — double-click to start, no terminal needed.

---

## ⚠️ Honest disclaimer

Let me be upfront: **if human-made subtitles exist for what you're watching, use those instead.** Fan-translated subtitles made by people who actually know Japanese, understand the source material, and care about the nuance will always be better than this.

This tool exists because sometimes you're watching something obscure, something old, something that never got a proper release — and there simply are no subtitles. That's the only situation where I reach for it.

The output is imperfect in ways that go beyond the usual "AI can make mistakes" disclaimer:

- Gemini mishears words, especially names, technical terms, and fast dialogue
- Timing can drift — a few entries may be off by a second or two
- Background music and overlapping voices trip it up
- Tone, register, and cultural nuance get flattened
- It will occasionally hallucinate lines that weren't spoken

Think of the output as **a rough draft you can follow along with**, not a polished translation. It's useful enough to watch something you otherwise couldn't follow at all. That's the bar it clears, and that's the bar I built it to clear.

---

## ✨ How it works

| Step | What happens |
|:---:|---|
| **1** | **Extract Audio** — pulls a small, high-quality mono MP3 from your video |
| **2** | **Transcribe** — Gemini listens to the full audio and writes timestamped English subtitles |
| **3** | **Fix Timestamps** — overlapping subtitle end-times are detected and automatically corrected |

---

## 🧰 Before you start

You need two things installed before running Anime STT:

### 1 · Gemini API Key (free)

Get one at **[aistudio.google.com/apikey](https://aistudio.google.com/apikey)** — no payment required for the free tier.

### 2 · ffmpeg

| Platform | Install command |
|---|---|
| **Windows** | `winget install ffmpeg` or grab a build from [ffmpeg.org](https://ffmpeg.org/download.html) |
| **macOS** | `brew install ffmpeg` |
| **Ubuntu / Debian** | `sudo apt install ffmpeg` |
| **Fedora / RHEL** | `sudo dnf install ffmpeg` |

Verify it worked: run `ffmpeg -version` in a terminal and confirm it prints a version number.

---

## 🚀 Getting started

### Windows
> Double-click **`Start.bat`**

### macOS
> 1. Open Terminal in this folder and run once: `chmod +x Start.command`
> 2. Double-click **`Start.command`** from Finder

### Linux
> 1. Run once in a terminal: `chmod +x Start.sh`
> 2. Double-click **`Start.sh`** — or right-click → *Run as Program*

**On first launch**, dependencies are downloaded automatically (about 30 seconds). Every launch after that is instant.

Your browser opens at `http://127.0.0.1:5001` on its own.

**Alternatively**, simply activate the venv then run `uv run app.py` in a terminal and open the URL manually.

---

## 🎬 Usage

1. **Paste your Gemini API key** — or click *Get Key ↗* to grab one
2. **Browse for your video file** — MKV, MP4, AVI, MOV and more are all supported
3. **Check the output path** — auto-filled as `<video-name>.en.srt` next to your video; change it if you like
4. Hit **Generate Subtitles** and watch the live progress log
5. Load the `.srt` in VLC, mpv, MPC-HC, or any subtitle-capable player

---

## 📋 Good to know

- **Your API key is never stored.** It lives only in your browser tab for that session.
- **Temporary audio files are deleted** automatically after each run.
- **Timestamp overlap correction** runs on every result — the log tells you how many entries needed fixing, so you can track quality over time.
- **Large files take longer** — Gemini queues uploads; the progress log shows polling status while it waits.
- Only one subtitle job runs at a time. Submit a new one once the current job finishes.

---

## 🔧 Troubleshooting

| Problem | Fix |
|---|---|
| *"ffmpeg failed"* or *"ffmpeg not found"* | Install ffmpeg and make sure it's on your system PATH |
| *"Gemini file processing failed"* | Check your API key and internet connection, then retry |
| Browser doesn't open automatically | Go to `http://127.0.0.1:5001` manually |
| macOS: *"cannot be opened because developer cannot be verified"* | Right-click `Start.command` → Open → Open |
| Browse button opens nothing | Type or paste the file path directly into the field |
| Blank or garbled `.srt` output | Gemini occasionally returns unexpected output — retry once |
| *"Port already in use"* | Another app is on port 5001; close it and restart |

---

## 🗂 Project structure

```
anime-stt/
├── app.py              Flask server + SSE pipeline orchestration
├── core/
│   ├── audio.py        ffmpeg audio extraction
│   ├── transcriber.py  Gemini Files API + generation
│   └── srt_fix.py      SRT timestamp overlap correction
├── templates/
│   └── index.html      Browser UI (no external dependencies)
├── pyproject.toml      Python project / uv dependency config
├── Start.bat           Windows launcher
├── Start.command       macOS launcher
└── Start.sh            Linux launcher
```

