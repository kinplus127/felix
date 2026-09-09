"""Map domain Quality onto tidalapi session quality."""

from __future__ import annotations

import tidalapi
from tidalapi import Quality as TidalQuality

from felix.domain.models import Quality

TO_TIDAL = {
    Quality.LOW: TidalQuality.low_320k,
    Quality.LOSSLESS: TidalQuality.high_lossless,
    Quality.MAX: TidalQuality.hi_res_lossless,
}


def apply_quality(session: tidalapi.Session, quality: Quality) -> None:
    session.audio_quality = TO_TIDAL[quality]
