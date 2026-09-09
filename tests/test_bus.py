"""EventBus fan-out and unsubscribe. No App, no mpv, no network."""

from __future__ import annotations

import threading
import unittest

from felix.domain.events import Paused, Playing
from felix.runtime.bus import EventBus


class TestEventBus(unittest.TestCase):
    def test_publish_reaches_every_subscriber(self) -> None:
        bus = EventBus()
        a: list[object] = []
        b: list[object] = []
        bus.subscribe(a.append)
        bus.subscribe(b.append)

        bus.publish(Playing())

        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)

    def test_failing_listener_does_not_stop_the_others(self) -> None:
        """The whole point: a broken UI must not kill playback events."""
        bus = EventBus()
        before: list[object] = []
        after: list[object] = []

        def explode(_event: object) -> None:
            raise RuntimeError("listener is broken")

        bus.subscribe(before.append)
        bus.subscribe(explode)
        bus.subscribe(after.append)

        with self.assertLogs("felix.bus", level="ERROR"):
            bus.publish(Playing())
            bus.publish(Paused())

        self.assertEqual(len(before), 2)
        self.assertEqual(len(after), 2)

    def test_unsubscribe_stops_delivery(self) -> None:
        bus = EventBus()
        seen: list[object] = []
        token = bus.subscribe(seen.append)

        bus.publish(Playing())
        self.assertTrue(bus.unsubscribe(token))
        bus.publish(Playing())

        self.assertEqual(len(seen), 1)
        self.assertEqual(bus.count(), 0)

    def test_unsubscribe_twice_is_harmless(self) -> None:
        bus = EventBus()
        token = bus.subscribe(lambda _event: None)

        self.assertTrue(bus.unsubscribe(token))
        self.assertFalse(bus.unsubscribe(token))

    def test_bound_method_unsubscribes_by_token(self) -> None:
        """A token works where list.remove() would not: each attribute
        lookup builds a fresh bound method object."""

        class View:
            def __init__(self) -> None:
                self.seen: list[object] = []

            def on_event(self, event: object) -> None:
                self.seen.append(event)

        bus = EventBus()
        view = View()
        token = bus.subscribe(view.on_event)

        self.assertIsNot(view.on_event, view.on_event)
        self.assertTrue(bus.unsubscribe(token))

        bus.publish(Playing())
        self.assertEqual(view.seen, [])

    def test_listener_may_unsubscribe_itself_during_publish(self) -> None:
        bus = EventBus()
        seen: list[object] = []
        token = 0

        def once(event: object) -> None:
            seen.append(event)
            bus.unsubscribe(token)

        token = bus.subscribe(once)
        bus.publish(Playing())
        bus.publish(Paused())

        self.assertEqual(len(seen), 1)

    def test_concurrent_subscribe_and_publish(self) -> None:
        bus = EventBus()
        errors: list[BaseException] = []

        def churn() -> None:
            try:
                for _ in range(200):
                    token = bus.subscribe(lambda _event: None)
                    bus.publish(Playing())
                    bus.unsubscribe(token)
            except BaseException as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        threads = [threading.Thread(target=churn) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(bus.count(), 0)


if __name__ == "__main__":
    unittest.main()
