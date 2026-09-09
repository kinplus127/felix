"""Interactive command adapter. Sends intents; does not talk to mpv or tidalapi."""

from __future__ import annotations

from felix.domain.events import (
    AlbumOpened,
    ArtistOpened,
    Ended,
    Event,
    CreditsReady,
    Failed,
    LyricsReady,
    Paused,
    Playing,
    PlaylistOpened,
    PlaylistsReady,
    Position,
    QueueUpdated,
    RepeatChanged,
    SearchReady,
    ShuffleChanged,
    SourceReady,
    Stopped,
    TrackResolved,
    VolumeChanged,
    OutputChanged,
    FormatReady,
)
from felix.domain.intents import (
    AdjustVolume,
    CycleRepeat,
    Enqueue,
    Intent,
    ListPlaylists,
    Next,
    OpenAlbum,
    OpenArtist,
    OpenPlaylist,
    Pause,
    PlayList,
    PlayPlaylist,
    PlayTrack,
    Prev,
    Resume,
    Search,
    Seek,
    SeekRelative,
    SetAudioOutput,
    ShowCredits,
    ShowLyrics,
    SetVolume,
    Stop,
    TogglePause,
    ToggleShuffle,
)
from felix.domain.models import Album, Artist, Playlist, Track
from felix.engine.alsa_devices import list_alsa_devices
from felix.runtime.app import App, RuntimeStatus
from felix.settings import SYSTEM_ALSA_WARNING

HELP = """
search <字>          搜尋 tracks / albums / artists
playlists            列出帳號 playlists（自己建立＋收藏）
play <n>             搜尋：只播一首；專輯／藝人／playlist：從該首播到列表結束
                     playlists 列表：整份入 queue 並播放
play id <track_id>   用 TIDAL id 播放
add <n>              將第 n 首加入 queue
album <n>            打開搜尋結果的專輯
artist <n>           打開搜尋結果的藝人
playlist <n>         打開帳號第 n 份 playlist
pause / resume       暫停／繼續
next / prev          下一首／上一首
seek <秒>            跳到絕對秒數
+5 / -5              相對 seek
stop                 停止
shuffle / repeat     切換隨機／重複
now                  現正播放
queue                佇列與 history
status               狀態、ao、最後錯誤、log 路徑
lyrics [n]           現正播放的歌詞；或列表第 n 首
credits [n]          現正播放的 credits；或列表第 n 首
vol [n]              音量；vol 50 或 vol +5 / vol -5
ao                   目前輸出（system / exclusive）
ao system            回到系統混音（PipeWire）
ao exclusive [n|hw]  exclusive；可選清單編號或 hw:CARD=…
ao devices           列出 ALSA hw 裝置
ao pipewire|alsa|…   system 的 ao 偏好（alsa 可能搶 DAC mixer）
ao device <id>       system 的 audio-device（重開引擎）
list                 再列出目前 tracks／albums／artists／playlists
help / quit
""".strip()


class CommandError(Exception):
    """User-facing command error."""


