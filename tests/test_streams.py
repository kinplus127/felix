"""MPD prune keeps newest and protected files."""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from felix.tidal.streams import _prune_mpd


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
