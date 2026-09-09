"""JSON IPC over a Unix socket. Does not know about songs."""

from __future__ import annotations

import json
import queue
import socket
import threading
import time
from pathlib import Path
from typing import Any

from felix.config import MPV_SOCKET_PATH
from felix.logs import get_logger

log = get_logger("ipc")


class IpcError(Exception):
    """mpv IPC command failed or the socket closed."""


class MpvIpc:
    def __init__(self, socket_path: Path | None = None) -> None:
        path = socket_path if socket_path is not None else MPV_SOCKET_PATH
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._connect(path)
        self._sock.settimeout(0.2)
        self._buf = b""
        self._next_id = 1
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _connect(self, path: Path) -> None:
        last: Exception | None = None
        for _ in range(40):
            try:
                self._sock.connect(str(path))
                return
            except OSError as exc:
                last = exc
                time.sleep(0.05)
        log.error("ipc connect failed path=%s", path)
        raise IpcError(f"無法連接 mpv socket：{path}") from last

    def command(self, *args: Any, timeout: float = 5.0) -> Any:
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            pending: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = pending
            payload = json.dumps({"command": list(args), "request_id": request_id})
            self._sock.sendall(payload.encode("utf-8") + b"\n")

        try:
            reply = pending.get(timeout=timeout)
        except queue.Empty as exc:
            name = args[0] if args else "?"
            log.warning("ipc timeout: %s", name)
            raise IpcError(f"指令逾時：{name}") from exc
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

        error = reply.get("error", "success")
        if error != "success":
            name = args[0] if args else "command"
            if name != "get_property":
                log.warning("ipc %s: %s", name, error)
            raise IpcError(f"{name}：{error}")
        return reply.get("data")

    def close(self) -> None:
        self._running = False
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=1)

    def _read_loop(self) -> None:
        while self._running:
            try:
                chunk = self._sock.recv(4096)
            except TimeoutError:
                continue
            except OSError:
                break
            if not chunk:
                break
            self._buf += chunk
            while b"\n" in self._buf:
                raw, self._buf = self._buf.split(b"\n", 1)
                if not raw.strip():
                    continue
                try:
                    message = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                request_id = message.get("request_id")
                if request_id is not None and "event" not in message:
                    with self._lock:
                        pending = self._pending.get(request_id)
                    if pending is not None:
                        pending.put(message)
                    continue
                self.events.put(message)
