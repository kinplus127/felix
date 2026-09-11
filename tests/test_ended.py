"""Natural eof hands queue advance to the transport worker. No mpv."""

from __future__ import annotations

import threading
import unittest

from felix.domain.events import Ended
from felix.domain.intents import ContinueAfterEnd, Intent
from felix.domain.models import RepeatMode, Track
from felix.engine.controller import EngineEvent
from felix.runtime.app import App
from felix.runtime.bus import EventBus
from felix.runtime.now_playing import NowPlaying
from felix.runtime.queue import PlayQueue


class _RecordingMailbox:
    def __init__(self) -> None:
        self.seen: list[Intent] = []

    def submit(self, intent: Intent) -> bool:
        self.seen.append(intent)
        return True


def _track(track_id: str) -> Track:
    return Track(id=track_id, title=track_id, artists=("x",), duration=1)


def _ended_app() -> App:
    app = App.__new__(App)
    app._lock = threading.Lock()
    app._latest_search = None
    app._transport = _RecordingMailbox()
    app._catalog = _RecordingMailbox()
    app.now = NowPlaying()
    app.queue = PlayQueue()
    app._bus = EventBus()
    app._switching = False
    app._play_seq = 1
    app.now.state = "playing"
    app.now.track = _track("a")
    app.started: list[str] = []
    app._start_track = lambda track_id: app.started.append(track_id)  # type: ignore[method-assign]
    return app


class TestContinueAfterEnd(unittest.TestCase):
    def test_eof_submits_to_transport_without_starting(self) -> None:
        app = _ended_app()
        app.queue.replace_with(["a", "b"], 0)
        events: list[object] = []
        app._bus.subscribe(events.append)

        app._on_engine(EngineEvent("eof"))

        self.assertEqual(app.now.state, "stopped")
        self.assertEqual(app._transport.seen, [ContinueAfterEnd(1)])
        self.assertEqual(app._catalog.seen, [])
        self.assertEqual(app.started, [])
        self.assertEqual(app.queue.current(), "a")
        self.assertTrue(any(isinstance(event, Ended) for event in events))

    def test_apply_advances_and_starts_next(self) -> None:
        app = _ended_app()
        app.queue.replace_with(["a", "b"], 0)
        app._apply_intent(ContinueAfterEnd(1))
        self.assertEqual(app.queue.current(), "b")
        self.assertEqual(app.started, ["b"])

    def test_repeat_one_replays_same_slot(self) -> None:
        app = _ended_app()
        app.queue.replace_with(["a", "b"], 0)
        app.queue.repeat = RepeatMode.ONE
        app._apply_intent(ContinueAfterEnd(1))
        self.assertEqual(app.queue.current(), "a")
        self.assertEqual(app.started, ["a"])

    def test_stale_after_new_play_is_ignored(self) -> None:
        app = _ended_app()
        app.queue.replace_with(["a", "b"], 0)
        app._play_seq = 2
        app._apply_intent(ContinueAfterEnd(1))
        self.assertEqual(app.queue.current(), "a")
        self.assertEqual(app.started, [])

    def test_last_track_does_not_start(self) -> None:
        app = _ended_app()
        app.queue.replace_with(["a"], 0)
        app._apply_intent(ContinueAfterEnd(1))
        self.assertIsNone(app.queue.current())
        self.assertEqual(app.started, [])

    def test_eof_during_output_switch_is_ignored(self) -> None:
        app = _ended_app()
        app._switching = True
        app._on_engine(EngineEvent("eof"))
        self.assertEqual(app._transport.seen, [])
        self.assertEqual(app.started, [])
        self.assertEqual(app.now.state, "playing")
