"""Search tracks / albums / artists through runtime intents. No playback."""

from __future__ import annotations

import queue
import sys
import time

from felix.domain.events import AlbumOpened, ArtistOpened, Event, Failed, SearchReady
from felix.domain.intents import OpenAlbum, OpenArtist, Search
from felix.runtime.app import App
from felix.tidal.auth import AuthError, load


def _wait(events: queue.Queue[Event], kind: type, timeout: float) -> Event:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            event = events.get(timeout=min(0.2, remaining))
        except queue.Empty:
            continue
        if isinstance(event, Failed):
            raise RuntimeError(event.message)
        if isinstance(event, kind):
            return event
    raise TimeoutError(f"等待 {kind.__name__} 逾時")


def _print_search(event: SearchReady) -> None:
    results = event.results
    print(f"query     {results.query}")
    print(f"tracks    {len(results.tracks)}")
    for track in results.tracks[:5]:
        artists = ", ".join(track.artists)
        print(f"  {track.id}  {track.title} — {artists}")
    print(f"albums    {len(results.albums)}")
    for album in results.albums[:5]:
        artists = ", ".join(album.artists)
        year = album.year or "-"
        print(f"  {album.id}  {album.title} ({year}) — {artists}")
    print(f"artists   {len(results.artists)}")
    for artist in results.artists[:5]:
        print(f"  {artist.id}  {artist.name}")


def main(argv: list[str]) -> int:
    query = " ".join(argv[1:]).strip() or "IVE"
    try:
        session = load()
    except AuthError as exc:
        print(f"尚未登入：{exc}", file=sys.stderr)
        return 1

    events: queue.Queue[Event] = queue.Queue()
    app = App(session=session)
    app.subscribe(events.put)
    try:
        app.handle(Search(query))
        ready = _wait(events, SearchReady, 15)
        assert isinstance(ready, SearchReady)
        _print_search(ready)
        if not (ready.results.tracks or ready.results.albums or ready.results.artists):
            raise RuntimeError("搜尋沒有結果")

        if ready.results.albums:
            album = ready.results.albums[0]
            app.handle(OpenAlbum(album.id))
            opened = _wait(events, AlbumOpened, 15)
            assert isinstance(opened, AlbumOpened)
            print(f"album     {opened.album.title}  tracks={len(opened.tracks)}")
            if not opened.tracks:
                raise RuntimeError("專輯沒有曲目")

        if ready.results.artists:
            artist = ready.results.artists[0]
            app.handle(OpenArtist(artist.id))
            page = _wait(events, ArtistOpened, 15)
            assert isinstance(page, ArtistOpened)
            print(
                f"artist    {page.artist.name}  "
                f"top={len(page.tracks)} albums={len(page.albums)}"
            )
            if not page.tracks and not page.albums:
                raise RuntimeError("藝人沒有曲目或專輯")
        return 0
    except (TimeoutError, RuntimeError, AssertionError) as exc:
        print(f"測試失敗：{exc}", file=sys.stderr)
        return 1
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
