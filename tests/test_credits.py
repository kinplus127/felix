"""Credits JSON and LRC strip. No TIDAL session."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from felix.tidal.client import _strip_lrc
from felix.tidal.credits import parse_contributors, year_from_album


class TestCredits(unittest.TestCase):
    def test_parse_grouped_contributors(self) -> None:
        data = {
            "items": [
                {
                    "type": "Producer",
                    "contributors": [{"name": "Seo Won-jin"}, {"name": "Seo Won-jin"}],
                },
                {"role": "Lyricist", "contributors": [{"name": "Jang Won-young"}]},
                {"type": "PRIMARY_ARTIST", "contributors": [{"name": "IVE"}]},
            ]
        }
        groups = parse_contributors(data)
        self.assertEqual(
            groups,
            [
                ("Producer", ["Seo Won-jin"]),
                ("Lyricist", ["Jang Won-young"]),
            ],
        )

    def test_year_from_album(self) -> None:
        album = SimpleNamespace(year=2021, release_date=None)
        self.assertEqual(year_from_album(album), 2021)
        dated = SimpleNamespace(year=None, release_date=SimpleNamespace(year=2019))
        self.assertEqual(year_from_album(dated), 2019)

    def test_strip_lrc(self) -> None:
        raw = "[00:12.00] hello\n[00:15.50] world\n"
        self.assertEqual(_strip_lrc(raw), "hello\nworld")
