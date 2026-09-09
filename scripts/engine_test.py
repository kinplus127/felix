"""Exercise mpv IPC with a local file or an already-resolved MPD. No TIDAL."""

from __future__ import annotations

import queue
import sys
import time
from pathlib import Path

from felix.domain.models import PlaybackSource, Quality, SourceKind
from felix.engine.controller import Controller, EngineEvent

DEFAULT_FILE = Path("/home/kinplus/felix/0033067141.flac")


def _source_for(path: Path) -> PlaybackSource:
    kind = SourceKind.MPD_FILE if path.suffix.lower() == ".mpd" else SourceKind.FILE
    return PlaybackSource(
        kind=kind,
        location=str(path),
        quality="local",
        bit_depth=None,
        sample_rate=None,
        requested=Quality.MAX,
    )


def _wait(events: queue.Queue[EngineEvent], name: str, timeout: float) -> EngineEvent:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            event = events.get(timeout=min(0.2, remaining))
        except queue.Empty:
            continue
        if event.name == "time":
            continue
        print(f"{event.name:<9} {event.payload if event.payload is not None else ''}".rstrip())
        if event.name == name:
            return event
        if event.name == "error":
            raise RuntimeError(event.payload)
    raise TimeoutError(f"等待 {name} 逾時")


def _wait_time_at_least(
    events: queue.Queue[EngineEvent], seconds: float, timeout: float
) -> float:
    deadline = time.monotonic() + timeout
    last = 0.0
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            event = events.get(timeout=min(0.2, remaining))
        except queue.Empty:
            continue
        if event.name == "time":
            last = float(event.payload)
            if last >= seconds:
                print(f"time      {last:.2f}")
                return last
            continue
        if event.name == "error":
            raise RuntimeError(event.payload)
        print(f"{event.name:<9} {event.payload if event.payload is not None else ''}".rstrip())
    raise TimeoutError(f"等待 playback-time >= {seconds} 逾時（最後 {last:.2f}）")


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_FILE
    if not path.exists():
        print(f"找不到檔案：{path}", file=sys.stderr)
        return 1

    controller = Controller()
    controller.start()
    try:
        print(f"load      {path}")
        controller.play(_source_for(path))
        _wait(controller.events, "playing", 8)
        _wait(controller.events, "duration", 8)
        _wait_time_at_least(controller.events, 1.5, 8)

        controller.pause()
        _wait(controller.events, "paused", 5)
        time.sleep(0.4)
        controller.resume()
        _wait(controller.events, "resumed", 5)

        controller.seek(10)
        _wait_time_at_least(controller.events, 9.5, 8)

        controller.stop()
        print("stopped")
        return 0
    except (TimeoutError, RuntimeError) as exc:
        print(f"測試失敗：{exc}", file=sys.stderr)
        return 1
    finally:
        controller.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
