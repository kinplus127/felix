"""The only module allowed to call both tidal and engine."""

from __future__ import annotations

import queue as stdqueue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import tidalapi

from felix.config import (
    DEFAULT_QUALITY,
    LOG_PATH,
    PREFETCH_LEAD_SECS,
    PREFETCH_TTL_SECS,
    PREFETCH_WAIT_SECS,
)
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
from felix.domain.models import PlaybackSource, Quality, RepeatMode, SourceKind
from felix.engine.controller import Controller, EngineEvent
from felix.engine.ipc import IpcError
from felix.engine.output import OutputSpec
from felix.engine.pcm import PcmReading, pcm_mismatch
from felix.engine.process import ProcessError
from felix.logs import get_logger, setup_logging
from felix.runtime.bus import EventBus, Listener
from felix.runtime.now_playing import NowPlaying
from felix.runtime.queue import PlayQueue
from felix.settings import (
    SYSTEM_ALSA_WARNING,
    Settings,
    SettingsError,
    clamp_volume,
    load_settings,
    normalize_ao,
    normalize_device,
    normalize_hw_device,
    save_settings,
)
from felix.tidal.auth import AuthError, load
from felix.tidal.client import CatalogError, Client
from felix.tidal.gate import gate_for
from felix.tidal.streams import StreamError, resolve

_PREV_RESTART_AFTER = 3.0
_SEEK_RETRY_DELAY = 0.35

# Catalog lookups hit the network. They get their own worker so a slow
# search can never delay pause / next / volume.
_CATALOG_INTENTS = (
    Search,
    OpenAlbum,
    OpenArtist,
    ListPlaylists,
    OpenPlaylist,
    PlayPlaylist,
    ShowLyrics,
    ShowCredits,
)

log = get_logger("app")


class IntentMailbox:
    """One worker, FIFO. Callers enqueue and return immediately."""

    def __init__(
        self, apply: Callable[[Intent], None], name: str = "felix-intents"
    ) -> None:
        self._apply = apply
        self._name = name
        self._queue: stdqueue.Queue[Intent | None] = stdqueue.Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._thread = threading.Thread(target=self._run, daemon=True, name=name)
        self._thread.start()

    def submit(self, intent: Intent) -> bool:
        with self._lock:
            if self._closed:
                return False
            self._queue.put(intent)
            return True

    def close(self, timeout: float = 15.0) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._queue.put(None)
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            log.warning("%s still running after close", self._name)

    def _run(self) -> None:
        while True:
            intent = self._queue.get()
            if intent is None:
                return
            try:
                self._apply(intent)
            except Exception:
                log.exception("intent worker crashed on %s", type(intent).__name__)


@dataclass(frozen=True)
class RuntimeStatus:
    log_path: str
    exclusive: bool
    ao: str
    ao_pref: str
    audio_device: str
    exclusive_device: str
    volume: float
    last_error: str
    source_rate: int | None
    source_bits: int | None
    decode_rate: int | None
    decode_format: str
    output_rate: int | None
    output_format: str
    pcm_matched: bool | None


