"""OutputSpec and exclusive mpv args. Does not start a working player."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from felix.engine.output import OutputSpec
from felix.engine.process import ProcessError, start_mpv


class TestOutputSpec(unittest.TestCase):
    def test_exclusive_uses_alsa_hw(self) -> None:
        spec = OutputSpec(
            exclusive=True,
            ao="pipewire",
            exclusive_device="hw:CARD=Qutest,DEV=0",
        )
        self.assertEqual(spec.mpv_ao(), "alsa")
        self.assertEqual(spec.mpv_audio_device(), "alsa/hw:CARD=Qutest,DEV=0")

    def test_system_keeps_pref(self) -> None:
        spec = OutputSpec(exclusive=False, ao="pipewire", audio_device="")
        self.assertEqual(spec.mpv_ao(), "pipewire")
        self.assertEqual(spec.mpv_audio_device(), "")


class TestExclusiveStartRejectsPlugHw(unittest.TestCase):
    def test_plughw_rejected(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "mpv.sock"
            with self.assertRaises(ProcessError):
                start_mpv(
                    path,
                    exclusive=True,
                    audio_device="alsa/plughw:CARD=Qutest,DEV=0",
                )

    def test_missing_device_rejected(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "mpv.sock"
            with self.assertRaises(ProcessError):
                start_mpv(path, exclusive=True, audio_device="")
