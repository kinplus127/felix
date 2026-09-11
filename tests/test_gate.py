"""SessionGate shares one RLock across Client and resolve."""

from __future__ import annotations

import threading
import time
import unittest

from felix.tidal.gate import SessionGate, gate_for


class _FakeSession:
    def __init__(self) -> None:
        self.token = "a"
        self.seen: list[tuple[str, str]] = []


class TestSessionGate(unittest.TestCase):
    def test_gate_for_is_idempotent(self) -> None:
        session = _FakeSession()
        first = gate_for(session)  # type: ignore[arg-type]
        second = gate_for(session)  # type: ignore[arg-type]
        third = gate_for(first)
        self.assertIs(first, second)
        self.assertIs(first, third)
        self.assertIs(first.session, session)

    def test_reentrant_lock(self) -> None:
        gate = SessionGate(_FakeSession())  # type: ignore[arg-type]
        with gate:
            with gate:
                self.assertTrue(True)

    def test_concurrent_run_serializes_token_reads(self) -> None:
        session = _FakeSession()
        gate = gate_for(session)  # type: ignore[arg-type]
        errors: list[BaseException] = []
        barrier = threading.Barrier(2)

        def refresh() -> None:
            try:
                barrier.wait(timeout=2)
                with gate:
                    session.token = "b"
                    time.sleep(0.05)
                    session.token = "c"
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def read() -> None:
            try:
                barrier.wait(timeout=2)
                with gate:
                    start = session.token
                    time.sleep(0.05)
                    end = session.token
                    session.seen.append((start, end))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=refresh),
            threading.Thread(target=read),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        self.assertEqual(errors, [])
        self.assertEqual(len(session.seen), 1)
        start, end = session.seen[0]
        self.assertEqual(start, end)
        self.assertIn(start, {"a", "c"})
