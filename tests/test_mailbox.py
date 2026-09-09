"""IntentMailbox FIFO. Does not start App or mpv."""

from __future__ import annotations

import threading
import time
import unittest

from felix.domain.intents import Pause, Resume, Search, Stop
from felix.runtime.app import IntentMailbox


class TestIntentMailbox(unittest.TestCase):
    def test_submit_returns_immediately_and_runs_fifo(self) -> None:
        seen: list[str] = []
        gate = threading.Event()
        started = threading.Event()

        def apply(intent: object) -> None:
            started.set()
            if isinstance(intent, Search):
                gate.wait(timeout=2)
                time.sleep(0.05)
            seen.append(type(intent).__name__)

        box = IntentMailbox(apply)
        try:
            t0 = time.monotonic()
            self.assertTrue(box.submit(Search("IVE")))
            self.assertTrue(box.submit(Pause()))
            self.assertTrue(box.submit(Resume()))
            self.assertLess(time.monotonic() - t0, 0.05)
            self.assertTrue(started.wait(timeout=1))
            self.assertEqual(seen, [])
            gate.set()
            deadline = time.monotonic() + 2
            while seen != ["Search", "Pause", "Resume"] and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(seen, ["Search", "Pause", "Resume"])
        finally:
            box.close()
        self.assertFalse(box.submit(Stop()))
        box.close()
