"""How the engine should open audio. Engine does not know about TIDAL."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutputSpec:
    exclusive: bool = False
    ao: str = ""
    audio_device: str = ""
    exclusive_device: str = ""

    def mpv_ao(self) -> str:
        if self.exclusive:
            return "alsa"
        return self.ao

    def mpv_audio_device(self) -> str:
        if self.exclusive:
            return f"alsa/{self.exclusive_device}"
        return self.audio_device
