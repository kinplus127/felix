"""Fan out events to listeners. Does not know what an event means."""

from __future__ import annotations

import threading
from collections.abc import Callable

from felix.domain.events import Event
from felix.logs import get_logger

log = get_logger("bus")

Listener = Callable[[Event], None]


class EventBus:
    """Thread-safe fan-out. One failing listener never stops the others."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[int, Listener] = {}
        self._next_token = 1

    def subscribe(self, listener: Listener) -> int:
        """Register a listener. The token is what unsubscribe() needs."""
        with self._lock:
            token = self._next_token
            self._next_token += 1
            self._subscribers[token] = listener
        return token

    def unsubscribe(self, token: int) -> bool:
        with self._lock:
            return self._subscribers.pop(token, None) is not None

    def count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def publish(self, event: Event) -> None:
        # Copy first: a listener may subscribe or unsubscribe from its callback.
        with self._lock:
            listeners = list(self._subscribers.values())
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                log.exception("listener failed on %s", type(event).__name__)
