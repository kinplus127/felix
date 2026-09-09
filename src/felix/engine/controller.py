"""play / pause / seek / volume. Accepts PlaybackSource only."""

from __future__ import annotations

import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from felix.config import MPV_SOCKET_PATH
from felix.domain.models import PlaybackSource
from felix.engine.ipc import IpcError, MpvIpc
from felix.engine.output import OutputSpec
from felix.engine.pcm import PcmReading, parse_params
from felix.engine.pipewire import (
    CardRelease,
    install_exit_hooks,
    release_card_for_exclusive,
    restore_any_pending,
    restore_card,
    set_exit_cleanup,
)
from felix.engine.process import ProcessError, start_mpv, stop_mpv
from felix.logs import get_logger

log = get_logger("engine")


def _enabled_ao_names(value: Any) -> list[str]:
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, dict):
                if item.get("enabled") is False:
                    continue
                name = str(item.get("name") or "")
                if name:
                    names.append(name)
            elif item:
                names.append(str(item))
        return names
    if isinstance(value, str) and value:
        return [value]
    return []


@dataclass(frozen=True)
class EngineEvent:
    name: str
    payload: Any = None


class Controller:
    def __init__(self, socket_path: Path | None = None) -> None:
        self._socket_path = socket_path if socket_path is not None else MPV_SOCKET_PATH
        self._proc: subprocess.Popen[bytes] | None = None
        self._ipc: MpvIpc | None = None
        self._dispatch: threading.Thread | None = None
        self._running = False
        self._spec = OutputSpec()
        self._pw_release: CardRelease | None = None
        self._pcm = PcmReading()
        self._stopping = False
        self.events: queue.Queue[EngineEvent] = queue.Queue()
        install_exit_hooks()
        set_exit_cleanup(self.close)

    def start(
        self,
        spec: OutputSpec | None = None,
        ao: str = "",
        audio_device: str = "",
    ) -> None:
        if self._ipc is not None:
            return
        if spec is None:
            spec = OutputSpec(ao=ao, audio_device=audio_device)
        self._spec = spec
        self._stopping = False
        restore_any_pending()
        try:
            if spec.exclusive:
                self._start_exclusive(spec)
            else:
                self._proc = start_mpv(
                    self._socket_path,
                    ao=spec.mpv_ao(),
                    audio_device=spec.mpv_audio_device(),
                )
                self._bind_ipc()
                self._assert_system_output(spec)
        except Exception:
            self._teardown_mpv()
            raise

    def restart(self, spec: OutputSpec) -> None:
        self.close()
        self._drain_events()
        time.sleep(0.3)
        self.start(spec)

    def play(self, source: PlaybackSource) -> None:
        ipc = self._require_ipc()
        log.info("loadfile %s %s", source.kind, source.location)
        ipc.command("loadfile", source.location, "replace")
        ipc.command("set_property", "pause", False)
        self._pcm = PcmReading()

    def audio_output(self) -> str:
        ipc = self._require_ipc()
        ao = None
        device = None
        try:
            ao = ipc.command("get_property", "current-ao")
        except IpcError:
            pass
        if not ao:
            try:
                names = _enabled_ao_names(ipc.command("get_property", "ao"))
                ao = "+".join(names) if names else None
            except IpcError:
                pass
        if not ao and self._spec.ao:
            ao = self._spec.ao
        try:
            device = ipc.command("get_property", "audio-device")
        except IpcError:
            pass
        if not device and self._spec.exclusive:
            device = self._spec.mpv_audio_device()
        elif not device and self._spec.audio_device:
            device = self._spec.audio_device
        parts = [str(part) for part in (ao, device) if part]
        mode = "exclusive" if self._spec.exclusive else "system"
        detail = " ".join(parts) if parts else "unknown"
        return f"{mode} {detail}"

    def audio_pcm(self) -> PcmReading:
        ipc = self._require_ipc()
        reading = PcmReading()
        try:
            rate, fmt = parse_params(ipc.command("get_property", "audio-params"))
            reading = reading.with_decode(rate, fmt)
        except IpcError:
            pass
        try:
            rate, fmt = parse_params(ipc.command("get_property", "audio-out-params"))
            reading = reading.with_output(rate, fmt)
        except IpcError:
            pass
        self._pcm = reading
        return reading

    def pause(self) -> None:
        self._require_ipc().command("set_property", "pause", True)

    def resume(self) -> None:
        self._require_ipc().command("set_property", "pause", False)

    def seek(self, seconds: float) -> None:
        self._require_ipc().command("seek", seconds, "absolute")

    def set_volume(self, volume: float) -> None:
        self._require_ipc().command("set_property", "volume", volume)

    def stop(self) -> None:
        self._require_ipc().command("stop")

    def close(self) -> None:
        self._stopping = True
        self._teardown_mpv()
        if self._pw_release is not None:
            restore_card(self._pw_release)
            self._pw_release = None

    def _start_exclusive(self, spec: OutputSpec) -> None:
        hw = spec.exclusive_device
        if not hw.startswith("hw:") or "plughw:" in hw:
            raise ProcessError("exclusive 需要 hw:CARD=…,DEV=…，拒絕 plughw")
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                self._pw_release = release_card_for_exclusive(
                    hw, preserve=self._pw_release
                )
                time.sleep(0.6)
                self._proc = start_mpv(
                    self._socket_path,
                    audio_device=spec.mpv_audio_device(),
                    exclusive=True,
                )
                self._bind_ipc()
                self._assert_hw(hw)
                return
            except Exception as exc:
                last_exc = exc
                log.warning("exclusive open %s/3 failed: %s", attempt + 1, exc)
                self._teardown_mpv()
                time.sleep(0.4 + attempt * 0.3)
                self._pw_release = release_card_for_exclusive(
                    hw, preserve=self._pw_release
                )
        restore_card(self._pw_release)
        self._pw_release = None
        raise ProcessError(f"exclusive 無法打開 {hw}：{last_exc}") from last_exc

    def _assert_hw(self, hw: str) -> None:
        ipc = self._require_ipc()
        actual = str(ipc.command("get_property", "audio-device") or "")
        if "plughw:" in actual:
            raise ProcessError(f"拒絕 plughw：{actual}")
        leak = any(
            token in actual.lower() for token in ("auto", "pipewire", "pulse", "default")
        ) or actual == ""
        if hw not in actual or leak:
            raise ProcessError(
                f"mpv 未進入 exclusive（audio-device={actual!r}，要的是 {hw}）"
            )

    def _assert_system_output(self, spec: OutputSpec) -> None:
        ipc = self._require_ipc()
        if spec.ao:
            try:
                actual = ipc.command("get_property", "ao")
            except IpcError as exc:
                raise ProcessError(f"無法讀取 ao：{exc}") from exc
            names = _enabled_ao_names(actual)
            if spec.ao not in names:
                raise ProcessError(f"mpv ao={actual!r}，不是 {spec.ao}")
        if spec.audio_device:
            try:
                device = str(ipc.command("get_property", "audio-device") or "")
            except IpcError as exc:
                raise ProcessError(f"無法讀取 audio-device：{exc}") from exc
            if spec.audio_device not in device:
                raise ProcessError(
                    f"mpv audio-device={device!r}，不是 {spec.audio_device}"
                )

    def _bind_ipc(self) -> None:
        self._ipc = MpvIpc(self._socket_path)
        self._ipc.command("observe_property", 1, "playback-time")
        self._ipc.command("observe_property", 2, "duration")
        self._ipc.command("observe_property", 3, "eof-reached")
        self._ipc.command("observe_property", 4, "pause")
        self._ipc.command("observe_property", 5, "audio-params")
        self._ipc.command("observe_property", 6, "audio-out-params")
        self._running = True
        self._dispatch = threading.Thread(target=self._pump, daemon=True)
        self._dispatch.start()

    def _teardown_mpv(self) -> None:
        self._running = False
        if self._ipc is not None:
            try:
                self._ipc.command("quit", timeout=1)
            except (IpcError, OSError):
                pass
            self._ipc.close()
            self._ipc = None
        if self._dispatch is not None:
            self._dispatch.join(timeout=1)
            self._dispatch = None
        if self._proc is not None:
            stop_mpv(self._proc, self._socket_path)
            self._proc = None

    def _drain_events(self) -> None:
        while True:
            try:
                self.events.get_nowait()
            except queue.Empty:
                break

    def _require_ipc(self) -> MpvIpc:
        if self._ipc is None:
            raise ProcessError("播放引擎尚未啟動")
        return self._ipc

    def _on_mpv_died(self) -> None:
        if self._stopping:
            return
        code = self._proc.returncode if self._proc is not None else None
        exclusive = self._spec.exclusive
        log.error("mpv died code=%s exclusive=%s", code, exclusive)
        self._running = False
        if self._ipc is not None:
            self._ipc.close()
            self._ipc = None
        if self._proc is not None:
            try:
                self._proc.wait(timeout=0.5)
            except Exception:
                pass
            self._proc = None
        if self._socket_path.exists():
            try:
                self._socket_path.unlink()
            except OSError:
                pass
        if self._pw_release is not None:
            restore_card(self._pw_release)
            self._pw_release = None
        if exclusive:
            detail = f"播放引擎已退出（code={code}），PipeWire 已還原"
        else:
            detail = f"播放引擎已退出（code={code}）"
        self._emit("died", detail)

    def _emit(self, name: str, payload: Any = None) -> None:
        self.events.put(EngineEvent(name, payload))

    def _pump(self) -> None:
        ipc = self._ipc
        if ipc is None:
            return
        while self._running:
            if self._proc is not None and self._proc.poll() is not None:
                self._on_mpv_died()
                return
            try:
                message = ipc.events.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._on_message(message)
            except Exception:
                log.exception("mpv event pump failed on %s", message.get("event"))

    def _on_message(self, message: dict[str, Any]) -> None:
        event = message.get("event")
        if event == "start-file":
            self._emit("playing")
        elif event == "end-file":
            reason = message.get("reason")
            if reason == "eof":
                self._emit("eof")
            elif reason == "error":
                detail = message.get("file_error") or "end-file"
                log.error("mpv end-file error: %s", detail)
                self._emit("error", detail)
        elif event == "property-change":
            name = message.get("name")
            data = message.get("data")
            if name == "duration" and data is not None:
                self._emit("duration", float(data))
            elif name == "playback-time" and data is not None:
                self._emit("time", float(data))
            elif name == "pause" and data is True:
                self._emit("paused")
            elif name == "pause" and data is False:
                self._emit("resumed")
            elif name == "eof-reached" and data is True:
                self._emit("eof")
            elif name == "audio-params":
                rate, fmt = parse_params(data)
                self._pcm = self._pcm.with_decode(rate, fmt)
                self._emit("pcm", self._pcm)
            elif name == "audio-out-params":
                rate, fmt = parse_params(data)
                self._pcm = self._pcm.with_output(rate, fmt)
                self._emit("pcm", self._pcm)
