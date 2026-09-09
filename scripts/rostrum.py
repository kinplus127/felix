"""Interactive control stand. Intent out, Event in. No GUI."""

from __future__ import annotations

import sys
import threading

from felix.domain.events import Event, Position
from felix.domain.intents import Intent
from felix.rostrum import (
    HELP,
    CommandError,
    Rostrum,
    format_ao,
    format_devices,
    format_event,
    format_lists,
    format_now,
    format_queue,
    format_status,
)
from felix.runtime.app import App
from felix.logs import setup_logging
from felix.tidal.auth import AuthError, load


def main() -> int:
    setup_logging()
    try:
        session = load()
    except AuthError as exc:
        print(f"尚未登入：{exc}", file=sys.stderr)
        print("請先執行：python scripts/login.py", file=sys.stderr)
        return 1

    io_lock = threading.Lock()
    app = App(session=session)
    rostrum = Rostrum(app)

    def on_event(event: Event) -> None:
        if isinstance(event, Position):
            return
        text = format_event(event)
        if not text:
            return
        with io_lock:
            print(text, flush=True)

    app.subscribe(on_event)
    print("rostrum  輸入 help 看指令，quit 離開")
    try:
        while True:
            try:
                line = input("rostrum> ")
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                continue
            if not line.strip():
                continue
            try:
                action = rostrum.dispatch(line)
            except CommandError as exc:
                print(f"! {exc}")
                continue
            if action == "help":
                print(HELP)
            elif action == "quit":
                break
            elif action == "now":
                print(format_now(app))
            elif action == "queue":
                print(format_queue(app))
            elif action == "status":
                print(format_status(app))
            elif action == "vol":
                print(f"volume    {app.status().volume:.0f}")
            elif action == "ao":
                print(format_ao(app))
            elif action == "devices":
                print(format_devices())
            elif action == "list":
                print(format_lists(rostrum))
            elif isinstance(action, Intent):
                app.handle(action)
    finally:
        app.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
