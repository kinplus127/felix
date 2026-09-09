"""PKCE session load/save. No search, no playback."""

from __future__ import annotations

import os
import webbrowser
from pathlib import Path

import tidalapi

from tidalapi.exceptions import AuthenticationError

from felix.config import CONFIG_DIR, DEFAULT_QUALITY, SESSION_PATH
from felix.domain.models import Quality
from felix.logs import get_logger
from felix.tidal.quality import apply_quality

log = get_logger("auth")


class AuthError(Exception):
    """Login failed or the saved session is not a valid PKCE session."""


LOGIN_HINT = "請重新執行 python scripts/login.py"


def expired_message() -> str:
    return f"TIDAL session 已失效，{LOGIN_HINT}"


def is_auth_failure(exc: BaseException) -> bool:
    """True when an API exception means the user must log in again."""
    if isinstance(exc, (AuthError, AuthenticationError)):
        return True
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in {401, 403}:
        return True
    text = str(exc).lower()
    needles = (
        "token has expired",
        "expired_token",
        "refresh token has expired",
        "unauthorized",
        "authentication error",
        "oauth",
    )
    return any(needle in text for needle in needles)


def raise_if_auth(exc: BaseException) -> None:
    if isinstance(exc, AuthError):
        raise exc
    if is_auth_failure(exc):
        raise AuthError(expired_message()) from exc


def _session_path(path: Path | None) -> Path:
    return path if path is not None else SESSION_PATH


def _prepare_store(path: Path) -> None:
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)
    if path.exists():
        os.chmod(path, 0o600)


def _lock_session_file(path: Path) -> None:
    os.chmod(path, 0o600)


def _apply_quality(session: tidalapi.Session) -> None:
    apply_quality(session, Quality(DEFAULT_QUALITY))


def _is_live_pkce(session: tidalapi.Session) -> bool:
    return bool(session.is_pkce and session.check_login())


def load(session_path: Path | None = None) -> tidalapi.Session:
    """Restore a PKCE session. Does not prompt. Raises if login is required."""
    path = _session_path(session_path)
    if not path.exists():
        log.error("session missing path=%s", path)
        raise AuthError("尚未登入，請先執行 scripts/login.py")

    session = tidalapi.Session()
    session.load_session_from_file(path)
    if not _is_live_pkce(session):
        log.error("session invalid path=%s", path)
        raise AuthError("session 無效或不是 PKCE，請重新執行 scripts/login.py")

    _apply_quality(session)
    log.info("session loaded path=%s", path)
    return session


def login(session_path: Path | None = None) -> tidalapi.Session:
    """Load a PKCE session, or run an interactive PKCE login and persist it."""
    path = _session_path(session_path)
    _prepare_store(path)

    session = tidalapi.Session()
    if path.exists():
        session.load_session_from_file(path)
        if _is_live_pkce(session):
            _apply_quality(session)
            _lock_session_file(path)
            log.info("session reused path=%s", path)
            return session

    url = session.pkce_login_url()
    print("請在瀏覽器開啟下列網址並登入 TIDAL。")
    print("登入後會看到「Oops」頁面，那是正常的。")
    print("請複製該頁完整網址（含 ?code=）並貼回這裡。")
    print()
    print(url)
    print()
    try:
        webbrowser.open(url)
    except Exception:
        pass

    redirect = input("請貼上 Oops 頁網址後按 Enter：").strip()
    if not redirect:
        log.error("pkce login aborted: empty redirect")
        raise AuthError("未提供重新導向網址")

    token = session.pkce_get_auth_token(redirect)
    session.process_auth_token(token, is_pkce_token=True)
    if not _is_live_pkce(session):
        log.error("pkce login failed after token")
        raise AuthError("PKCE 登入失敗")

    session.save_session_to_file(path)
    _lock_session_file(path)
    _apply_quality(session)
    log.info("pkce login saved path=%s", path)
    return session
