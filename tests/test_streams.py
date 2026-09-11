"""MPD prune and resolve session locking."""

from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from felix.domain.models import Quality, SourceKind
from felix.tidal.quality import TO_TIDAL
from felix.tidal.streams import _prune_mpd, resolve


class TestPruneMpd(unittest.TestCase):
    def test_keeps_limit_and_protected(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            files = []
            for i in range(6):
                path = directory / f"felix-{i}.mpd"
                path.write_text("x", encoding="utf-8")
                files.append(path)
                time.sleep(0.02)
            keep = files[-1]
            protected = files[0]
            _prune_mpd(directory, keep=keep, limit=4, protected=(protected,))
            left = {path.name for path in directory.glob("felix-*.mpd")}
            self.assertIn(keep.name, left)
            self.assertIn(protected.name, left)
            self.assertEqual(len(left), 4)


class _FakeManifest:
    is_encrypted = False

    def get_urls(self) -> list[str]:
        return ["https://example.test/audio"]


class _FakeStream:
    is_mpd = False
    is_bts = True
    bit_depth = 16
    sample_rate = 44100
    track_replay_gain = None
    manifest_mime_type = "application/vnd.tidal.bts"

    def __init__(self, track_id: str, audio_quality: str) -> None:
        self.track_id = track_id
        self.audio_quality = audio_quality

    def get_stream_manifest(self) -> _FakeManifest:
        return _FakeManifest()


class _FakeTrack:
    def __init__(self, session: "_FakeSession", track_id: str) -> None:
        self.session = session
        self.id = track_id

    def get_stream(self) -> _FakeStream:
        start = self.session.audio_quality
        time.sleep(0.05)
        end = self.session.audio_quality
        self.session.seen.append((start, end))
        return _FakeStream(self.id, start)


class _FakeSession:
    """Stand-in session; gate_for() keys the shared lock off this object."""

    def __init__(self) -> None:
        self.audio_quality = TO_TIDAL[Quality.MAX]
        self.seen: list[tuple[str, str]] = []

    def track(self, track_id: str) -> _FakeTrack:
        return _FakeTrack(self, track_id)


class TestResolveSessionLock(unittest.TestCase):
    def test_concurrent_resolve_keeps_quality_stable(self) -> None:
        session = _FakeSession()
        errors: list[BaseException] = []
        barrier = threading.Barrier(2)

        def run(quality: Quality, track_id: str) -> None:
            try:
                barrier.wait(timeout=2)
                source = resolve(session, track_id, quality=quality)  # type: ignore[arg-type]
                self.assertEqual(source.kind, SourceKind.URL)
                self.assertEqual(source.requested, quality)
            except BaseException as exc:  # noqa: BLE001 — gather for main thread
                errors.append(exc)

        threads = [
            threading.Thread(target=run, args=(Quality.LOW, "1")),
            threading.Thread(target=run, args=(Quality.MAX, "2")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        self.assertEqual(errors, [])
        self.assertEqual(len(session.seen), 2)
        for start, end in session.seen:
            self.assertEqual(start, end)
        self.assertEqual(
            {start for start, _ in session.seen},
            {TO_TIDAL[Quality.LOW], TO_TIDAL[Quality.MAX]},
        )
        # Each resolve restores its own requested preference; last finisher wins.
        self.assertIn(
            session.audio_quality,
            {TO_TIDAL[Quality.LOW], TO_TIDAL[Quality.MAX]},
        )

    def test_client_and_resolve_share_the_same_gate(self) -> None:
        from felix.tidal.client import Client
        from felix.tidal.gate import gate_for

        session = _FakeSession()
        client = Client(session)  # type: ignore[arg-type]
        self.assertIs(client._gate, gate_for(session))  # type: ignore[arg-type]