class App:
    def __init__(
        self,
        session: tidalapi.Session | None = None,
        controller: Controller | None = None,
        quality: Quality | None = None,
    ) -> None:
        setup_logging()
        raw_session = session if session is not None else load()
        self._gate = gate_for(raw_session)
        self._session = self._gate.session
        self._client = Client(self._gate)
        self._engine = controller if controller is not None else Controller()
        self._quality = quality if quality is not None else Quality(DEFAULT_QUALITY)
        self.now = NowPlaying()
        self.queue = PlayQueue()
        self.last_error = ""
        self._settings = load_settings()
        self._bus = EventBus()
        self._lock = threading.Lock()
        self._play_lock = threading.Lock()
        self._rehydrating = False
        self._hydrate_attempts = 0
        self._pending_seek: float | None = None
        self._prefetch_id: str | None = None
        self._prefetch_source: PlaybackSource | None = None
        self._prefetch_at: float | None = None
        self._prefetch_inflight: str | None = None
        self._pending_pause = False
        self._switching = False
        self._format: FormatReady | None = None
        self._latest_search: Search | None = None
        self._ao_cache: str | None = None
        self._running = True
        self._start_engine()
        self._pump = threading.Thread(target=self._pump_engine, daemon=True)
        self._pump.start()
        self._transport = IntentMailbox(self._apply_intent, name="felix-transport")
        self._catalog = IntentMailbox(self._apply_intent, name="felix-catalog")
        log.info(
            "app started quality=%s volume=%s output=%s ao=%s device=%s exclusive=%s",
            self._quality,
            self._settings.volume,
            self._settings.output,
            self._settings.ao or "auto",
            self._settings.audio_device or "auto",
            self._settings.exclusive_device or "-",
        )

    def subscribe(self, listener: Listener) -> int:
        """Listen for events. Keep the token; a UI must unsubscribe on close."""
        return self._bus.subscribe(listener)

    def unsubscribe(self, token: int) -> bool:
        return self._bus.unsubscribe(token)

    def status(self) -> RuntimeStatus:
        ao = self._audio_output()
        with self._lock:
            last_error = self.last_error
            volume = self._settings.volume
            exclusive = self._settings.output == "exclusive"
            ao_pref = self._settings.ao or "auto"
            audio_device = self._settings.audio_device or "auto"
            exclusive_device = self._settings.exclusive_device or ""
            fmt = self._format
        return RuntimeStatus(
            log_path=str(LOG_PATH),
            exclusive=exclusive,
            ao=ao,
            ao_pref=ao_pref,
            audio_device=audio_device,
            exclusive_device=exclusive_device,
            volume=volume,
            last_error=last_error,
            source_rate=fmt.source_rate if fmt else None,
            source_bits=fmt.source_bits if fmt else None,
            decode_rate=fmt.decode_rate if fmt else None,
            decode_format=fmt.decode_format if fmt else "",
            output_rate=fmt.output_rate if fmt else None,
            output_format=fmt.output_format if fmt else "",
            pcm_matched=fmt.matched if fmt else None,
        )

    def _audio_output(self) -> str:
        """Cached: a UI polls status() often and this costs mpv IPC round trips.
        Only the engine restarting can change it, so that is when we drop it."""
        with self._lock:
            cached = self._ao_cache
        if cached is not None:
            return cached
        try:
            ao = self._engine.audio_output()
        except (IpcError, ProcessError) as exc:
            return f"unavailable ({exc})"
        with self._lock:
            self._ao_cache = ao
        return ao

    def _invalidate_audio_output(self) -> None:
        with self._lock:
            self._ao_cache = None

    def handle(self, intent: Intent) -> None:
        """Route the intent to the transport or the catalog worker."""
        if isinstance(intent, Search):
            with self._lock:
                self._latest_search = intent
        catalog = isinstance(intent, _CATALOG_INTENTS)
        mailbox = self._catalog if catalog else self._transport
        if not mailbox.submit(intent):
            log.warning("intent ignored after close: %s", type(intent).__name__)

    def _apply_intent(self, intent: Intent) -> None:
        try:
            if isinstance(intent, PlayTrack):
                self._on_play_track(intent.track_id)
            elif isinstance(intent, PlayList):
                self._on_play_list(intent.track_ids, intent.start_index)
            elif isinstance(intent, Enqueue):
                self._on_enqueue(intent.track_id)
            elif isinstance(intent, Next):
                self._on_next()
            elif isinstance(intent, Prev):
                self._on_prev()
            elif isinstance(intent, ToggleShuffle):
                self._on_toggle_shuffle()
            elif isinstance(intent, CycleRepeat):
                self._on_cycle_repeat()
            elif isinstance(intent, TogglePause):
                self._toggle_pause()
            elif isinstance(intent, Pause):
                self._pause()
            elif isinstance(intent, Resume):
                self._resume()
            elif isinstance(intent, Seek):
                self._seek(intent.seconds)
            elif isinstance(intent, SeekRelative):
                with self._lock:
                    target = max(0.0, self.now.position + intent.delta)
                self._seek(target)
            elif isinstance(intent, Stop):
                self._stop()
            elif isinstance(intent, Search):
                self._on_search(intent)
            elif isinstance(intent, OpenAlbum):
                self._on_open_album(intent.album_id)
            elif isinstance(intent, OpenArtist):
                self._on_open_artist(intent.artist_id)
            elif isinstance(intent, ListPlaylists):
                self._on_list_playlists()
            elif isinstance(intent, OpenPlaylist):
                self._on_open_playlist(intent.playlist_id)
            elif isinstance(intent, PlayPlaylist):
                self._on_play_playlist(intent.playlist_id, intent.start_index)
            elif isinstance(intent, ShowLyrics):
                self._on_show_lyrics(intent.track_id)
            elif isinstance(intent, ShowCredits):
                self._on_show_credits(intent.track_id)
            elif isinstance(intent, SetVolume):
                self._apply_volume(intent.level)
            elif isinstance(intent, AdjustVolume):
                with self._lock:
                    current = self._settings.volume
                self._apply_volume(current + intent.delta)
            elif isinstance(intent, SetAudioOutput):
                self._apply_output(intent)
        except SettingsError as exc:
            self._soft_fail(str(exc))
        except AuthError as exc:
            self._fail(str(exc))
        except (CatalogError, StreamError, IpcError, ProcessError) as exc:
            self._fail(str(exc))
        except Exception as exc:
            log.exception("intent failed %s", type(intent).__name__)
            self._soft_fail(f"指令失敗：{exc}")

    def _output_spec(self, settings: Settings | None = None) -> OutputSpec:
        current = settings if settings is not None else self._settings
        return OutputSpec(
            exclusive=current.output == "exclusive",
            ao=current.ao,
            audio_device=current.audio_device,
            exclusive_device=current.exclusive_device,
        )

    def _start_engine(self) -> None:
        self._invalidate_audio_output()
        settings = self._settings
        if settings.output == "exclusive" and not settings.exclusive_device:
            log.warning("exclusive requested without device; starting system")
            settings = replace(settings, output="system")
            self._settings = settings
            self.last_error = "exclusive 未設定裝置，已以 system 啟動"
        spec = self._output_spec(settings)
        try:
            self._engine.start(spec)
        except ProcessError:
            if not spec.exclusive:
                raise
            log.warning("exclusive start failed; falling back to system")
            settings = replace(self._settings, output="system")
            self._settings = settings
            self._engine.start(self._output_spec(settings))
            self.last_error = "exclusive 啟動失敗，已改為 system"
        if spec.exclusive and self._settings.output == "exclusive":
            self._engine.set_volume(100)
        else:
            self._apply_volume(self._settings.volume, persist=False)

    def _apply_volume(self, level: float, persist: bool = True) -> None:
        with self._lock:
            exclusive = self._settings.output == "exclusive"
        if exclusive and persist:
            self._soft_fail("exclusive 模式請用 DAC 旋鈕；軟體音量已鎖 100")
            return
        volume = clamp_volume(level)
        if exclusive:
            self._engine.set_volume(100)
            return
        self._engine.set_volume(volume)
        with self._lock:
            self._settings.volume = volume
        log.info("volume %s", volume)
        if persist:
            save_settings(self._settings)
            self._emit(VolumeChanged(volume))

    def _apply_output(self, intent: SetAudioOutput) -> None:
        with self._lock:
            previous = replace(self._settings)
            next_settings = self._next_output_settings(intent)
        if next_settings == previous:
            self._emit(self._output_changed(previous))
            return
        if next_settings.output == "exclusive" and not next_settings.exclusive_device:
            raise SettingsError("尚未設定 exclusive 裝置，請先 ao devices 再 ao exclusive <n>")
        with self._lock:
            track_id = self.now.track.id if self.now.track else None
            position = self.now.position
            was_playing = self.now.state in {"playing", "paused"}
            was_paused = self.now.state == "paused"
        self._clear_prefetch()
        failed: ProcessError | None = None
        self._switching = True
        try:
            try:
                self._engine.restart(self._output_spec(next_settings))
            except ProcessError as exc:
                log.warning("output switch failed; restoring %s", previous.output)
                self._engine.restart(self._output_spec(previous))
                with self._lock:
                    self._settings = previous
                applied = previous
                failed = exc
            else:
                with self._lock:
                    self._settings = next_settings
                save_settings(next_settings)
                applied = next_settings
                log.info(
                    "output %s ao=%s device=%s exclusive=%s",
                    next_settings.output,
                    next_settings.ao or "auto",
                    next_settings.audio_device or "auto",
                    next_settings.exclusive_device or "-",
                )
                self._emit(self._output_changed(next_settings))
            if applied.output == "exclusive":
                self._engine.set_volume(100)
            else:
                self._apply_volume(applied.volume, persist=False)
        finally:
            self._switching = False
            self._invalidate_audio_output()
        if was_playing and track_id:
            self._pending_pause = was_paused
            if position > 1:
                self._pending_seek = position
            self._start_track(track_id)
        if failed is not None:
            raise SettingsError(f"無法切換輸出：{failed}") from failed
        self._warn_system_alsa(applied)

    def _warn_system_alsa(self, settings: Settings) -> None:
        if settings.output == "system" and settings.ao == "alsa":
            self._soft_fail(SYSTEM_ALSA_WARNING)
            return
        with self._lock:
            if self.last_error == SYSTEM_ALSA_WARNING:
                self.last_error = ""

    def _next_output_settings(self, intent: SetAudioOutput) -> Settings:
        current = self._settings
        next_ao = current.ao if intent.ao is None else normalize_ao(intent.ao)
        next_dev = (
            current.audio_device
            if intent.audio_device is None
            else normalize_device(intent.audio_device)
        )
        next_hw = (
            current.exclusive_device
            if intent.exclusive_device is None
            else normalize_hw_device(intent.exclusive_device)
        )
        if intent.exclusive is True:
            output = "exclusive"
        elif intent.exclusive is False:
            output = "system"
        elif intent.ao is not None or intent.audio_device is not None:
            output = "system"
        else:
            output = current.output
        return replace(
            current,
            output=output,
            ao=next_ao,
            audio_device=next_dev,
            exclusive_device=next_hw,
        )

    def _output_changed(self, settings: Settings) -> OutputChanged:
        return OutputChanged(
            exclusive=settings.output == "exclusive",
            ao=settings.ao or "auto",
            audio_device=settings.audio_device or "auto",
            exclusive_device=settings.exclusive_device,
        )

    def close(self) -> None:
        # Catalog first: a fetch in flight may still hand playback to transport.
        self._catalog.close()
        self._transport.close()
        self._running = False
        self._engine.close()
        self._pump.join(timeout=1)

    def _on_play_track(self, track_id: str) -> None:
        self._clear_prefetch()
        with self._lock:
            self.queue.play_now(track_id)
        self._emit_queue()
        self._start_track(track_id)

    def _on_play_list(self, track_ids: tuple[str, ...], start_index: int) -> None:
        self._clear_prefetch()
        with self._lock:
            current = self.queue.replace_with(track_ids, start_index)
        self._emit_queue()
        if current is None:
            self._soft_fail("播放列表是空的")
            return
        self._start_track(current)

    def _on_enqueue(self, track_id: str) -> None:
        with self._lock:
            self.queue.enqueue(track_id)
        self._emit_queue()

    def _on_next(self) -> None:
        if self._is_loading():
            return
        with self._lock:
            nxt = self.queue.go_next()
        self._emit_queue()
        if nxt is None:
            self._stop()
            return
        self._start_track(nxt)

    def _on_prev(self) -> None:
        if self._is_loading():
            return
        with self._lock:
            position = self.now.position
            before = self.queue.cursor()
        if position > _PREV_RESTART_AFTER:
            self._seek(0.0)
            return
        with self._lock:
            prev = self.queue.go_prev()
            after = self.queue.cursor()
        self._emit_queue()
        if prev is None or after == before:
            self._seek(0.0)
            return
        self._start_track(prev)

    def _on_toggle_shuffle(self) -> None:
        self._clear_prefetch()
        with self._lock:
            enabled = self.queue.toggle_shuffle()
        self._emit(ShuffleChanged(enabled))
        self._emit_queue()

    def _on_cycle_repeat(self) -> None:
        self._clear_prefetch()
        with self._lock:
            mode = self.queue.cycle_repeat()
        self._emit(RepeatChanged(mode))

    def _is_loading(self) -> bool:
        with self._lock:
            return self.now.state == "loading"

    def _on_search(self, intent: Search) -> None:
        cleaned = intent.query.strip()
        if not cleaned:
            self._soft_fail("搜尋字串是空的")
            return
        if self._search_superseded(intent):
            log.info("search skipped, newer one queued: %s", cleaned)
            return
        results = self._client.search(cleaned, limit=intent.limit)
        if self._search_superseded(intent):
            log.info("search discarded, newer one queued: %s", cleaned)
            return
        self._emit(SearchReady(results))

    def _search_superseded(self, intent: Search) -> bool:
        """True once a newer Search was submitted, so stale results never
        overwrite fresher ones in a type-ahead UI."""
        with self._lock:
            return self._latest_search is not intent

    def _on_open_album(self, album_id: str) -> None:
        album, tracks = self._client.album_tracks(album_id)
        self._emit(AlbumOpened(album, tracks))

    def _on_open_artist(self, artist_id: str) -> None:
        artist, tracks, albums = self._client.artist_catalog(artist_id)
        self._emit(ArtistOpened(artist, tracks, albums))

    def _on_list_playlists(self) -> None:
        self._emit(PlaylistsReady(self._client.user_playlists()))

    def _on_open_playlist(self, playlist_id: str) -> None:
        playlist, tracks = self._client.playlist_tracks(playlist_id)
        self._emit(PlaylistOpened(playlist, tracks))

    def _on_play_playlist(self, playlist_id: str, start_index: int) -> None:
        playlist, tracks = self._client.playlist_tracks(playlist_id)
        self._emit(PlaylistOpened(playlist, tracks))
        # Hand playback back to transport: the catalog worker must not own it.
        self.handle(PlayList(tuple(item.id for item in tracks), start_index))

    def _on_show_lyrics(self, track_id: str) -> None:
        lyrics = self._client.get_lyrics(track_id)
        if lyrics.text:
            log.info("lyrics track=%s timed=%s chars=%s", track_id, lyrics.timed, len(lyrics.text))
        else:
            log.info("lyrics missing track=%s", track_id)
        self._emit(LyricsReady(lyrics))

    def _on_show_credits(self, track_id: str) -> None:
        credits = self._client.get_credits(track_id)
        log.info(
            "credits track=%s groups=%s year=%s",
            track_id,
            len(credits.groups),
            credits.year,
        )
        self._emit(CreditsReady(credits))

    def _start_track(self, track_id: str) -> None:
        with self._play_lock:
            source = self._take_prefetch(track_id)
            if source is None:
                self._clear_prefetch()
            with self._lock:
                self.now.state = "loading"
                self.now.position = 0.0
                self.now.duration = None
                self._format = None
                if not self._rehydrating:
                    self._pending_seek = None
            track = self._client.get_track(track_id)
            with self._lock:
                self.now.track = track
            self._emit(TrackResolved(track))
            log.info("play track=%s title=%s prefetched=%s", track.id, track.title, source is not None)
            if source is None:
                source = resolve(self._gate, track_id, self._quality)
            with self._lock:
                self.now.source = source
            self._emit(SourceReady(source))
            self._engine.play(source)

    def _toggle_pause(self) -> None:
        with self._lock:
            state = self.now.state
        if state == "playing":
            self._pause()
        elif state == "paused":
            self._resume()

    def _pause(self) -> None:
        with self._lock:
            if self.now.state != "playing":
                return
        self._engine.pause()

    def _resume(self) -> None:
        with self._lock:
            if self.now.state != "paused":
                return
            track_id = self.now.track.id if self.now.track else None
            position = self.now.position
        try:
            self._engine.resume()
        except IpcError:
            if track_id is None:
                raise
            self._rehydrate(track_id, position)

    def _seek(self, seconds: float) -> None:
        target = max(0.0, seconds)
        with self._lock:
            if self.now.state not in {"playing", "paused"}:
                return
        last_error: IpcError | None = None
        for attempt in range(2):
            try:
                self._engine.seek(target)
                return
            except IpcError as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(_SEEK_RETRY_DELAY)
        self._soft_fail(str(last_error) if last_error else "seek 失敗")

    def _rehydrate(self, track_id: str, position: float) -> None:
        if self._rehydrating:
            return
        self._rehydrating = True
        try:
            if position > 1.0:
                self._pending_seek = position
            self._start_track(track_id)
        finally:
            self._rehydrating = False

    def _on_engine_error(self, message: str) -> None:
        with self._lock:
            track_id = self.now.track.id if self.now.track else None
            position = self.now.position
            busy = self._rehydrating
            attempts = self._hydrate_attempts
        if busy or track_id is None or attempts >= 1:
            self._fail(message)
            return
        with self._lock:
            self._hydrate_attempts = attempts + 1
        try:
            self._rehydrate(track_id, position)
        except AuthError as exc:
            self._fail(str(exc))
        except (CatalogError, StreamError, IpcError, ProcessError) as exc:
            self._fail(str(exc))

    def _on_engine_died(self, message: str) -> None:
        self._clear_prefetch()
        self._invalidate_audio_output()
        with self._lock:
            self.now.state = "stopped"
            self._format = None
        self._remember_error(message)
        self._emit(Failed(message))
        self._emit(Stopped())
        try:
            self._start_engine()
            log.info("engine restarted after mpv death")
        except ProcessError as exc:
            detail = f"{message}；無法重開引擎：{exc}"
            self._remember_error(detail)
            self._emit(Failed(detail))

    def _soft_fail(self, message: str) -> None:
        self._remember_error(message)
        self._emit(Failed(message))

    def _stop(self) -> None:
        self._clear_prefetch()
        self._engine.stop()
        with self._lock:
            self.now.state = "stopped"
            self.now.position = 0.0
        self._emit(Stopped())

    def _fail(self, message: str) -> None:
        self._clear_prefetch()
        with self._lock:
            self.now.state = "stopped"
        self._remember_error(message)
        self._emit(Failed(message))

    def _remember_error(self, message: str) -> None:
        with self._lock:
            self.last_error = message
        log.error("%s", message)

    def _emit_queue(self) -> None:
        with self._lock:
            track_ids, index, history = self.queue.snapshot()
        self._emit(QueueUpdated(track_ids, index, history))

    def _emit(self, event: Event) -> None:
        self._bus.publish(event)

    def _pump_engine(self) -> None:
        while self._running:
            try:
                event = self._engine.events.get(timeout=0.2)
            except stdqueue.Empty:
                continue
            try:
                self._on_engine(event)
            except Exception:
                log.exception("engine pump failed on %s", event.name)

    def _on_engine(self, event: EngineEvent) -> None:
        if self._switching and event.name in {"error", "eof", "playing", "paused", "pcm"}:
            return
        if event.name == "playing":
            with self._lock:
                self.now.state = "playing"
                self._hydrate_attempts = 0
            self._emit(Playing())
            self._apply_pending_seek()
            if self._pending_pause:
                self._pending_pause = False
                self._engine.pause()
        elif event.name == "paused":
            with self._lock:
                self.now.state = "paused"
            self._emit(Paused())
        elif event.name == "resumed":
            with self._lock:
                if self.now.state == "stopped":
                    return
                self.now.state = "playing"
            self._emit(Playing())
        elif event.name == "duration":
            with self._lock:
                self.now.duration = float(event.payload)
            self._apply_pending_seek()
        elif event.name == "time":
            seconds = float(event.payload)
            with self._lock:
                self.now.position = seconds
                duration = self.now.duration
            self._emit(Position(seconds, duration))
            self._maybe_prefetch(seconds, duration)
        elif event.name == "eof":
            self._on_ended()
        elif event.name == "pcm":
            self._on_pcm(event.payload)
        elif event.name == "error":
            log.warning("engine error: %s", event.payload)
            self._on_engine_error(str(event.payload))
        elif event.name == "died":
            self._on_engine_died(str(event.payload))

    def _on_pcm(self, payload: object) -> None:
        if not isinstance(payload, PcmReading):
            return
        if payload.output_rate is None and payload.decode_rate is None:
            return
        with self._lock:
            source = self.now.source
            exclusive = self._settings.output == "exclusive"
            state = self.now.state
            previous = self._format
        if source is None or state not in {"playing", "paused"}:
            return
        if exclusive and payload.output_rate is None:
            return
        reason = pcm_mismatch(source.sample_rate, source.bit_depth, payload)
        matched: bool | None
        if exclusive:
            matched = not reason
        else:
            matched = None
        event = FormatReady(
            source_rate=source.sample_rate,
            source_bits=source.bit_depth,
            decode_rate=payload.decode_rate,
            decode_format=payload.decode_format,
            output_rate=payload.output_rate,
            output_format=payload.output_format,
            matched=matched,
            exclusive=exclusive,
        )
        with self._lock:
            self._format = event
        same = (
            previous is not None
            and previous.matched == event.matched
            and previous.output_rate == event.output_rate
            and previous.decode_rate == event.decode_rate
            and previous.output_format == event.output_format
        )
        if same:
            return
        log.info(
            "pcm src=%s/%s decode=%s/%s out=%s/%s matched=%s exclusive=%s",
            source.bit_depth,
            source.sample_rate,
            payload.decode_format or "-",
            payload.decode_rate,
            payload.output_format or "-",
            payload.output_rate,
            matched,
            exclusive,
        )
        self._emit(event)
        if exclusive and not matched:
            self._soft_fail(f"exclusive {reason}")
        elif exclusive and matched:
            with self._lock:
                if self.last_error.startswith("exclusive "):
                    self.last_error = ""

    def _apply_pending_seek(self) -> None:
        with self._lock:
            target = self._pending_seek
            if target is None:
                return
            self._pending_seek = None
            state = self.now.state
        if state in {"playing", "paused"}:
            self._seek(target)

    def _clear_prefetch(self) -> None:
        with self._lock:
            self._prefetch_id = None
            self._prefetch_source = None
            self._prefetch_at = None

    def _take_prefetch(self, track_id: str) -> PlaybackSource | None:
        deadline = time.monotonic() + PREFETCH_WAIT_SECS
        while True:
            with self._lock:
                if self._prefetch_id == track_id and self._prefetch_source is not None:
                    source = self._prefetch_source
                    age = time.monotonic() - (self._prefetch_at or 0.0)
                    self._prefetch_id = None
                    self._prefetch_source = None
                    self._prefetch_at = None
                    if age > PREFETCH_TTL_SECS:
                        log.info("prefetch expired track=%s age=%.1fs", track_id, age)
                        return None
                    return source
                waiting = self._prefetch_inflight == track_id
            if not waiting or time.monotonic() >= deadline:
                return None
            time.sleep(0.05)

    def _prefetch_is_fresh(self, track_id: str) -> bool:
        if self._prefetch_id != track_id or self._prefetch_source is None:
            return False
        age = time.monotonic() - (self._prefetch_at or 0.0)
        return age <= PREFETCH_TTL_SECS

    def _maybe_prefetch(self, position: float, duration: float | None) -> None:
        if duration is None or duration <= 0:
            return
        remaining = duration - position
        if remaining > PREFETCH_LEAD_SECS or remaining < 0.5:
            return
        with self._lock:
            if self.now.state not in {"playing", "paused"}:
                return
            nxt = self.queue.peek_next()
            if nxt is None or self.queue.peek_is_replay():
                return
            if self._prefetch_is_fresh(nxt) or self._prefetch_inflight is not None:
                return
            self._prefetch_id = None
            self._prefetch_source = None
            self._prefetch_at = None
            self._prefetch_inflight = nxt
            current_source = self.now.source
        thread = threading.Thread(
            target=self._prefetch_track,
            args=(nxt, current_source),
            daemon=True,
            name="felix-prefetch",
        )
        thread.start()

    def _prefetch_track(
        self, track_id: str, current_source: PlaybackSource | None
    ) -> None:
        protect: Path | None = None
        if current_source is not None and current_source.kind is SourceKind.MPD_FILE:
            protect = Path(current_source.location)
        try:
            source = resolve(
                self._gate, track_id, self._quality, protect=protect
            )
            with self._lock:
                if self.queue.peek_next() != track_id:
                    log.info("prefetch discarded track=%s", track_id)
                    return
                self._prefetch_id = track_id
                self._prefetch_source = source
                self._prefetch_at = time.monotonic()
            log.info("prefetched track=%s kind=%s", track_id, source.kind)
        except AuthError as exc:
            log.warning("prefetch auth failed track=%s", track_id)
            self._soft_fail(str(exc))
        except Exception as exc:
            log.warning("prefetch failed track=%s: %s", track_id, exc)
        finally:
            with self._lock:
                if self._prefetch_inflight == track_id:
                    self._prefetch_inflight = None

    def _on_ended(self) -> None:
        with self._lock:
            self.now.state = "stopped"
        self._emit(Ended())
        try:
            with self._lock:
                nxt = self.queue.on_ended()
            self._emit_queue()
            if nxt is None:
                return
            self._start_track(nxt)
        except AuthError as exc:
            self._fail(str(exc))
        except (CatalogError, StreamError, IpcError, ProcessError) as exc:
            self._fail(str(exc))