class Rostrum:
    def __init__(self, app: App) -> None:
        self.app = app
        self.tracks: tuple[Track, ...] = ()
        self.albums: tuple[Album, ...] = ()
        self.artists: tuple[Artist, ...] = ()
        self.playlists: tuple[Playlist, ...] = ()
        self.context = "search"
        app.subscribe(self.note)

    def note(self, event: Event) -> None:
        if isinstance(event, SearchReady):
            self.tracks = event.results.tracks
            self.albums = event.results.albums
            self.artists = event.results.artists
            self.playlists = ()
            self.context = "search"
        elif isinstance(event, AlbumOpened):
            self.tracks = event.tracks
            self.context = "album"
        elif isinstance(event, ArtistOpened):
            self.tracks = event.tracks
            self.albums = event.albums
            self.context = "artist"
        elif isinstance(event, PlaylistsReady):
            self.playlists = event.playlists
            self.tracks = ()
            self.albums = ()
            self.artists = ()
            self.context = "playlists"
        elif isinstance(event, PlaylistOpened):
            self.tracks = event.tracks
            self.context = "playlist"

    def dispatch(self, line: str) -> Intent | str:
        parts = line.strip().split()
        if not parts:
            raise CommandError("空白指令")
        cmd, *args = parts
        cmd = cmd.lower()

        if cmd in {"help", "h", "?"}:
            return "help"
        if cmd in {"quit", "exit", "q"}:
            return "quit"
        if cmd == "now":
            return "now"
        if cmd == "queue":
            return "queue"
        if cmd == "status":
            return "status"
        if cmd == "lyrics":
            return self._lyrics(args)
        if cmd == "credits":
            return self._credits(args)
        if cmd in {"vol", "volume"}:
            return self._volume(args)
        if cmd == "ao":
            return self._ao(args)
        if cmd == "list":
            return "list"
        if cmd == "search":
            query = " ".join(args).strip()
            if not query:
                raise CommandError("search 需要關鍵字")
            return Search(query)
        if cmd == "play":
            return self._play(args)
        if cmd in {"add", "enq", "enqueue"}:
            return Enqueue(self._track_at(_index(args)).id)
        if cmd == "album":
            return OpenAlbum(self._album_at(_index(args)).id)
        if cmd == "artist":
            return OpenArtist(self._artist_at(_index(args)).id)
        if cmd == "playlists":
            return ListPlaylists()
        if cmd == "playlist":
            return OpenPlaylist(self._playlist_at(_index(args)).id)
        if cmd == "pause":
            return Pause()
        if cmd == "resume":
            return Resume()
        if cmd in {"toggle", "p"}:
            return TogglePause()
        if cmd == "next":
            return Next()
        if cmd == "prev":
            return Prev()
        if cmd == "stop":
            return Stop()
        if cmd == "shuffle":
            return ToggleShuffle()
        if cmd == "repeat":
            return CycleRepeat()
        if cmd == "seek":
            if not args:
                raise CommandError("seek 需要秒數")
            return Seek(float(args[0]))
        if cmd == "+5":
            return SeekRelative(5)
        if cmd == "-5":
            return SeekRelative(-5)
        raise CommandError(f"未知指令：{cmd}")

    def _play(self, args: list[str]) -> PlayTrack | PlayList | PlayPlaylist:
        if args and args[0] == "id":
            if len(args) < 2:
                raise CommandError("play id 需要 track_id")
            return PlayTrack(args[1])
        index = _index(args)
        if self.context == "playlists":
            return PlayPlaylist(self._playlist_at(index).id)
        track = self._track_at(index)
        if self.context in {"album", "artist", "playlist"}:
            return PlayList(tuple(item.id for item in self.tracks), index)
        return PlayTrack(track.id)

    def _lyrics(self, args: list[str]) -> ShowLyrics:
        if args and args[0] == "id":
            if len(args) < 2:
                raise CommandError("lyrics id 需要 track_id")
            return ShowLyrics(args[1])
        if args:
            return ShowLyrics(self._track_at(_index(args)).id)
        track = self.app.now.track
        if track is None:
            raise CommandError("目前沒有播放中的曲目，請先 play 或 lyrics <n>")
        return ShowLyrics(track.id)

    def _credits(self, args: list[str]) -> ShowCredits:
        if args and args[0] == "id":
            if len(args) < 2:
                raise CommandError("credits id 需要 track_id")
            return ShowCredits(args[1])
        if args:
            return ShowCredits(self._track_at(_index(args)).id)
        track = self.app.now.track
        if track is None:
            raise CommandError("目前沒有播放中的曲目，請先 play 或 credits <n>")
        return ShowCredits(track.id)

    def _volume(self, args: list[str]) -> Intent | str:
        if not args:
            return "vol"
        raw = args[0]
        try:
            if raw[0] in {"+", "-"}:
                return AdjustVolume(float(raw))
            return SetVolume(float(raw))
        except ValueError as exc:
            raise CommandError(f"無效音量：{raw}") from exc

    def _ao(self, args: list[str]) -> Intent | str:
        if not args:
            return "ao"
        head = args[0].lower()
        if head == "devices":
            return "devices"
        if head == "device":
            if len(args) < 2:
                raise CommandError("ao device 需要裝置名稱或 auto")
            return SetAudioOutput(exclusive=False, audio_device=" ".join(args[1:]))
        if head == "system":
            if len(args) != 1:
                raise CommandError("ao system 不需要額外參數")
            return SetAudioOutput(exclusive=False)
        if head == "exclusive":
            if len(args) == 1:
                return SetAudioOutput(exclusive=True)
            token = " ".join(args[1:])
            if token.isdigit():
                devices = list_alsa_devices()
                if not devices:
                    raise CommandError("找不到 ALSA hw 裝置")
                index = int(token)
                if index < 0 or index >= len(devices):
                    raise CommandError(
                        f"裝置編號超出範圍 0–{len(devices) - 1}，請先 ao devices"
                    )
                return SetAudioOutput(
                    exclusive=True, exclusive_device=devices[index].hw_device
                )
            return SetAudioOutput(exclusive=True, exclusive_device=token)
        if len(args) != 1:
            raise CommandError(
                "ao 用法：ao / ao system / ao exclusive [n|hw:] / "
                "ao devices / ao pipewire|pulse|alsa|auto / ao device <id>"
            )
        return SetAudioOutput(exclusive=False, ao=args[0])

    def _track_at(self, index: int) -> Track:
        if not self.tracks:
            raise CommandError("目前沒有曲目列表，請先 search / album / artist")
        if index < 0 or index >= len(self.tracks):
            raise CommandError(f"曲目編號超出範圍 0–{len(self.tracks) - 1}")
        return self.tracks[index]

    def _album_at(self, index: int) -> Album:
        if not self.albums:
            raise CommandError("目前沒有專輯列表")
        if index < 0 or index >= len(self.albums):
            raise CommandError(f"專輯編號超出範圍 0–{len(self.albums) - 1}")
        return self.albums[index]

    def _artist_at(self, index: int) -> Artist:
        if not self.artists:
            raise CommandError("目前沒有藝人列表")
        if index < 0 or index >= len(self.artists):
            raise CommandError(f"藝人編號超出範圍 0–{len(self.artists) - 1}")
        return self.artists[index]

    def _playlist_at(self, index: int) -> Playlist:
        if not self.playlists:
            raise CommandError("目前沒有 playlist 列表，請先 playlists")
        if index < 0 or index >= len(self.playlists):
            raise CommandError(f"playlist 編號超出範圍 0–{len(self.playlists) - 1}")
        return self.playlists[index]


