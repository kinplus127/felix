"""Parse TIDAL contributors JSON. No session, no playback."""

from __future__ import annotations

from typing import Any

_ROLE_ORDER = (
    "Producer",
    "Composer",
    "Lyricist",
    "Writer",
    "Featuring",
)

_ROLE_LABELS = {
    "PRODUCER": "Producer",
    "COMPOSER": "Composer",
    "LYRICIST": "Lyricist",
    "LYRICS": "Lyricist",
    "WRITER": "Writer",
    "SONGWRITER": "Writer",
    "FEATURED_ARTIST": "Featuring",
    "FEATURED": "Featuring",
    "FEATURING": "Featuring",
}

_SKIP_ROLES = {
    "PRIMARY_ARTIST",
    "MAIN_ARTIST",
    "ARTIST",
    "PERFORMER",
}


def _role_key(raw: str) -> str:
    return (raw or "").strip().replace("-", "_").replace(" ", "_").upper()


def _role_label(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return "Credit"
    mapped = _ROLE_LABELS.get(_role_key(s))
    if mapped:
        return mapped
    key = _role_key(s)
    if "_" in s or s == s.upper():
        return key.replace("_", " ").title()
    return s


def _contributor_name(item: Any) -> str | None:
    if isinstance(item, str):
        name = item.strip()
        return name or None
    if not isinstance(item, dict):
        return None
    for key in ("name", "title"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def parse_contributors(data: Any) -> list[tuple[str, list[str]]]:
    """Normalize TIDAL contributors JSON into ``[(Role, [names]), ...]``."""
    groups: dict[str, list[str]] = {}
    order: list[str] = []

    def add(role_raw: str, name: str | None) -> None:
        if not name:
            return
        key = _role_key(role_raw)
        if key in _SKIP_ROLES:
            return
        label = _role_label(role_raw)
        if label not in groups:
            groups[label] = []
            order.append(label)
        if name not in groups[label]:
            groups[label].append(name)

    def eat_grouped(block: dict[str, Any]) -> bool:
        role = block.get("type") or block.get("role")
        people = block.get("contributors")
        if not isinstance(role, str):
            return False
        if isinstance(people, list):
            for person in people:
                add(role, _contributor_name(person))
            return True
        name = _contributor_name(block)
        if name:
            add(role, name)
            return True
        return False

    payload: Any = data
    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            payload = data["items"]
        elif isinstance(data.get("credits"), list):
            payload = data["credits"]

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                eat_grouped(item)
    elif isinstance(payload, dict):
        eat_grouped(payload)

    ranked = [role for role in _ROLE_ORDER if role in groups]
    rest = [role for role in order if role not in _ROLE_ORDER]
    return [(role, groups[role]) for role in ranked + rest]


def year_from_album(album: Any | None) -> int | None:
    if album is None:
        return None
    year = getattr(album, "year", None)
    if isinstance(year, int) and year > 0:
        return year
    for attr in ("release_date", "tidal_release_date"):
        dt = getattr(album, attr, None)
        if dt is not None and hasattr(dt, "year"):
            try:
                value = int(dt.year)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                return value
    return None


def release_year(track: Any | None) -> int | None:
    if track is None:
        return None
    year = year_from_album(getattr(track, "album", None))
    if year is not None:
        return year
    for attr in ("tidal_release_date", "stream_start_date"):
        dt = getattr(track, attr, None)
        if dt is not None and hasattr(dt, "year"):
            try:
                value = int(dt.year)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                return value
    return None


def copyright_text(obj: Any | None) -> str | None:
    if obj is None:
        return None
    raw = getattr(obj, "copyright", None)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None
