"""Exercise queue / next / prev / shuffle / repeat via intents."""

from __future__ import annotations

import queue
import sys
import time

from felix.domain.events import (
    Event,
    Failed,
    Playing,
    Position,
    QueueUpdated,
    RepeatChanged,
    ShuffleChanged,
    Stopped,
    TrackResolved,
)
from felix.domain.intents import (
    CycleRepeat,
    Enqueue,
    Next,
    PlayTrack,
    Prev,
    Stop,
    ToggleShuffle,
)
from felix.domain.models import RepeatMode
from felix.runtime.app import App
from felix.tidal.auth import AuthError, load
from felix.tidal.client import Client


def _wait(events: queue.Queue[Event], kind: type, timeout: float) -> Event:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            event = events.get(timeout=min(0.2, remaining))
        except queue.Empty:
            continue
        if isinstance(event, Position):
            continue
        print(_format(event))
        if isinstance(event, Failed):
            raise RuntimeError(event.message)
        if isinstance(event, kind):
            return event
    raise TimeoutError(f"等待 {kind.__name__} 逾時")


def _wait_track(events: queue.Queue[Event], track_id: str, timeout: float) -> TrackResolved:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            event = events.get(timeout=min(0.2, remaining))
        except queue.Empty:
            continue
        if isinstance(event, Position):
            continue
        print(_format(event))
        if isinstance(event, Failed):
            raise RuntimeError(event.message)
        if isinstance(event, TrackResolved) and event.track.id == track_id:
            return event
    raise TimeoutError(f"等待 TrackResolved {track_id} 逾時")


def _format(event: Event) -> str:
    if isinstance(event, TrackResolved):
        return f"resolved  {event.track.title} ({event.track.id})"
    if isinstance(event, QueueUpdated):
        return f"queue     index={event.index} ids={event.track_ids} hist={event.history}"
    if isinstance(event, ShuffleChanged):
        return f"shuffle   {event.enabled}"
    if isinstance(event, RepeatChanged):
        return f"repeat    {event.mode}"
    if isinstance(event, Playing):
        return "playing"
    if isinstance(event, Stopped):
        return "stopped"
    if isinstance(event, Failed):
        return f"failed    {event.message}"
    return type(event).__name__.lower()


def main() -> int:
    try:
        session = load()
    except AuthError as exc:
        print(f"尚未登入：{exc}", file=sys.stderr)
        return 1

    client = Client(session)
    first = client.search_tracks("I WANT IVE", limit=1)
    second = client.search_tracks("black midi hellfire", limit=1)
    if not first or not second:
        print("搜尋失敗", file=sys.stderr)
        return 1
    a, b = first[0], second[0]
    print(f"a {a.id} {a.title}")
    print(f"b {b.id} {b.title}")

    events: queue.Queue[Event] = queue.Queue()
    app = App(session=session)
    app.subscribe(events.put)
    try:
        app.handle(PlayTrack(a.id))
        _wait_track(events, a.id, 20)
        _wait(events, Playing, 15)

        app.handle(Enqueue(b.id))
        queued = _wait(events, QueueUpdated, 5)
        assert isinstance(queued, QueueUpdated)
        if b.id not in queued.track_ids:
            raise RuntimeError("Enqueue 未進入 queue")

        app.handle(Next())
        _wait_track(events, b.id, 20)
        _wait(events, Playing, 15)

        app.handle(Prev())
        _wait_track(events, a.id, 20)
        _wait(events, Playing, 15)

        app.handle(ToggleShuffle())
        _wait(events, ShuffleChanged, 5)
        app.handle(CycleRepeat())
        repeat = _wait(events, RepeatChanged, 5)
        assert isinstance(repeat, RepeatChanged) and repeat.mode is RepeatMode.ALL

        app.handle(Stop())
        _wait(events, Stopped, 5)
        return 0
    except (TimeoutError, RuntimeError, AssertionError) as exc:
        print(f"測試失敗：{exc}", file=sys.stderr)
        return 1
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main())
