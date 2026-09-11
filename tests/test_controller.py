"""Controller mpv message mapping. Does not start mpv."""

from __future__ import annotations

import queue
import unittest

from felix.engine.controller import Controller, EngineEvent
from felix.engine.pcm import PcmReading


def _bare_controller() -> Controller:
    controller = Controller.__new__(Controller)
    controller.events = queue.Queue()
    controller._pcm = PcmReading()
    return controller


def _drain(controller: Controller) -> list[EngineEvent]:
    seen: list[EngineEvent] = []
    while True:
        try:
            seen.append(controller.events.get_nowait())
        except queue.Empty:
            return seen


def _names(controller: Controller) -> list[str]:
    return [event.name for event in _drain(controller)]


class TestControllerEof(unittest.TestCase):
    def test_end_file_eof_emits_once(self) -> None:
        controller = _bare_controller()
        controller._on_message({"event": "end-file", "reason": "eof"})
        self.assertEqual(_names(controller), ["eof"])

    def test_eof_reached_does_not_emit(self) -> None:
        controller = _bare_controller()
        controller._on_message(
            {"event": "property-change", "name": "eof-reached", "data": True}
        )
        self.assertEqual(_names(controller), [])

    def test_eof_reached_then_end_file_emits_once(self) -> None:
        controller = _bare_controller()
        controller._on_message(
            {"event": "property-change", "name": "eof-reached", "data": True}
        )
        controller._on_message({"event": "end-file", "reason": "eof"})
        self.assertEqual(_names(controller), ["eof"])

    def test_end_file_then_eof_reached_emits_once(self) -> None:
        controller = _bare_controller()
        controller._on_message({"event": "end-file", "reason": "eof"})
        controller._on_message(
            {"event": "property-change", "name": "eof-reached", "data": True}
        )
        self.assertEqual(_names(controller), ["eof"])

    def test_end_file_error_is_not_eof(self) -> None:
        controller = _bare_controller()
        controller._on_message(
            {
                "event": "end-file",
                "reason": "error",
                "file_error": "loading failed",
            }
        )
        events = _drain(controller)
        self.assertEqual([event.name for event in events], ["error"])
        self.assertEqual(events[0].payload, "loading failed")

    def test_end_file_stop_is_silent(self) -> None:
        controller = _bare_controller()
        controller._on_message({"event": "end-file", "reason": "stop"})
        self.assertEqual(_names(controller), [])
