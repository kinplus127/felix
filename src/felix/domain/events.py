"""Facts that already happened. UI and scripts only listen."""

from __future__ import annotations

from dataclasses import dataclass

from felix.domain.models import (
    Album,
    Artist,
    Credits,
    Lyrics,
    PlaybackSource,
    Playlist,
    RepeatMode,
    SearchResults,
    Track,
)


@dataclass(frozen=True)
class TrackResolved:
    track: Track


@dataclass(frozen=True)
class SourceReady:
    source: PlaybackSource


@dataclass(frozen=True)
class Playing:
    pass


@dataclass(frozen=True)
class Paused:
    pass


@dataclass(frozen=True)
class Position:
    seconds: float
    duration: float | None


@dataclass(frozen=True)
class Ended:
    pass


@dataclass(frozen=True)
class Stopped:
    pass


@dataclass(frozen=True)
class Failed:
    message: str


@dataclass(frozen=True)
class QueueUpdated:
    track_ids: tuple[str, ...]
    index: int | None
    history: tuple[str, ...]


@dataclass(frozen=True)
class ShuffleChanged:
    enabled: bool


@dataclass(frozen=True)
class RepeatChanged:
    mode: RepeatMode


@dataclass(frozen=True)
class SearchReady:
    results: SearchResults


@dataclass(frozen=True)
class AlbumOpened:
    album: Album
    tracks: tuple[Track, ...]


@dataclass(frozen=True)
class ArtistOpened:
    artist: Artist
    tracks: tuple[Track, ...]
    albums: tuple[Album, ...]


@dataclass(frozen=True)
class PlaylistsReady:
    playlists: tuple[Playlist, ...]


@dataclass(frozen=True)
class PlaylistOpened:
    playlist: Playlist
    tracks: tuple[Track, ...]


@dataclass(frozen=True)
class LyricsReady:
    lyrics: Lyrics


@dataclass(frozen=True)
class CreditsReady:
    credits: Credits


@dataclass(frozen=True)
class VolumeChanged:
    level: float


@dataclass(frozen=True)
class OutputChanged:
    exclusive: bool
    ao: str
    audio_device: str
    exclusive_device: str


@dataclass(frozen=True)
class FormatReady:
    source_rate: int | None
    source_bits: int | None
    decode_rate: int | None
    decode_format: str
    output_rate: int | None
    output_format: str
    matched: bool | None
    exclusive: bool


Event = (
    TrackResolved
    | SourceReady
    | Playing
    | Paused
    | Position
    | Ended
    | Stopped
    | Failed
    | QueueUpdated
    | ShuffleChanged
    | RepeatChanged
    | SearchReady
    | AlbumOpened
    | ArtistOpened
    | PlaylistsReady
    | PlaylistOpened
    | LyricsReady
    | CreditsReady
    | VolumeChanged
    | OutputChanged
    | FormatReady
)
