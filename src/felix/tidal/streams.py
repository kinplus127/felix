"""Resolve a track id into a PlaybackSource. No engine calls."""

from __future__ import annotations

from pathlib import Path

import tidalapi
from requests import HTTPError
from tidalapi.exceptions import StreamNotAvailable, TidalAPIError

from felix.config import MPD_DIR, MPD_KEEP
from felix.domain.models import PlaybackSource, Quality, SourceKind
from felix.logs import get_logger
from felix.tidal.auth import raise_if_auth
from felix.tidal.quality import apply_quality

log = get_logger("streams")

_FALLBACK: dict[Quality, tuple[Quality, ...]] = {
    Quality.MAX: (Quality.MAX, Quality.LOSSLESS, Quality.LOW),
    Quality.LOSSLESS: (Quality.LOSSLESS, Quality.LOW),
    Quality.LOW: (Quality.LOW,),
}


class StreamError(Exception):
    """Could not resolve a playable source for this track."""


def _write_mpd(
    track_id: str, manifest_xml: str, protect: Path | None = None
) -> Path:
    directory = MPD_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"felix-{track_id}.mpd"
    path.write_text(manifest_xml, encoding="utf-8")
    extra = (protect,) if protect is not None else ()
    _prune_mpd(directory, keep=path, limit=MPD_KEEP, protected=extra)
    return path


def _prune_mpd(
    directory: Path,
    keep: Path,
    limit: int,
    protected: tuple[Path, ...] = (),
) -> None:
    """Keep at most `limit` felix-*.mpd files; never delete keep or protected."""
    if limit < 1:
        return
    found: list[tuple[float, Path]] = []
    for path in directory.glob("felix-*.mpd"):
        try:
            found.append((path.stat().st_mtime, path))
        except OSError:
            continue
    found.sort()
    protected_keys = {keep.resolve(), *(path.resolve() for path in protected)}
    others = [path for _, path in found if path.resolve() not in protected_keys]
    overflow = len(found) - limit
    if overflow <= 0:
        return
    for path in others[:overflow]:
        try:
            path.unlink(missing_ok=True)
            log.info("pruned mpd %s", path)
        except OSError as exc:
            log.warning("could not prune mpd %s: %s", path, exc)


def _source_from_stream(
    stream: tidalapi.media.Stream,
    requested: Quality,
    protect: Path | None = None,
) -> PlaybackSource:
    if stream.is_mpd:
        location = str(
            _write_mpd(str(stream.track_id), stream.get_manifest_data(), protect=protect)
        )
        kind = SourceKind.MPD_FILE
    elif stream.is_bts:
        manifest = stream.get_stream_manifest()
        if manifest.is_encrypted:
            raise StreamError("此串流已加密，無法播放")
        urls = manifest.get_urls()
        if not urls:
            raise StreamError("串流沒有可用的 URL")
        location = urls[0]
        kind = SourceKind.URL
    else:
        raise StreamError(f"未知的 manifest 類型：{stream.manifest_mime_type}")

    return PlaybackSource(
        kind=kind,
        location=location,
        quality=str(stream.audio_quality),
        bit_depth=stream.bit_depth,
        sample_rate=stream.sample_rate,
        replay_gain=stream.track_replay_gain,
        requested=requested,
    )


def _resolve_at(
    session: tidalapi.Session,
    track_id: str,
    quality: Quality,
    protect: Path | None = None,
) -> PlaybackSource:
    apply_quality(session, quality)
    track = session.track(track_id)
    stream = track.get_stream()
    return _source_from_stream(stream, quality, protect=protect)


def resolve(
    session: tidalapi.Session,
    track_id: str,
    quality: Quality = Quality.MAX,
    protect: Path | None = None,
) -> PlaybackSource:
    """Turn a track id into a URL or temporary MPD file. Falls back on failure."""
    errors: list[str] = []
    for candidate in _FALLBACK[quality]:
        try:
            source = _resolve_at(session, track_id, candidate, protect=protect)
        except (
            StreamNotAvailable,
            TidalAPIError,
            StreamError,
            OSError,
            ValueError,
            HTTPError,
        ) as exc:
            raise_if_auth(exc)
            log.warning("resolve fallback track=%s quality=%s: %s", track_id, candidate, exc)
            errors.append(f"{candidate}: {exc}")
            continue
        if candidate != quality:
            log.warning(
                "resolved track=%s at %s (wanted %s) kind=%s quality=%s",
                track_id,
                candidate,
                quality,
                source.kind,
                source.quality,
            )
        else:
            log.info(
                "resolved track=%s kind=%s quality=%s bit=%s hz=%s",
                track_id,
                source.kind,
                source.quality,
                source.bit_depth,
                source.sample_rate,
            )
        return source

    detail = "; ".join(errors) if errors else "unknown"
    log.error("resolve failed track=%s: %s", track_id, detail)
    raise StreamError(f"無法取得 {track_id} 的串流（{detail}）")
