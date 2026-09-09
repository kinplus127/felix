"""Play one TIDAL track through runtime intents. No UI."""

from __future__ import annotations

import queue
import sys
import time

from felix.domain.events import (
    Ended,
    Event,
    Failed,
    Paused,
    Playing,
    Position,
    SourceReady,
    Stopped,
    TrackResolved,
)
from felix.domain.intents import PlayTrack, Seek, Stop, TogglePause
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


def _wait_position(
    events: queue.Queue[Event], seconds: float, timeout: float
) -> Position:
    deadline = time.monotonic() + timeout
    last = 0.0
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            event = events.get(timeout=min(0.2, remaining))
        except queue.Empty:
            continue
        if isinstance(event, Failed):
            raise RuntimeError(event.message)
        if isinstance(event, Position):
            last = event.seconds
            if last >= seconds:
                print(_format(event))
                return event
            continue
        print(_format(event))
    raise TimeoutError(f"等待 Position >= {seconds} 逾時（最後 {last:.2f}）")


def _format(event: Event) -> str:
    if isinstance(event, TrackResolved):
        artists = ", ".join(event.track.artists)
        return f"resolved  {event.track.title} — {artists} ({event.track.id})"
    if isinstance(event, SourceReady):
        src = event.source
        return (
            f"source    {src.kind} {src.quality} "
            f"{src.bit_depth}/{src.sample_rate} {src.location}"
        )
    if isinstance(event, Playing):
        return "playing"
    if isinstance(event, Paused):
        return "paused"
    if isinstance(event, Position):
        duration = f"{event.duration:.1f}" if event.duration is not None else "?"
        return f"position  {event.seconds:.2f} / {duration}"
    if isinstance(event, Ended):
        return "ended"
    if isinstance(event, Stopped):
        return "stopped"
    if isinstance(event, Failed):
        return f"failed    {event.message}"
    return str(event)


def main(argv: list[str]) -> int:
    query = " ".join(argv[1:]).strip() or "I WANT IVE"
    try:
        session = load()
    except AuthError as exc:
        print(f"尚未登入：{exc}", file=sys.stderr)
        return 1

    tracks = Client(session).search_tracks(query, limit=1)
    if not tracks:
        print(f"找不到：{query}", file=sys.stderr)
        return 1

    events: queue.Queue[Event] = queue.Queue()
    app = App(session=session)
    app.subscribe(events.put)
    try:
        app.handle(PlayTrack(tracks[0].id))
        _wait(events, TrackResolved, 15)
        _wait(events, SourceReady, 15)
        _wait(events, Playing, 15)
        _wait_position(events, 1.5, 10)

        app.handle(TogglePause())
        _wait(events, Paused, 5)
        app.handle(TogglePause())
        _wait(events, Playing, 5)

        app.handle(Seek(10))
        _wait_position(events, 9.5, 8)

        app.handle(Stop())
        _wait(events, Stopped, 5)
        return 0
    except (TimeoutError, RuntimeError) as exc:
        print(f"測試失敗：{exc}", file=sys.stderr)
        return 1
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
