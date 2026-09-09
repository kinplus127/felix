"""Release a DAC from PipeWire for exclusive ALSA, then put it back.

Enter exclusive → card profile ``off`` + persist restore info.
Exit / crash → restore profile + default sink.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

from felix.config import CONFIG_DIR
from felix.logs import get_logger

RESTORE_PATH = CONFIG_DIR / "pw_restore.json"
log = get_logger("pipewire")

_hooks_installed = False
_exit_cleanup: Callable[[], None] | None = None
_pending: CardRelease | None = None


@dataclass
class CardRelease:
    card_name: str
    previous_profile: str
    active_profile: str
    previous_default_sink: str = ""
    previous_default_source: str = ""


def _run(args: list[str], timeout: float = 5.0) -> str:
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(err or f"command failed: {' '.join(args)}")
    return result.stdout


def _pactl_info_value(key: str) -> str:
    try:
        text = _run(["pactl", "info"])
    except (RuntimeError, FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    prefix = f"{key}:"
    for line in text.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""


def _get_default_sink() -> str:
    return _pactl_info_value("Default Sink")


def _get_default_source() -> str:
    return _pactl_info_value("Default Source")


def _parse_cards(text: str) -> list[dict]:
    cards: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        if line.startswith("Card #"):
            if current:
                cards.append(current)
            current = {
                "name": "",
                "alsa_name": "",
                "alsa_id": "",
                "alsa_card_name": "",
                "active_profile": "",
                "profiles": [],
            }
            continue
        if current is None:
            continue
        if line.startswith("\tName:"):
            current["name"] = line.split(":", 1)[1].strip()
        elif "alsa.card_name" in line or "alsa.long_card_name" in line:
            current["alsa_name"] = line.split("=", 1)[-1].strip().strip('"')
        elif re.match(r"^\s*(?:api\.)?alsa\.id\s*=", line):
            current["alsa_id"] = line.split("=", 1)[-1].strip().strip('"')
        elif re.match(r"^\s*api\.alsa\.card\.name\s*=", line):
            current["alsa_card_name"] = (
                line.split("=", 1)[-1].strip().strip('"')
            )
        elif "device.string" in line and "CARD=" in line:
            match = re.search(r"CARD=([^,\"\s]+)", line)
            if match:
                current["alsa_id"] = match.group(1)
        elif line.startswith("\tActive Profile:"):
            current["active_profile"] = line.split(":", 1)[1].strip()
        elif line.startswith("\t\t"):
            match = re.match(r"^\t\t(.+): (.+\(sinks:.*\))\s*$", line)
            if match:
                prof = match.group(1).strip()
                if prof and prof not in current["profiles"]:
                    current["profiles"].append(prof)
    if current:
        cards.append(current)
    return cards


def _list_cards() -> list[dict]:
    try:
        return _parse_cards(_run(["pactl", "list", "cards"]))
    except (RuntimeError, FileNotFoundError, subprocess.TimeoutExpired):
        return []


def _card_by_name(card_name: str) -> dict | None:
    for card in _list_cards():
        if card.get("name") == card_name:
            return card
    return None


def card_id_from_hw(hw_device: str) -> str | None:
    """hw:CARD=Qutest,DEV=0 → Qutest"""
    match = re.search(r"CARD=([^,]+)", hw_device)
    return match.group(1).strip() if match else None


def find_pipewire_card(hw_device: str) -> dict | None:
    card_id = card_id_from_hw(hw_device)
    if not card_id:
        return None
    needle = card_id.lower()
    cards = _list_cards()
    for card in cards:
        exact_ids = {
            str(card.get("alsa_id", "")).strip().lower(),
            str(card.get("alsa_card_name", "")).strip().lower(),
        }
        if needle in exact_ids:
            return card
    for card in cards:
        blob = " ".join(
            [
                card.get("name", ""),
                card.get("alsa_name", ""),
                card.get("alsa_card_name", ""),
            ]
        ).lower()
        if needle in blob or needle.replace(" ", "") in blob.replace(" ", ""):
            return card
    return None


def _pick_profile(profiles: list[str], preferred: str = "") -> str:
    """Non-off profile to restore. Never return ``off``."""
    preferred = (preferred or "").strip()
    if preferred and preferred != "off" and preferred in profiles:
        return preferred
    for cand in ("output:analog-stereo", "pro-audio", "output:iec958-stereo", "HiFi"):
        if cand in profiles:
            return cand
    for prof in profiles:
        if prof and prof != "off":
            return prof
    return ""


def _save_pending(release: CardRelease | None) -> None:
    global _pending
    _pending = release
    if release is None:
        try:
            RESTORE_PATH.unlink(missing_ok=True)
        except OSError:
            log.warning("could not remove PipeWire restore file", exc_info=True)
        return
    try:
        CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        RESTORE_PATH.write_text(json.dumps(asdict(release), indent=2), encoding="utf-8")
        os.chmod(RESTORE_PATH, 0o600)
    except OSError:
        log.error("could not persist PipeWire restore state", exc_info=True)


def _load_pending_file() -> CardRelease | None:
    if not RESTORE_PATH.exists():
        return None
    try:
        data = json.loads(RESTORE_PATH.read_text(encoding="utf-8"))
        return CardRelease(
            card_name=data["card_name"],
            previous_profile=data["previous_profile"],
            active_profile=data["active_profile"],
            previous_default_sink=str(data.get("previous_default_sink") or ""),
            previous_default_source=str(data.get("previous_default_source") or ""),
        )
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        log.warning("PipeWire restore file is unreadable or invalid", exc_info=True)
        return None


def _move_streams_off_card(card_name: str) -> None:
    try:
        sinks = _run(["pactl", "list", "short", "sinks"])
    except (RuntimeError, FileNotFoundError, subprocess.TimeoutExpired):
        return
    token = card_name.replace("alsa_card.", "")
    alt = None
    for line in sinks.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name = parts[1]
        if token and token in name:
            continue
        if name.endswith(".monitor"):
            continue
        alt = name
        break
    if not alt:
        return
    try:
        inputs = _run(["pactl", "list", "short", "sink-inputs"])
    except (RuntimeError, FileNotFoundError, subprocess.TimeoutExpired):
        return
    for line in inputs.splitlines():
        parts = line.split("\t")
        if not parts:
            continue
        try:
            _run(["pactl", "move-sink-input", parts[0], alt])
        except RuntimeError:
            log.debug(
                "could not move PipeWire sink input %s to %s",
                parts[0],
                alt,
                exc_info=True,
            )


def release_card_for_exclusive(
    hw_device: str,
    *,
    preserve: CardRelease | None = None,
) -> CardRelease | None:
    """Set card profile to ``off`` and persist how to undo it."""
    card = find_pipewire_card(hw_device)
    if not card or not card.get("name"):
        log.info("no PipeWire card matched ALSA device %s", hw_device)
        return preserve

    profiles = list(card.get("profiles") or [])
    active = card.get("active_profile") or ""
    if "off" not in profiles:
        log.warning("PipeWire card %s has no off profile", card["name"])
        return preserve

    if preserve and preserve.previous_profile and preserve.previous_profile != "off":
        previous = preserve.previous_profile
    elif active and active != "off":
        previous = active
    else:
        previous = _pick_profile(profiles, "")
    if not previous or previous == "off":
        previous = _pick_profile(profiles, active)
    if not previous or previous == "off":
        return preserve

    default_sink = (
        preserve.previous_default_sink
        if preserve and preserve.previous_default_sink
        else _get_default_sink()
    )
    default_source = (
        preserve.previous_default_source
        if preserve and preserve.previous_default_source
        else _get_default_source()
    )

    _move_streams_off_card(card["name"])
    if active != "off":
        try:
            _run(["pactl", "set-card-profile", card["name"], "off"])
        except RuntimeError:
            log.warning("could not release PipeWire card %s", card["name"], exc_info=True)
            return preserve

    release = CardRelease(
        card_name=card["name"],
        previous_profile=previous,
        active_profile="off",
        previous_default_sink=default_sink,
        previous_default_source=default_source,
    )
    for _ in range(15):
        time.sleep(0.1)
        now = _card_by_name(card["name"])
        if now and now.get("active_profile") == "off":
            break
    _save_pending(release)
    log.info("PipeWire card %s profile off (restore %s)", card["name"], previous)
    return release


def restore_card(release: CardRelease | None, *, clear_pending: bool = True) -> bool:
    """Restore profile + default sink. Caller must have released ALSA first."""
    target = release or _pending or _load_pending_file()
    if target is None:
        return True

    card = _card_by_name(target.card_name)
    if card is None:
        log.error("PipeWire card disappeared during restore: %s", target.card_name)
        return False

    profiles = list(card.get("profiles") or [])
    desired = _pick_profile(profiles, target.previous_profile)
    if not desired:
        log.error("no usable PipeWire profile for restore: %s", target.card_name)
        return False

    current = card.get("active_profile") or ""
    if current != desired:
        for _ in range(8):
            try:
                _run(["pactl", "set-card-profile", target.card_name, desired])
            except RuntimeError:
                log.debug(
                    "PipeWire profile restore retry failed for %s",
                    target.card_name,
                    exc_info=True,
                )
                time.sleep(0.25)
                continue
            time.sleep(0.2)
            now = _card_by_name(target.card_name)
            if now and now.get("active_profile") == desired:
                current = desired
                break
            time.sleep(0.25)

    if current == "off" or (_card_by_name(target.card_name) or {}).get("active_profile") == "off":
        log.error("PipeWire card remained off after restore: %s", target.card_name)
        return False

    sink = (target.previous_default_sink or "").strip()
    if sink:
        for _ in range(30):
            try:
                names = {
                    line.split("\t")[1]
                    for line in _run(["pactl", "list", "short", "sinks"]).splitlines()
                    if "\t" in line
                }
            except (RuntimeError, FileNotFoundError, subprocess.TimeoutExpired):
                names = set()
            if sink in names:
                try:
                    _run(["pactl", "set-default-sink", sink])
                except RuntimeError:
                    log.debug("could not restore default PipeWire sink %s", sink, exc_info=True)
                break
            time.sleep(0.1)
    source = (target.previous_default_source or "").strip()
    if source:
        try:
            _run(["pactl", "set-default-source", source])
        except RuntimeError:
            log.debug("could not restore default PipeWire source %s", source, exc_info=True)

    if clear_pending:
        _save_pending(None)
    log.info("PipeWire card %s restored to %s", target.card_name, desired)
    return True


def restore_any_pending() -> bool:
    """Restore from memory or leftover file (startup / fallback)."""
    pending = _pending or _load_pending_file()
    if pending is None:
        return True
    log.info("restoring leftover PipeWire exclusive state")
    return restore_card(pending, clear_pending=True)


def set_exit_cleanup(callback: Callable[[], None] | None) -> None:
    global _exit_cleanup
    _exit_cleanup = callback


def _run_exit_cleanup() -> None:
    cb = _exit_cleanup
    if cb is not None:
        try:
            cb()
            return
        except Exception:
            log.exception("registered audio cleanup failed; using restore fallback")
    restore_any_pending()


def install_exit_hooks() -> None:
    """SIGTERM / SIGHUP / atexit restore PipeWire. SIGINT left to the CLI."""
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True
    atexit.register(_run_exit_cleanup)

    def _handler(signum: int, _frame) -> None:
        for sig in (signal.SIGTERM, signal.SIGHUP):
            try:
                signal.signal(sig, signal.SIG_IGN)
            except (ValueError, OSError):
                pass
        try:
            _run_exit_cleanup()
        finally:
            signal.signal(signum, signal.SIG_DFL)
            signal.raise_signal(signum)

    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass
