"""Snapshot of the current track, source, and transport state."""

from __future__ import annotations

from dataclasses import dataclass

from felix.domain.models import PlaybackSource, Track


@dataclass
class NowPlaying:
    track: Track | None = None
    source: PlaybackSource | None = None
    state: str = "stopped"
    position: float = 0.0
    duration: float | None = None

    def clear(self) -> None:
        self.track = None
        self.source = None
        self.state = "stopped"
        self.position = 0.0
        self.duration = None
