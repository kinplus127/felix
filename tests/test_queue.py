"""PlayQueue cursor. No network, no mpv."""

from __future__ import annotations

import random
import unittest

from felix.domain.models import RepeatMode
from felix.runtime.queue import PlayQueue


class TestPlayQueue(unittest.TestCase):
    def test_replace_and_next_prev(self) -> None:
        ids = tuple(f"t{i}" for i in range(11))
        q = PlayQueue()
        self.assertEqual(q.replace_with(ids, 2), "t2")
        self.assertEqual(q.play_order_ids()[:3], ["t0", "t1", "t2"])
        self.assertEqual(q.history, [])
        self.assertEqual(q.go_prev(), "t1")
        self.assertEqual(q.history, [])

    def test_repeat_all_wraps(self) -> None:
        ids = tuple(f"t{i}" for i in range(11))
        q = PlayQueue()
        q.replace_with(ids, 2)
        q.repeat = RepeatMode.ALL
        for _ in range(8):
            q.go_next()
        self.assertEqual(q.current(), "t10")
        self.assertEqual(q.go_next(), "t0")

    def test_duplicate_ids_use_cursor(self) -> None:
        q = PlayQueue()
        q.replace_with(["x", "y", "x"], 0)
        self.assertEqual(q.cursor(), 0)
        self.assertEqual(q.go_next(), "y")
        self.assertEqual(q.go_next(), "x")
        self.assertEqual(q.cursor(), 2)
        self.assertIsNone(q.go_next())

    def test_play_now_prefers_current_duplicate(self) -> None:
        q = PlayQueue()
        q.replace_with(["a", "b", "a"], 2)
        self.assertEqual(q.play_now("a"), "a")
        self.assertEqual(q.cursor(), 2)

    def test_play_now_finds_next_duplicate(self) -> None:
        q = PlayQueue()
        q.replace_with(["a", "b", "a"], 1)
        self.assertEqual(q.play_now("a"), "a")
        self.assertEqual(q.cursor(), 2)

    def test_shuffle_keeps_prefix_and_cursor(self) -> None:
        random.seed(1)
        q = PlayQueue()
        q.replace_with(["a", "b", "c", "d", "e"], 2)
        self.assertTrue(q.toggle_shuffle())
        self.assertEqual(q.current(), "c")
        self.assertEqual(q.play_order_ids()[:3], ["a", "b", "c"])
        self.assertEqual(set(q.play_order_ids()[3:]), {"d", "e"})

    def test_repeat_one_peeks_same_slot(self) -> None:
        q = PlayQueue()
        q.replace_with(["a", "b"], 0)
        q.repeat = RepeatMode.ONE
        self.assertEqual(q.peek_next(), "a")
        self.assertTrue(q.peek_is_replay())
        self.assertEqual(q.on_ended(), "a")
        self.assertEqual(q.cursor(), 0)

    def test_empty_queue(self) -> None:
        q = PlayQueue()
        self.assertIsNone(q.replace_with([], 0))
        self.assertIsNone(q.current())
        self.assertIsNone(q.go_next())
        self.assertIsNone(q.peek_next())

    def test_cycle_repeat(self) -> None:
        q = PlayQueue()
        self.assertEqual(q.cycle_repeat(), RepeatMode.ALL)
        self.assertEqual(q.cycle_repeat(), RepeatMode.ONE)
        self.assertEqual(q.cycle_repeat(), RepeatMode.OFF)
