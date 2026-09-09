"""User intentions. UI and scripts send these into runtime."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlayTrack:
    track_id: str


@dataclass(frozen=True)
class PlayList:
    track_ids: tuple[str, ...]
    start_index: int = 0


@dataclass(frozen=True)
class TogglePause:
    pass


@dataclass(frozen=True)
class Pause:
    pass


@dataclass(frozen=True)
class Resume:
    pass


@dataclass(frozen=True)
class Seek:
    seconds: float


@dataclass(frozen=True)
class SeekRelative:
    delta: float


@dataclass(frozen=True)
class Stop:
    pass


@dataclass(frozen=True)
class Enqueue:
    track_id: str


@dataclass(frozen=True)
class Next:
    pass


@dataclass(frozen=True)
class Prev:
    pass


@dataclass(frozen=True)
class ToggleShuffle:
    pass


@dataclass(frozen=True)
class CycleRepeat:
    pass


@dataclass(frozen=True)
class Search:
    query: str
    limit: int = 10


@dataclass(frozen=True)
class OpenAlbum:
    album_id: str


@dataclass(frozen=True)
class OpenArtist:
    artist_id: str


@dataclass(frozen=True)
class ListPlaylists:
    pass


@dataclass(frozen=True)
class OpenPlaylist:
    playlist_id: str


@dataclass(frozen=True)
class PlayPlaylist:
    playlist_id: str
    start_index: int = 0


@dataclass(frozen=True)
class ShowLyrics:
    track_id: str


@dataclass(frozen=True)
class ShowCredits:
    track_id: str


@dataclass(frozen=True)
class SetVolume:
    level: float


@dataclass(frozen=True)
class AdjustVolume:
    delta: float


@dataclass(frozen=True)
class SetAudioOutput:
    ao: str | None = None
    audio_device: str | None = None
    exclusive: bool | None = None
    exclusive_device: str | None = None


Intent = (
    PlayTrack
    | PlayList
    | TogglePause
    | Pause
    | Resume
    | Seek
    | SeekRelative
    | Stop
    | Enqueue
    | Next
    | Prev
    | ToggleShuffle
    | CycleRepeat
    | Search
    | OpenAlbum
    | OpenArtist
    | ListPlaylists
    | OpenPlaylist
    | PlayPlaylist
    | ShowLyrics
    | ShowCredits
    | SetVolume
    | AdjustVolume
    | SetAudioOutput
)
