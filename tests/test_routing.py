"""Intent routing across the transport and catalog workers. No mpv, no network."""

from __future__ import annotations

import threading
import time
import unittest

from felix.domain.intents import (
    Intent,
    ListPlaylists,
    Next,
    OpenAlbum,
    OpenArtist,
    OpenPlaylist,
    Pause,
    PlayList,
    PlayPlaylist,
    PlayTrack,
    Search,
    Seek,
    SetVolume,
    ShowCredits,
    ShowLyrics,
    Stop,
)
from felix.runtime.app import App, IntentMailbox


class _RecordingMailbox:
    def __init__(self) -> None:
        self.seen: list[Intent] = []

    def submit(self, intent: Intent) -> bool:
        self.seen.append(intent)
        return True


def _bare_app() -> App:
    """Just enough App to exercise handle(). No engine, no session."""
    app = App.__new__(App)
    app._lock = threading.Lock()
    app._latest_search = None
    app._transport = _RecordingMailbox()
    app._catalog = _RecordingMailbox()
    return app


class TestIntentRouting(unittest.TestCase):
    def test_transport_intents_stay_on_transport(self) -> None:
        app = _bare_app()
        intents = (
            PlayTrack("1"),
            PlayList(("1", "2")),
            Pause(),
            Next(),
            Seek(10.0),
            SetVolume(50.0),
            Stop(),
        )
        for intent in intents:
            app.handle(intent)

        self.assertEqual(app._transport.seen, list(intents))
        self.assertEqual(app._catalog.seen, [])

    def test_catalog_intents_go_to_the_catalog_worker(self) -> None:
        app = _bare_app()
        intents = (
            Search("ive"),
            OpenAlbum("1"),
            OpenArtist("1"),
            ListPlaylists(),
            OpenPlaylist("1"),
            PlayPlaylist("1"),
            ShowLyrics("1"),
            ShowCredits("1"),
        )
        for intent in intents:
            app.handle(intent)

        self.assertEqual(app._catalog.seen, list(intents))
        self.assertEqual(app._transport.seen, [])

    def test_only_the_latest_search_is_allowed_to_emit(self) -> None:
        app = _bare_app()
        first = Search("ive")
        second = Search("ive baddie")

        app.handle(first)
        self.assertFalse(app._search_superseded(first))

        app.handle(second)
        self.assertTrue(app._search_superseded(first))
        self.assertFalse(app._search_superseded(second))

    def test_slow_catalog_work_does_not_delay_transport(self) -> None:
        """The reason the split exists: pause must not queue behind a search."""
        order: list[str] = []
        search_running = threading.Event()
        pause_done = threading.Event()

        def apply(intent: Intent) -> None:
            if isinstance(intent, Search):
                search_running.set()
                time.sleep(0.5)
                order.append("search")
            else:
                order.append("pause")
                pause_done.set()

        catalog = IntentMailbox(apply, name="test-catalog")
        transport = IntentMailbox(apply, name="test-transport")
        try:
            catalog.submit(Search("slow query"))
            self.assertTrue(search_running.wait(timeout=2))

            transport.submit(Pause())
            self.assertTrue(
                pause_done.wait(timeout=1.0), "pause was stuck behind the search"
            )
            self.assertEqual(order, ["pause"])
        finally:
            catalog.close()
            transport.close()

        self.assertEqual(order, ["pause", "search"])


if __name__ == "__main__":
    unittest.main()
