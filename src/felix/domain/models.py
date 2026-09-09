"""Track, PlaybackSource, Quality. No tidalapi, no mpv."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Quality(StrEnum):
    LOW = "low"
    LOSSLESS = "lossless"
    MAX = "max"


class RepeatMode(StrEnum):
    OFF = "off"
    ALL = "all"
    ONE = "one"


class SourceKind(StrEnum):
    URL = "url"
    MPD_FILE = "mpd_file"
    FILE = "file"


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    artists: tuple[str, ...]
    duration: int
    album_id: str | None = None
    album_title: str | None = None


@dataclass(frozen=True)
class Album:
    id: str
    title: str
    artists: tuple[str, ...]
    year: int | None = None
    track_count: int | None = None


@dataclass(frozen=True)
class Artist:
    id: str
    name: str


@dataclass(frozen=True)
class Playlist:
    id: str
    title: str
    track_count: int | None = None


@dataclass(frozen=True)
class SearchResults:
    query: str
    tracks: tuple[Track, ...]
    albums: tuple[Album, ...]
    artists: tuple[Artist, ...]


@dataclass(frozen=True)
class PlaybackSource:
    kind: SourceKind
    location: str
    quality: str
    bit_depth: int | None
    sample_rate: int | None
    replay_gain: float | None = None
    requested: Quality = Quality.MAX


@dataclass(frozen=True)
class Lyrics:
    track_id: str
    text: str
    timed: bool
    subtitles: str = ""


@dataclass(frozen=True)
class CreditGroup:
    role: str
    names: tuple[str, ...]


@dataclass(frozen=True)
class Credits:
    track_id: str
    groups: tuple[CreditGroup, ...] = ()
    year: int | None = None
    copyright: str | None = None
