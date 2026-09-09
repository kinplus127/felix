"""Parse mpv audio-params / audio-out-params. No TIDAL, no playback policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PcmReading:
    decode_rate: int | None = None
    decode_format: str = ""
    output_rate: int | None = None
    output_format: str = ""

    def with_decode(self, rate: int | None, fmt: str) -> PcmReading:
        return PcmReading(
            decode_rate=rate,
            decode_format=fmt,
            output_rate=self.output_rate,
            output_format=self.output_format,
        )

    def with_output(self, rate: int | None, fmt: str) -> PcmReading:
        return PcmReading(
            decode_rate=self.decode_rate,
            decode_format=self.decode_format,
            output_rate=rate,
            output_format=fmt,
        )


def parse_params(data: Any) -> tuple[int | None, str]:
    if not isinstance(data, dict):
        return None, ""
    raw_rate = data.get("samplerate")
    try:
        rate = int(raw_rate) if raw_rate is not None else None
    except (TypeError, ValueError):
        rate = None
    fmt = str(data.get("format") or "")
    return rate, fmt


def bit_depth_from_format(fmt: str) -> int | None:
    name = (fmt or "").lower()
    if name.startswith("s16") or name.startswith("u16"):
        return 16
    if "s24" in name or "u24" in name:
        return 24
    if name.startswith("s32") or name.startswith("u32"):
        return 32
    return None


def pcm_mismatch(
    source_rate: int | None,
    source_bits: int | None,
    reading: PcmReading,
) -> str:
    """Empty if output matches the source rate (and is not truncated to 16-bit)."""
    reasons: list[str] = []
    out = reading.output_rate
    decode = reading.decode_rate
    if source_rate is not None and out is not None and source_rate != out:
        reasons.append(f"輸出 {out} Hz，源是 {source_rate} Hz（被轉採樣）")
    if decode is not None and out is not None and decode != out:
        reasons.append(f"解碼 {decode} Hz → 輸出 {out} Hz")
    if source_bits is not None and source_bits > 16:
        out_bits = bit_depth_from_format(reading.output_format)
        if out_bits == 16:
            reasons.append(
                f"輸出 {reading.output_format}，源是 {source_bits}-bit（被截成 16-bit）"
            )
    return "；".join(reasons)
