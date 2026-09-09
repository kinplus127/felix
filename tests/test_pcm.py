"""PCM mismatch rules. No mpv."""

from __future__ import annotations

import unittest

from felix.engine.pcm import PcmReading, bit_depth_from_format, parse_params, pcm_mismatch


class TestPcm(unittest.TestCase):
    def test_parse_params(self) -> None:
        rate, fmt = parse_params({"samplerate": 96000, "format": "s32"})
        self.assertEqual(rate, 96000)
        self.assertEqual(fmt, "s32")
        self.assertEqual(parse_params("nope"), (None, ""))

    def test_bit_depth_from_format(self) -> None:
        self.assertEqual(bit_depth_from_format("s16"), 16)
        self.assertEqual(bit_depth_from_format("s24le"), 24)
        self.assertEqual(bit_depth_from_format("s32"), 32)
        self.assertIsNone(bit_depth_from_format("float"))

    def test_match_24_96_as_s32(self) -> None:
        reading = PcmReading(
            decode_rate=96000,
            decode_format="s32",
            output_rate=96000,
            output_format="s32",
        )
        self.assertEqual(pcm_mismatch(96000, 24, reading), "")

    def test_resample_is_mismatch(self) -> None:
        reading = PcmReading(decode_rate=96000, output_rate=48000, output_format="s32")
        text = pcm_mismatch(96000, 24, reading)
        self.assertIn("轉採樣", text)

    def test_truncate_to_s16_is_mismatch(self) -> None:
        reading = PcmReading(
            decode_rate=96000,
            output_rate=96000,
            output_format="s16",
        )
        text = pcm_mismatch(96000, 24, reading)
        self.assertIn("16-bit", text)
