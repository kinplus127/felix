"""Start and stop the idle mpv process."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

from felix.config import MPV_SOCKET_PATH
from felix.logs import get_logger, setup_logging

log = get_logger("mpv")

_SYSTEM_ARGS = (
    "--idle=yes",
    "--no-video",
    "--force-window=no",
    "--audio-display=no",
    "--no-terminal",
    "--no-input-default-bindings",
    "--no-config",
    "--load-unsafe-playlists",
    "--cache=yes",
    "--demuxer-readahead-secs=15",
    "--network-timeout=10",
    "--demuxer-lavf-o-append=protocol_whitelist=file,http,https,tcp,tls,crypto",
    "--demuxer-lavf-o-append=reconnect=1",
    "--demuxer-lavf-o-append=reconnect_streamed=1",
)

_EXCLUSIVE_ARGS = (
    "--ao=alsa",
    "--audio-exclusive=yes",
    "--alsa-resample=no",
    "--alsa-mixer-device=",
    "--replaygain=no",
    "--audio-normalize-downmix=no",
    "--volume=100",
)


class ProcessError(Exception):
    """mpv failed to start or exited unexpectedly."""


def _drain_stderr(proc: subprocess.Popen[bytes]) -> None:
    stream = proc.stderr
    if stream is None:
        return
    for raw in iter(stream.readline, b""):
        line = raw.decode("utf-8", "replace").rstrip()
        if line:
            log.info("%s", line)


def start_mpv(
    socket_path: Path | None = None,
    *,
    ao: str = "",
    audio_device: str = "",
    exclusive: bool = False,
) -> subprocess.Popen[bytes]:
    setup_logging()
    path = socket_path if socket_path is not None else MPV_SOCKET_PATH
    if path.exists():
        path.unlink()

    args = ["mpv", *_SYSTEM_ARGS, f"--input-ipc-server={path}"]
    if exclusive:
        if not audio_device or "plughw:" in audio_device:
            raise ProcessError("exclusive 需要 alsa/hw:CARD=…,DEV=…，拒絕 plughw")
        args.extend(_EXCLUSIVE_ARGS)
        args.append(f"--audio-device={audio_device}")
        log.info("mpv exclusive device=%s", audio_device)
    else:
        if ao:
            args.append(f"--ao={ao}")
        if audio_device:
            args.append(f"--audio-device={audio_device}")
        log.info("mpv args ao=%s device=%s", ao or "auto", audio_device or "auto")

    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            err = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", "replace")
            log.error("mpv exited at start: %s", err.strip() or proc.returncode)
            raise ProcessError(f"mpv 啟動後立即退出：{err.strip() or proc.returncode}")
        if path.exists():
            thread = threading.Thread(
                target=_drain_stderr, args=(proc,), daemon=True, name="mpv-stderr"
            )
            thread.start()
            log.info("mpv started pid=%s socket=%s", proc.pid, path)
            return proc
        time.sleep(0.05)

    proc.terminate()
    log.error("mpv socket wait timed out: %s", path)
    raise ProcessError(f"等待 IPC socket 逾時：{path}")


def stop_mpv(proc: subprocess.Popen[bytes], socket_path: Path | None = None) -> None:
    path = socket_path if socket_path is not None else MPV_SOCKET_PATH
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            log.warning("mpv did not exit, killing pid=%s", proc.pid)
            proc.kill()
            proc.wait(timeout=2)
    if path.exists():
        path.unlink()
    log.info("mpv stopped")
