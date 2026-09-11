"""Catalog: search, tracks, albums, playlists. No now-playing."""

from __future__ import annotations

import re

import tidalapi
from tidalapi.exceptions import MetadataNotAvailable, ObjectNotFound, TooManyRequests

from felix.domain.models import (
    Album,
    Artist,
    Credits,
    CreditGroup,
    Lyrics,
    Playlist,
    SearchResults,
    Track,
)
from felix.tidal.auth import raise_if_auth
from felix.tidal.credits import (
    copyright_text,
    parse_contributors,
    release_year,
    year_from_album,
)
from felix.tidal.gate import SessionGate, gate_for


class CatalogError(Exception):
    """Track or search lookup failed."""


def _names(artists: list | None, fallback: object | None = None) -> tuple[str, ...]:
    items = list(artists or [])
    if not items and fallback is not None:
        items = [fallback]
    return tuple(artist.name for artist in items if artist and getattr(artist, "name", None))


def to_track(raw: tidalapi.Track) -> Track:
    album = raw.album
    return Track(
        id=str(raw.id),
        title=raw.full_name or raw.title or "",
        artists=_names(raw.artists, raw.artist),
        duration=int(raw.duration or 0),
        album_id=str(album.id) if album and album.id is not None else None,
        album_title=album.name if album else None,
    )


def to_album(raw: tidalapi.Album) -> Album:
    return Album(
        id=str(raw.id),
        title=raw.name or "",
        artists=_names(raw.artists, raw.artist),
        year=raw.year,
        track_count=raw.num_tracks if raw.num_tracks not in (None, -1) else None,
    )


def to_artist(raw: tidalapi.Artist) -> Artist:
    return Artist(id=str(raw.id), name=raw.name or "")


def to_playlist(raw: tidalapi.Playlist) -> Playlist:
    count = raw.num_tracks
    return Playlist(
        id=str(raw.id),
        title=raw.name or "",
        track_count=count if count not in (None, -1) else None,
    )


_PLAYLIST_PAGE = 50
_TRACK_PAGE = 100


