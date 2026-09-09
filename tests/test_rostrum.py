"""Rostrum dispatch and status text. No live App / mpv."""

from __future__ import annotations

import unittest

from felix.domain.events import FormatReady, LyricsReady, PlaylistOpened, PlaylistsReady
from felix.domain.intents import (
    AdjustVolume,
    ListPlaylists,
    OpenPlaylist,
    PlayList,
    PlayPlaylist,
    Search,
    SetAudioOutput,
    SetVolume,
)
from felix.domain.models import Lyrics, Playlist, Track
from felix.rostrum import (
    CommandError,
    Rostrum,
    format_ao,
    format_event,
    format_status,
)
from felix.runtime.app import RuntimeStatus
from felix.runtime.now_playing import NowPlaying
from felix.runtime.queue import PlayQueue
from felix.settings import SYSTEM_ALSA_WARNING


class FakeApp:
    def __init__(self, status: RuntimeStatus | None = None) -> None:
        self.now = NowPlaying()
        self.queue = PlayQueue()
        self._status = status or _status()

    def subscribe(self, listener: object) -> None:
        return None

    def status(self) -> RuntimeStatus:
        return self._status


def _status(**kwargs: object) -> RuntimeStatus:
    fields: dict[str, object] = {
        "log_path": "/tmp/felix.log",
        "exclusive": False,
        "ao": "pipewire",
        "ao_pref": "",
        "audio_device": "auto",
        "exclusive_device": "",
        "volume": 100.0,
        "last_error": "",
        "source_rate": None,
        "source_bits": None,
        "decode_rate": None,
        "decode_format": "",
        "output_rate": None,
        "output_format": "",
        "pcm_matched": None,
    }
    fields.update(kwargs)
    return RuntimeStatus(**fields)  # type: ignore[arg-type]


class TestDispatch(unittest.TestCase):
    def setUp(self) -> None:
        self.rostrum = Rostrum(FakeApp())  # type: ignore[arg-type]

    def test_basic_commands(self) -> None:
        self.assertEqual(self.rostrum.dispatch("help"), "help")
        self.assertEqual(self.rostrum.dispatch("search IVE"), Search("IVE"))
        self.assertEqual(self.rostrum.dispatch("vol"), "vol")
        self.assertEqual(self.rostrum.dispatch("vol 40"), SetVolume(40.0))
        self.assertEqual(self.rostrum.dispatch("vol +5"), AdjustVolume(5.0))

    def test_ao_commands(self) -> None:
        self.assertEqual(self.rostrum.dispatch("ao"), "ao")
        self.assertEqual(
            self.rostrum.dispatch("ao system"),
            SetAudioOutput(exclusive=False),
        )
        self.assertEqual(
            self.rostrum.dispatch("ao exclusive"),
            SetAudioOutput(exclusive=True),
        )
        self.assertEqual(
            self.rostrum.dispatch("ao pipewire"),
            SetAudioOutput(exclusive=False, ao="pipewire"),
        )
        self.assertEqual(
            self.rostrum.dispatch("ao alsa"),
            SetAudioOutput(exclusive=False, ao="alsa"),
        )
        self.assertEqual(
            self.rostrum.dispatch("ao exclusive hw:CARD=Qutest,DEV=0"),
            SetAudioOutput(exclusive=True, exclusive_device="hw:CARD=Qutest,DEV=0"),
        )

    def test_play_without_list_fails(self) -> None:
        with self.assertRaises(CommandError):
            self.rostrum.dispatch("play 0")

    def test_playlists_commands(self) -> None:
        self.assertEqual(self.rostrum.dispatch("playlists"), ListPlaylists())
        with self.assertRaises(CommandError):
            self.rostrum.dispatch("playlist 0")
        with self.assertRaises(CommandError):
            self.rostrum.dispatch("play 0")

        self.rostrum.note(
            PlaylistsReady(
                (
                    Playlist(id="pl-1", title="Drive", track_count=2),
                    Playlist(id="pl-2", title="Night", track_count=1),
                )
            )
        )
        self.assertEqual(self.rostrum.dispatch("playlist 1"), OpenPlaylist("pl-2"))
        self.assertEqual(self.rostrum.dispatch("playlist p0"), OpenPlaylist("pl-1"))
        self.assertEqual(self.rostrum.dispatch("play 0"), PlayPlaylist("pl-1"))

        tracks = (
            Track(id="t1", title="A", artists=("X",), duration=10),
            Track(id="t2", title="B", artists=("Y",), duration=20),
        )
        self.rostrum.note(PlaylistOpened(Playlist("pl-1", "Drive", 2), tracks))
        self.assertEqual(
            self.rostrum.dispatch("play 1"),
            PlayList(("t1", "t2"), 1),
        )


class TestFormat(unittest.TestCase):
    def test_lyrics_none_and_text(self) -> None:
        empty = format_event(LyricsReady(Lyrics("1", "", False)))
        self.assertEqual(empty, "lyrics    1  (none)")
        text = format_event(LyricsReady(Lyrics("1", "hello", False)))
        self.assertEqual(text, "lyrics    1  text\nhello")

    def test_pcm_exclusive_match(self) -> None:
        event = FormatReady(
            source_rate=96000,
            source_bits=24,
            decode_rate=96000,
            decode_format="s32",
            output_rate=96000,
            output_format="s32",
            matched=True,
            exclusive=True,
        )
        line = format_event(event)
        assert line is not None
        self.assertIn("src 24/96000", line)
        self.assertIn("out s32/96000", line)
        self.assertIn("match", line)

    def test_pcm_system_is_pipewire_not_match(self) -> None:
        event = FormatReady(
            source_rate=96000,
            source_bits=24,
            decode_rate=96000,
            decode_format="s32",
            output_rate=96000,
            output_format="s32",
            matched=None,
            exclusive=False,
        )
        line = format_event(event)
        assert line is not None
        self.assertIn("pipewire", line)
        self.assertNotIn("match", line)

    def test_status_pcm_and_alsa_warning(self) -> None:
        snap = _status(
            exclusive=True,
            ao="alsa/hw:CARD=Qutest,DEV=0",
            ao_pref="pipewire",
            exclusive_device="hw:CARD=Qutest,DEV=0",
            source_rate=96000,
            source_bits=24,
            decode_rate=96000,
            decode_format="s32",
            output_rate=96000,
            output_format="s32",
            pcm_matched=True,
        )
        text = format_status(FakeApp(snap))  # type: ignore[arg-type]
        self.assertIn("pcm       src 24/96000", text)
        self.assertIn("out s32/96000", text)
        self.assertIn("match", text)
        self.assertNotIn("warning", text)

        alsa = _status(exclusive=False, ao="alsa", ao_pref="alsa")
        ao_text = format_ao(FakeApp(alsa))  # type: ignore[arg-type]
        self.assertIn(SYSTEM_ALSA_WARNING, ao_text)
        status = format_status(FakeApp(alsa))  # type: ignore[arg-type]
        self.assertIn("warning", status)
        self.assertIn(SYSTEM_ALSA_WARNING, status)

    def test_playlists_format(self) -> None:
        listed = format_event(
            PlaylistsReady((Playlist(id="pl-1", title="Drive", track_count=2),))
        )
        self.assertEqual(listed, "playlists 1\n  p0   Drive  (2)")
        opened = format_event(
            PlaylistOpened(
                Playlist("pl-1", "Drive", 2),
                (Track(id="t1", title="A", artists=("X",), duration=10),),
            )
        )
        self.assertEqual(opened, "playlist Drive  (1 tracks)\n  t0   A — X")