def _index(args: list[str]) -> int:
    if not args:
        raise CommandError("需要編號")
    raw = args[0]
    if raw[:1] in {"t", "T", "a", "A", "p", "P"} and raw[1:].isdigit():
        raw = raw[1:]
    try:
        return int(raw)
    except ValueError as exc:
        raise CommandError(f"無效編號：{args[0]}") from exc


def format_event(event: Event) -> str | None:
    if isinstance(event, Position):
        return None
    if isinstance(event, SearchReady):
        return _format_search(event)
    if isinstance(event, AlbumOpened):
        lines = [f"album  {event.album.title}  ({len(event.tracks)} tracks)"]
        lines.extend(_format_tracks(event.tracks))
        return "\n".join(lines)
    if isinstance(event, ArtistOpened):
        lines = [
            f"artist {event.artist.name}  "
            f"top={len(event.tracks)} albums={len(event.albums)}"
        ]
        lines.append("tracks")
        lines.extend(_format_tracks(event.tracks))
        if event.albums:
            lines.append("albums")
            lines.extend(_format_albums(event.albums))
        return "\n".join(lines)
    if isinstance(event, PlaylistsReady):
        lines = [f"playlists {len(event.playlists)}"]
        lines.extend(_format_playlists(event.playlists))
        return "\n".join(lines)
    if isinstance(event, PlaylistOpened):
        lines = [f"playlist {event.playlist.title}  ({len(event.tracks)} tracks)"]
        lines.extend(_format_tracks(event.tracks))
        return "\n".join(lines)
    if isinstance(event, TrackResolved):
        artists = ", ".join(event.track.artists)
        return f"resolved  {event.track.title} — {artists}"
    if isinstance(event, SourceReady):
        src = event.source
        return f"source    {src.quality} {src.bit_depth}/{src.sample_rate}"
    if isinstance(event, Playing):
        return "playing"
    if isinstance(event, Paused):
        return "paused"
    if isinstance(event, Ended):
        return "ended"
    if isinstance(event, Stopped):
        return "stopped"
    if isinstance(event, Failed):
        return f"failed    {event.message}"
    if isinstance(event, QueueUpdated):
        return f"queue     {len(event.track_ids)} items  index={event.index}"
    if isinstance(event, ShuffleChanged):
        return f"shuffle   {event.enabled}"
    if isinstance(event, RepeatChanged):
        return f"repeat    {event.mode}"
    if isinstance(event, LyricsReady):
        return _format_lyrics(event)
    if isinstance(event, CreditsReady):
        return _format_credits(event)
    if isinstance(event, VolumeChanged):
        return f"volume    {event.level:.0f}"
    if isinstance(event, OutputChanged):
        mode = "exclusive" if event.exclusive else "system"
        device = event.exclusive_device if event.exclusive else event.audio_device
        return (
            f"output    {mode}  ao={event.ao}  device={device or 'auto'}"
        )
    if isinstance(event, FormatReady):
        return _format_pcm(event)
    return type(event).__name__


