"""Paths and defaults. No I/O besides path construction."""

from pathlib import Path

APP_NAME = "felix"
CONFIG_DIR = Path.home() / ".config" / APP_NAME
SESSION_PATH = CONFIG_DIR / "session.json"
LOG_PATH = CONFIG_DIR / "felix.log"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
MPV_SOCKET_PATH = Path("/tmp/felix-mpv.sock")
MPD_DIR = Path("/tmp")
MPD_KEEP = 4
DEFAULT_QUALITY = "max"
PREFETCH_LEAD_SECS = 18.0
PREFETCH_TTL_SECS = 75.0
# How long a track change waits for an in-flight prefetch before resolving
# itself. Kept short: this blocks the transport worker.
PREFETCH_WAIT_SECS = 1.5