class Client:
    """Directory lookups. Does not resolve streams or remember playback."""

    def __init__(self, session: tidalapi.Session | SessionGate) -> None:
        self._gate = gate_for(session)
        self._session = self._gate.session

    def get_track(self, track_id: str) -> Track:
        with self._gate:
            try:
                raw = self._session.track(track_id)
            except Exception as exc:
                raise_if_auth(exc)
                raise CatalogError(f"找不到曲目 {track_id}") from exc
            return to_track(raw)

    def search_tracks(self, query: str, limit: int = 10) -> list[Track]:
        return list(self.search(query, limit=limit).tracks)

    def search(self, query: str, limit: int = 10) -> SearchResults:
        with self._gate:
            try:
                result = self._session.search(
                    query,
                    models=[tidalapi.Track, tidalapi.Album, tidalapi.Artist],
                    limit=limit,
                )
            except Exception as exc:
                raise_if_auth(exc)
                raise CatalogError(f"搜尋失敗：{exc}") from exc
            return SearchResults(
                query=query,
                tracks=tuple(to_track(item) for item in result["tracks"] or []),
                albums=tuple(to_album(item) for item in result["albums"] or []),
                artists=tuple(to_artist(item) for item in result["artists"] or []),
            )

    def album_tracks(self, album_id: str) -> tuple[Album, tuple[Track, ...]]:
        with self._gate:
            try:
                raw = self._session.album(album_id)
                tracks = raw.tracks()
            except Exception as exc:
                raise_if_auth(exc)
                raise CatalogError(f"找不到專輯 {album_id}") from exc
            return to_album(raw), tuple(to_track(item) for item in tracks)

    def artist_catalog(
        self, artist_id: str, limit: int = 20
    ) -> tuple[Artist, tuple[Track, ...], tuple[Album, ...]]:
        with self._gate:
            try:
                raw = self._session.artist(artist_id)
                tracks = raw.get_top_tracks(limit=limit)
                albums = raw.get_albums(limit=limit)
            except Exception as exc:
                raise_if_auth(exc)
                raise CatalogError(f"找不到藝人 {artist_id}") from exc
            return (
                to_artist(raw),
                tuple(to_track(item) for item in tracks or []),
                tuple(to_album(item) for item in albums or []),
            )

    def user_playlists(self) -> tuple[Playlist, ...]:
        with self._gate:
            user = self._session.user
            fetch = getattr(user, "playlist_and_favorite_playlists", None)
            if user is None or not callable(fetch):
                raise CatalogError("尚未登入，無法取得 playlists")
            items: list = []
            offset = 0
            try:
                while True:
                    page = fetch(offset=offset, limit=_PLAYLIST_PAGE)
                    batch = list(page or [])
                    items.extend(batch)
                    if len(batch) < _PLAYLIST_PAGE:
                        break
                    offset += _PLAYLIST_PAGE
            except Exception as exc:
                raise_if_auth(exc)
                raise CatalogError("無法取得 playlists") from exc
            seen: set[str] = set()
            out: list[Playlist] = []
            for raw in items:
                pid = str(getattr(raw, "id", "") or "")
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                out.append(to_playlist(raw))
            return tuple(out)

    def playlist_tracks(self, playlist_id: str) -> tuple[Playlist, tuple[Track, ...]]:
        with self._gate:
            try:
                raw = self._session.playlist(playlist_id)
                tracks = _playlist_track_pages(raw)
            except Exception as exc:
                raise_if_auth(exc)
                raise CatalogError(f"找不到播放清單 {playlist_id}") from exc
            return to_playlist(raw), tuple(to_track(item) for item in tracks)

    def get_lyrics(self, track_id: str) -> Lyrics:
        with self._gate:
            try:
                raw = self._session.track(track_id)
            except Exception as exc:
                raise_if_auth(exc)
                raise CatalogError(f"找不到曲目 {track_id}") from exc
            try:
                data = raw.lyrics()
            except (MetadataNotAvailable, ObjectNotFound):
                return Lyrics(track_id=track_id, text="", timed=False)
            except TooManyRequests as exc:
                raise CatalogError(f"歌詞暫時無法取得（{track_id}）") from exc
            except Exception as exc:
                raise_if_auth(exc)
                raise CatalogError(f"無法取得歌詞 {track_id}") from exc

            subtitles = (getattr(data, "subtitles", None) or "").strip()
            plain = (getattr(data, "text", None) or "").strip()
            if not plain and subtitles:
                plain = _strip_lrc(subtitles)
            return Lyrics(
                track_id=track_id,
                text=plain,
                timed=bool(subtitles),
                subtitles=subtitles,
            )

    def get_credits(self, track_id: str) -> Credits:
        with self._gate:
            try:
                raw = self._session.track(track_id)
            except Exception as exc:
                raise_if_auth(exc)
                raise CatalogError(f"找不到曲目 {track_id}") from exc

            year = release_year(raw)
            copyright = copyright_text(raw) or copyright_text(
                getattr(raw, "album", None)
            )
            groups = self._credit_groups(track_id)

            if year is None or not copyright:
                album = getattr(raw, "album", None)
                album_id = getattr(album, "id", None) if album is not None else None
                if album_id is not None:
                    try:
                        extra = self._session.album(album_id)
                    except (MetadataNotAvailable, ObjectNotFound, TooManyRequests):
                        extra = None
                    except Exception as exc:
                        raise_if_auth(exc)
                        extra = None
                    if extra is not None:
                        if year is None:
                            year = year_from_album(extra)
                        if not copyright:
                            copyright = copyright_text(extra)

            return Credits(
                track_id=track_id,
                groups=tuple(CreditGroup(role, tuple(names)) for role, names in groups),
                year=year,
                copyright=copyright,
            )

    def _credit_groups(self, track_id: str) -> list[tuple[str, list[str]]]:
        """Caller must already hold the session gate."""
        groups: list[tuple[str, list[str]]] = []
        last_error: Exception | None = None
        seen_ok = False
        for path in (
            f"tracks/{track_id}/contributors",
            f"tracks/{track_id}/credits",
        ):
            try:
                response = self._session.request.request("GET", path)
                groups = parse_contributors(response.json())
                seen_ok = True
            except (MetadataNotAvailable, ObjectNotFound):
                continue
            except TooManyRequests as exc:
                raise CatalogError(f"Credits 暫時無法取得（{track_id}）") from exc
            except Exception as exc:
                raise_if_auth(exc)
                last_error = exc
                continue
            if groups:
                return groups
        if last_error is not None and not seen_ok:
            raise CatalogError(f"無法取得 credits {track_id}") from last_error
        return groups


def _playlist_track_pages(raw: tidalapi.Playlist) -> list:
    items: list = []
    offset = 0
    while True:
        page = raw.tracks(limit=_TRACK_PAGE, offset=offset)
        batch = list(page or [])
        items.extend(batch)
        if len(batch) < _TRACK_PAGE:
            break
        offset += _TRACK_PAGE
    return items


_LRC_LINE = re.compile(r"^\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]\s*")


def _strip_lrc(subtitles: str) -> str:
    lines = [_LRC_LINE.sub("", line) for line in subtitles.splitlines()]
    return "\n".join(lines).strip()