def format_now(app: App) -> str:
    now = app.now
    if now.track is None:
        return f"now       {now.state}"
    artists = ", ".join(now.track.artists)
    duration = f"{now.duration:.0f}" if now.duration is not None else "?"
    quality = now.source.quality if now.source else "-"
    return (
        f"now       {now.state}  {now.position:.0f}/{duration}s  "
        f"{now.track.title} — {artists}  [{quality}]"
    )


def format_queue(app: App) -> str:
    ids, index, history = app.queue.snapshot()
    current = app.now.track
    lines = [
        f"queue     index={index}  shuffle={app.queue.shuffle}  "
        f"repeat={app.queue.repeat}  n={len(ids)}"
    ]
    if current is not None:
        lines.append(f"playing   {current.id}  {current.title}")
    if ids:
        lines.append("coming    " + " ".join(ids[(index or 0) + 1 :][:8] or ["-"]))
    if history:
        lines.append("history   " + " ".join(history[-8:]))
    return "\n".join(lines)


def format_status(app: App) -> str:
    snap = app.status()
    error = snap.last_error or "(none)"
    mode = "exclusive" if snap.exclusive else "system"
    volume = f"{snap.volume:.0f}"
    if snap.exclusive:
        volume = f"{snap.volume:.0f}（鎖 100）"
    lines = [
        f"log       {snap.log_path}",
        format_now(app),
        format_queue(app),
        f"output    {mode}",
        f"ao        {snap.ao}",
        f"ao-pref   {snap.ao_pref}  device={snap.audio_device}",
        f"exclusive {snap.exclusive_device or '(unset)'}",
        f"pcm       {_format_pcm_status(snap)}",
        f"volume    {volume}",
        f"error     {error}",
    ]
    if not snap.exclusive and snap.ao_pref == "alsa":
        lines.append(f"warning   {SYSTEM_ALSA_WARNING}")
    return "\n".join(lines)


def format_ao(app: App) -> str:
    snap = app.status()
    mode = "exclusive" if snap.exclusive else "system"
    lines = [
        f"output    {mode}",
        f"ao        {snap.ao}",
        f"ao-pref   {snap.ao_pref}  device={snap.audio_device}",
        f"exclusive {snap.exclusive_device or '(unset)'}",
    ]
    if not snap.exclusive and snap.ao_pref == "alsa":
        lines.append(f"warning   {SYSTEM_ALSA_WARNING}")
    return "\n".join(lines)


def format_devices() -> str:
    devices = list_alsa_devices()
    if not devices:
        return "devices   (none)"
    lines = ["devices"]
    for i, device in enumerate(devices):
        lines.append(f"  {i:<3} {device.hw_device}  {device.name}")
    return "\n".join(lines)


def format_lists(rostrum: Rostrum) -> str:
    lines = [f"context   {rostrum.context}"]
    if rostrum.tracks:
        lines.append("tracks")
        lines.extend(_format_tracks(rostrum.tracks))
    if rostrum.albums:
        lines.append("albums")
        lines.extend(_format_albums(rostrum.albums))
    if rostrum.artists:
        lines.append("artists")
        lines.extend(_format_artists(rostrum.artists))
    if rostrum.playlists:
        lines.append("playlists")
        lines.extend(_format_playlists(rostrum.playlists))
    if len(lines) == 1:
        return "目前沒有列表"
    return "\n".join(lines)


