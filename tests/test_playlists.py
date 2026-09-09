"""User playlists catalog. No live TIDAL session."""

from __future__ import annotations

import unittest

from felix.tidal.client import CatalogError, Client, to_playlist


class FakeArtist:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeTrack:
    def __init__(self, track_id: str, title: str) -> None:
        self.id = track_id
        self.full_name = title
        self.title = title
        self.artists = [FakeArtist("X")]
        self.artist = FakeArtist("X")
        self.duration = 10
        self.album = None


class FakeRawPlaylist:
    def __init__(
        self,
        pid: str,
        name: str,
        tracks: list[FakeTrack] | None = None,
        num_tracks: int | None = None,
    ) -> None:
        self.id = pid
        self.name = name
        self._tracks = list(tracks or [])
        self.num_tracks = num_tracks if num_tracks is not None else len(self._tracks)

    def tracks(self, limit: int | None = None, offset: int = 0, **_kwargs: object) -> list[FakeTrack]:
        items = self._tracks[offset:]
        if limit is not None:
            items = items[:limit]
        return items


class FakeUser:
    def __init__(self, playlists: list[FakeRawPlaylist]) -> None:
        self._playlists = playlists

    def playlist_and_favorite_playlists(
        self, offset: int = 0, limit: int = 50
    ) -> list[FakeRawPlaylist]:
        return self._playlists[offset : offset + limit]


class FakeSession:
    def __init__(
        self,
        user: FakeUser | None = None,
        catalog: dict[str, FakeRawPlaylist] | None = None,
    ) -> None:
        self.user = user
        self._catalog = catalog or {}

    def playlist(self, playlist_id: str) -> FakeRawPlaylist:
        if playlist_id not in self._catalog:
            raise RuntimeError("missing playlist")
        return self._catalog[playlist_id]


class TestUserPlaylists(unittest.TestCase):
    def test_maps_and_paginates(self) -> None:
        raw = [FakeRawPlaylist(f"pl-{i}", f"List {i}") for i in range(51)]
        raw.append(FakeRawPlaylist("pl-0", "duplicate"))
        client = Client(FakeSession(user=FakeUser(raw)))  # type: ignore[arg-type]
        playlists = client.user_playlists()
        self.assertEqual(len(playlists), 51)
        self.assertEqual(playlists[0].id, "pl-0")
        self.assertEqual(playlists[0].title, "List 0")
        self.assertEqual(playlists[-1].id, "pl-50")

    def test_requires_logged_in_user(self) -> None:
        client = Client(FakeSession(user=None))  # type: ignore[arg-type]
        with self.assertRaises(CatalogError):
            client.user_playlists()

    def test_playlist_tracks_paginates(self) -> None:
        tracks = [FakeTrack(f"t{i}", f"Song {i}") for i in range(101)]
        raw = FakeRawPlaylist("pl-1", "Drive", tracks=tracks)
        client = Client(FakeSession(catalog={"pl-1": raw}))  # type: ignore[arg-type]
        playlist, got = client.playlist_tracks("pl-1")
        self.assertEqual(playlist.title, "Drive")
        self.assertEqual(len(got), 101)
        self.assertEqual(got[0].id, "t0")
        self.assertEqual(got[-1].title, "Song 100")

    def test_to_playlist_hides_unknown_count(self) -> None:
        mapped = to_playlist(FakeRawPlaylist("pl-1", "Drive", num_tracks=-1))  # type: ignore[arg-type]
        self.assertEqual(mapped.track_count, None)
