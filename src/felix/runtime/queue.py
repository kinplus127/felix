"""Playlist cursor. Does not resolve streams or talk to mpv."""

from __future__ import annotations

import random

from felix.domain.models import RepeatMode


class PlayQueue:
    def __init__(self) -> None:
        self._items: list[str] = []
        self._index: int | None = None
        self._order: list[int] = []
        self.shuffle = False
        self.repeat = RepeatMode.OFF
        self.history: list[str] = []

    def play_order_ids(self) -> list[str]:
        if self.shuffle and self._order:
            return [self._items[i] for i in self._order]
        return list(self._items)

    def cursor(self) -> int | None:
        return self._index

    def current(self) -> str | None:
        ids = self.play_order_ids()
        if self._index is None or not ids:
            return None
        if self._index < 0 or self._index >= len(ids):
            return None
        return ids[self._index]

    def snapshot(self) -> tuple[tuple[str, ...], int | None, tuple[str, ...]]:
        return (tuple(self.play_order_ids()), self._index, tuple(self.history))

    def replace_with(self, track_ids: tuple[str, ...] | list[str], start_index: int = 0) -> str | None:
        """Replace the queue. Cursor sits on start_index; earlier tracks stay before it."""
        ids = [track_id for track_id in track_ids if track_id]
        self._items = ids
        self.history = []
        if not ids:
            self._index = None
            self._order = []
            return None
        start = max(0, min(start_index, len(ids) - 1))
        self._index = start
        if self.shuffle:
            self._shuffle_from_cursor()
        else:
            self._order = []
        return self.current()

    def enqueue(self, track_id: str) -> None:
        self._items.append(track_id)
        if self.shuffle:
            self._order.append(len(self._items) - 1)

    def play_now(self, track_id: str) -> str:
        found = self._find_play_index(track_id)
        if found is not None:
            self._index = found
            return track_id

        self._items.append(track_id)
        item_idx = len(self._items) - 1
        if self.shuffle:
            if self._index is None:
                self._order.append(item_idx)
                self._index = len(self._order) - 1
            else:
                self._order.insert(self._index + 1, item_idx)
                self._index += 1
        else:
            self._index = item_idx
        return track_id

    def go_next(self) -> str | None:
        ids = self.play_order_ids()
        if not ids or self._index is None:
            return None
        self._remember()
        nxt = self._index + 1
        if nxt < len(ids):
            self._index = nxt
            return self.current()
        if self.repeat is RepeatMode.ALL:
            self._index = 0
            return self.current()
        self._index = None
        return None

    def go_prev(self) -> str | None:
        ids = self.play_order_ids()
        if not ids or self._index is None:
            return None
        if self._index > 0:
            self._index -= 1
            return self.current()
        if self.repeat is RepeatMode.ALL:
            self._index = len(ids) - 1
            return self.current()
        return self.current()

    def on_ended(self) -> str | None:
        if self.repeat is RepeatMode.ONE:
            return self.current()
        return self.go_next()

    def peek_next(self) -> str | None:
        """Next id after the current cursor, without moving it."""
        ids = self.play_order_ids()
        if not ids or self._index is None:
            return None
        if self.repeat is RepeatMode.ONE:
            return self.current()
        nxt = self._index + 1
        if nxt < len(ids):
            return ids[nxt]
        if self.repeat is RepeatMode.ALL:
            return ids[0]
        return None

    def peek_is_replay(self) -> bool:
        """True when the next play is this same queue slot (repeat one)."""
        return self.repeat is RepeatMode.ONE and self.current() is not None

    def toggle_shuffle(self) -> bool:
        slot = self._current_item_index()
        self.shuffle = not self.shuffle
        if self.shuffle:
            self._index = slot
            self._shuffle_from_cursor()
        else:
            self._order = []
            self._index = slot
        return self.shuffle

    def cycle_repeat(self) -> RepeatMode:
        order = (RepeatMode.OFF, RepeatMode.ALL, RepeatMode.ONE)
        self.repeat = order[(order.index(self.repeat) + 1) % len(order)]
        return self.repeat

    def _find_play_index(self, track_id: str) -> int | None:
        """Prefer the current slot, then the next occurrence after the cursor."""
        ids = self.play_order_ids()
        if not ids:
            return None
        if self.current() == track_id:
            return self._index
        start = 0 if self._index is None else self._index + 1
        for offset in range(len(ids)):
            index = (start + offset) % len(ids)
            if ids[index] == track_id:
                return index
        return None

    def _current_item_index(self) -> int | None:
        if self._index is None:
            return None
        if self.shuffle and self._order:
            if 0 <= self._index < len(self._order):
                return self._order[self._index]
            return None
        if 0 <= self._index < len(self._items):
            return self._index
        return None

    def _shuffle_from_cursor(self) -> None:
        count = len(self._items)
        if count == 0:
            self._order = []
            return
        if self._index is None:
            order = list(range(count))
            random.shuffle(order)
            self._order = order
            return
        cursor = self._index
        before = list(range(cursor))
        after = list(range(cursor + 1, count))
        random.shuffle(after)
        self._order = before + [cursor] + after
        self._index = cursor

    def _remember(self) -> None:
        current = self.current()
        if current is not None:
            self.history.append(current)