def _format_pcm(event: FormatReady) -> str:
    src = _hz_bits(event.source_bits, event.source_rate)
    decode = _hz_fmt(event.decode_format, event.decode_rate)
    out = _hz_fmt(event.output_format, event.output_rate)
    flag = _pcm_flag(event.exclusive, event.matched, event.output_rate)
    return f"pcm       src {src}  decode {decode}  out {out}  {flag}"


def _format_pcm_status(snap: RuntimeStatus) -> str:
    if snap.output_rate is None and snap.decode_rate is None:
        return "(pending)"
    src = _hz_bits(snap.source_bits, snap.source_rate)
    decode = _hz_fmt(snap.decode_format, snap.decode_rate)
    out = _hz_fmt(snap.output_format, snap.output_rate)
    flag = _pcm_flag(snap.exclusive, snap.pcm_matched, snap.output_rate)
    return f"src {src}  decode {decode}  out {out}  {flag}"


def _pcm_flag(exclusive: bool, matched: bool | None, output_rate: int | None) -> str:
    if not exclusive:
        return "pipewire"
    if output_rate is None:
        return "pending"
    if matched is True:
        return "match"
    if matched is False:
        return "RESAMPLE"
    return "pending"


def _hz_bits(bits: int | None, rate: int | None) -> str:
    bit_s = "-" if bits is None else str(bits)
    rate_s = "-" if rate is None else str(rate)
    return f"{bit_s}/{rate_s}"


def _hz_fmt(fmt: str, rate: int | None) -> str:
    name = fmt or "-"
    rate_s = "-" if rate is None else str(rate)
    return f"{name}/{rate_s}"


def _format_lyrics(event: LyricsReady) -> str:
    lyrics = event.lyrics
    kind = "timed" if lyrics.timed else "text"
    if not lyrics.text:
        return f"lyrics    {lyrics.track_id}  (none)"
    return f"lyrics    {lyrics.track_id}  {kind}\n{lyrics.text}"


def _format_credits(event: CreditsReady) -> str:
    credits = event.credits
    lines = [f"{group.role}: {', '.join(group.names)}" for group in credits.groups]
    if credits.year is not None and credits.year > 0:
        lines.append(f"Released: {credits.year}")
    if credits.copyright:
        lines.append(f"Label: {credits.copyright}")
    if not lines:
        return f"credits   {credits.track_id}  (none)"
    return f"credits   {credits.track_id}\n" + "\n".join(lines)


def _format_search(event: SearchReady) -> str:
    results = event.results
    lines = [f"search    {results.query}"]
    lines.append("tracks")
    lines.extend(_format_tracks(results.tracks))
    lines.append("albums")
    lines.extend(_format_albums(results.albums))
    lines.append("artists")
    lines.extend(_format_artists(results.artists))
    return "\n".join(lines)


def _format_tracks(tracks: tuple[Track, ...]) -> list[str]:
    lines = []
    for i, track in enumerate(tracks):
        artists = ", ".join(track.artists)
        lines.append(f"  t{i:<3} {track.title} — {artists}")
    return lines or ["  (none)"]


def _format_albums(albums: tuple[Album, ...]) -> list[str]:
    lines = []
    for i, album in enumerate(albums):
        artists = ", ".join(album.artists)
        year = album.year or "-"
        lines.append(f"  a{i:<3} {album.title} ({year}) — {artists}")
    return lines or ["  (none)"]


def _format_artists(artists: tuple[Artist, ...]) -> list[str]:
    lines = []
    for i, artist in enumerate(artists):
        lines.append(f"  A{i:<3} {artist.name}")
    return lines or ["  (none)"]


def _format_playlists(playlists: tuple[Playlist, ...]) -> list[str]:
    lines = []
    for i, playlist in enumerate(playlists):
        count = playlist.track_count
        suffix = f"  ({count})" if count is not None else ""
        lines.append(f"  p{i:<3} {playlist.title}{suffix}")
    return lines or ["  (none)"]
