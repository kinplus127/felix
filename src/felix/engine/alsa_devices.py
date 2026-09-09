"""List ALSA playback devices for exclusive output."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class AlsaDevice:
    """One ALSA sink the user can pick for exclusive (hw:) playback."""

    hw_device: str  # e.g. hw:CARD=KA13,DEV=0
    name: str


def list_alsa_devices() -> list[AlsaDevice]:
    """Return ALSA hw devices (best-effort via aplay -l, else /proc)."""
    try:
        return parse_aplay_listing(_aplay_listing())
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return _from_proc()


def parse_aplay_listing(text: str) -> list[AlsaDevice]:
    devices: list[AlsaDevice] = []
    for line in text.splitlines():
        match = re.match(
            r"^card\s+\d+:\s+([^[]+)\s+\[([^\]]+)\],\s+device\s+(\d+):\s+([^[]+)\s+\[([^\]]+)\]",
            line,
        )
        if not match:
            continue
        card_short = match.group(1).strip()
        card_full = match.group(2).strip()
        dev = int(match.group(3))
        dev_full = match.group(5).strip()
        hw = f"hw:CARD={card_short},DEV={dev}"
        devices.append(AlsaDevice(hw_device=hw, name=f"{card_full} — {dev_full}"))
    return devices


def _aplay_listing() -> str:
    result = subprocess.run(
        ["aplay", "-l"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    return result.stdout


def _from_proc() -> list[AlsaDevice]:
    cards: dict[int, str] = {}
    shorts: dict[int, str] = {}
    try:
        with open("/proc/asound/cards", encoding="utf-8") as f:
            for line in f:
                match = re.match(r"^\s*(\d+)\s+\[([^\]]+)\]\s*:\s*.+?\s-\s(.+)$", line)
                if match:
                    idx = int(match.group(1))
                    shorts[idx] = match.group(2).strip()
                    cards[idx] = match.group(3).strip()
    except OSError:
        return []

    devices: list[AlsaDevice] = []
    try:
        with open("/proc/asound/devices", encoding="utf-8") as f:
            for line in f:
                match = re.match(
                    r"^\s*\d+:\s+\[\s*(\d+)-\s*(\d+)\]:\s*digital audio playback",
                    line,
                )
                if not match:
                    continue
                card, dev = int(match.group(1)), int(match.group(2))
                short = shorts.get(card, str(card))
                full = cards.get(card, f"Card {card}")
                hw = f"hw:CARD={short},DEV={dev}"
                devices.append(AlsaDevice(hw_device=hw, name=f"{full} (dev {dev})"))
    except OSError:
        return []
    return devices
