"""Persistent player settings: volume and audio output preference."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from felix.config import CONFIG_DIR, SETTINGS_PATH
from felix.logs import get_logger

log = get_logger("settings")

VOLUME_MIN = 0.0
VOLUME_MAX = 100.0
DEFAULT_VOLUME = 100.0
ALLOWED_AO = ("pipewire", "pulse", "alsa")
ALLOWED_OUTPUT = ("system", "exclusive")
SYSTEM_ALSA_WARNING = (
    "system+alsa 可能搶走 DAC mixer、搞壞 PipeWire 音量；建議 ao pipewire"
)


class SettingsError(Exception):
    """Invalid settings value."""


@dataclass
class Settings:
    volume: float = DEFAULT_VOLUME
    output: str = "system"
    ao: str = ""
    audio_device: str = ""
    exclusive_device: str = ""


def clamp_volume(value: float) -> float:
    return max(VOLUME_MIN, min(VOLUME_MAX, float(value)))


def normalize_ao(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw in {"", "auto", "default"}:
        return ""
    if raw in ALLOWED_AO:
        return raw
    raise SettingsError(f"ao 只能是 auto / pipewire / pulse / alsa，不是 {value!r}")


def normalize_device(value: str) -> str:
    raw = (value or "").strip()
    if raw.lower() in {"", "auto", "default"}:
        return ""
    return raw


def normalize_output(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw in {"", "system", "shared", "default"}:
        return "system"
    if raw in {"exclusive", "hw", "alsa-exclusive"}:
        return "exclusive"
    raise SettingsError(f"output 只能是 system 或 exclusive，不是 {value!r}")


def normalize_hw_device(value: str) -> str:
    raw = (value or "").strip()
    if raw.lower() in {"", "auto", "default"}:
        return ""
    if raw.startswith("alsa/"):
        raw = raw[5:]
    if raw.startswith("plughw:"):
        raise SettingsError("exclusive 不接受 plughw，請用 hw:CARD=…,DEV=…")
    if not raw.startswith("hw:"):
        raise SettingsError("exclusive 需要 hw:CARD=…,DEV=…")
    return raw


def load_settings() -> Settings:
    if not SETTINGS_PATH.exists():
        return Settings()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read settings: %s", exc)
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    try:
        volume = clamp_volume(data.get("volume", DEFAULT_VOLUME))
    except (TypeError, ValueError):
        volume = DEFAULT_VOLUME
    try:
        ao = normalize_ao(str(data.get("ao", "") or ""))
    except SettingsError:
        log.warning("ignoring invalid ao in settings")
        ao = ""
    try:
        output = normalize_output(str(data.get("output", "system") or "system"))
    except SettingsError:
        log.warning("ignoring invalid output in settings")
        output = "system"
    device = normalize_device(str(data.get("audio_device", "") or ""))
    try:
        exclusive_device = normalize_hw_device(
            str(data.get("exclusive_device", "") or "")
        )
    except SettingsError:
        log.warning("ignoring invalid exclusive_device in settings")
        exclusive_device = ""
        if output == "exclusive":
            output = "system"
    return Settings(
        volume=volume,
        output=output,
        ao=ao,
        audio_device=device,
        exclusive_device=exclusive_device,
    )


def save_settings(settings: Settings) -> None:
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload: dict = {}
    if SETTINGS_PATH.exists():
        try:
            existing = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                payload = existing
        except (OSError, json.JSONDecodeError):
            payload = {}
    payload["volume"] = clamp_volume(settings.volume)
    payload["output"] = settings.output
    payload["ao"] = settings.ao
    payload["audio_device"] = settings.audio_device
    payload["exclusive_device"] = settings.exclusive_device
    SETTINGS_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.chmod(SETTINGS_PATH, 0o600)
