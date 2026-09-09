"""Interactive PKCE login. Saves ~/.config/felix/session.json."""

from __future__ import annotations

import sys

from felix.config import SESSION_PATH
from felix.logs import get_logger, setup_logging
from felix.tidal.auth import AuthError, login


def main() -> int:
    setup_logging()
    log = get_logger("login")
    try:
        session = login()
    except AuthError as exc:
        log.error("login failed: %s", exc)
        print(f"登入失敗：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        log.exception("login failed")
        print(f"登入失敗：{exc}", file=sys.stderr)
        return 1

    user = session.user
    user_id = getattr(user, "id", None)
    print("登入成功")
    print(f"  user_id : {user_id}")
    print(f"  country : {session.country_code}")
    print(f"  pkce    : {session.is_pkce}")
    print(f"  quality : {session.audio_quality}")
    print(f"  session : {SESSION_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
