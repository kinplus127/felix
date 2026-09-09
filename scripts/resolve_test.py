"""Resolve a search hit into a PlaybackSource. Does not start mpv."""

from __future__ import annotations

import sys

from felix.tidal.auth import AuthError, load
from felix.tidal.client import Client
from felix.tidal.streams import StreamError, resolve


def main(argv: list[str]) -> int:
    query = " ".join(argv[1:]).strip() or "black midi hellfire"
    try:
        session = load()
    except AuthError as exc:
        print(f"尚未登入：{exc}", file=sys.stderr)
        return 1

    client = Client(session)
    tracks = client.search_tracks(query, limit=5)
    if not tracks:
        print(f"找不到：{query}", file=sys.stderr)
        return 1

    track = tracks[0]
    artists = ", ".join(track.artists) or "?"
    print(f"track     : {track.title}")
    print(f"artists   : {artists}")
    print(f"id        : {track.id}")
    print(f"duration  : {track.duration}s")
    print(f"album     : {track.album_title or '-'}")
    print()

    try:
        source = resolve(session, track.id)
    except StreamError as exc:
        print(f"取流失敗：{exc}", file=sys.stderr)
        return 1

    print(f"kind      : {source.kind}")
    print(f"quality   : {source.quality}")
    print(f"requested : {source.requested}")
    print(f"bit_depth : {source.bit_depth}")
    print(f"rate      : {source.sample_rate}")
    print(f"gain      : {source.replay_gain}")
    print(f"location  : {source.location}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
