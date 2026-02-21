#!/usr/bin/env bash
# macOS double-click launcher for Anime STT
# Make executable once: chmod +x Start.command

set -euo pipefail

# Always run from the directory containing this script
cd "$(dirname "$0")"

echo ""
echo " ============================================="
echo "   Anime STT - Starting..."
echo " ============================================="
echo ""

# ── Check / install uv ────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    echo " uv not found. Installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Make uv available in this shell session immediately
    export PATH="$HOME/.local/bin:$PATH"
fi

# ── Sync dependencies ─────────────────────────────────────────────────────
echo " Syncing dependencies (first run may take a minute)..."
uv sync

# ── Launch app ────────────────────────────────────────────────────────────
echo ""
echo " Launching app — your browser will open automatically."
echo " Close this window (or press Ctrl+C) to stop the server."
echo ""
uv run app.py

echo ""
echo " App exited. You can close this window."
