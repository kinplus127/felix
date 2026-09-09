"""Settings normalisation and load/save. Does not touch ~/.config/felix."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from felix.settings import (
    Settings,
    SettingsError,
    clamp_volume,
    load_settings,
    normalize_ao,
    normalize_device,
    normalize_hw_device,
    normalize_output,
    save_settings,
)


class TestNormalize(unittest.TestCase):
    def test_clamp_volume(self) -> None:
        self.assertEqual(clamp_volume(-10), 0)
        self.assertEqual(clamp_volume(150), 100)
        self.assertEqual(clamp_volume(42.2), 42.2)

    def test_normalize_ao(self) -> None:
        self.assertEqual(normalize_ao("PipeWire"), "pipewire")
        self.assertEqual(normalize_ao("auto"), "")
        self.assertEqual(normalize_ao(""), "")
        with self.assertRaises(SettingsError):
            normalize_ao("jack")

    def test_normalize_output(self) -> None:
        self.assertEqual(normalize_output("shared"), "system")
        self.assertEqual(normalize_output("hw"), "exclusive")
        with self.assertRaises(SettingsError):
            normalize_output("wasapi")

    def test_normalize_device(self) -> None:
        self.assertEqual(normalize_device("auto"), "")
        self.assertEqual(normalize_device("  alsa/foo  "), "alsa/foo")

    def test_normalize_hw_device(self) -> None:
        self.assertEqual(normalize_hw_device(""), "")
        self.assertEqual(
            normalize_hw_device("hw:CARD=Qutest,DEV=0"),
            "hw:CARD=Qutest,DEV=0",
        )
        self.assertEqual(
            normalize_hw_device("alsa/hw:CARD=Qutest,DEV=0"),
            "hw:CARD=Qutest,DEV=0",
        )
        with self.assertRaises(SettingsError):
            normalize_hw_device("plughw:CARD=Qutest,DEV=0")
        with self.assertRaises(SettingsError):
            normalize_hw_device("alsa/plughw:CARD=Qutest,DEV=0")
        with self.assertRaises(SettingsError):
            normalize_hw_device("CARD=Qutest,DEV=0")
        self.assertEqual(normalize_hw_device("default"), "")


class TestSettingsFile(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "settings.json"
        self.patches = [
            patch("felix.settings.CONFIG_DIR", self.dir),
            patch("felix.settings.SETTINGS_PATH", self.path),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def test_missing_file_defaults(self) -> None:
        got = load_settings()
        self.assertEqual(got, Settings())

    def test_roundtrip(self) -> None:
        save_settings(
            Settings(
                volume=80,
                output="exclusive",
                ao="pipewire",
                audio_device="",
                exclusive_device="hw:CARD=Qutest,DEV=0",
            )
        )
        got = load_settings()
        self.assertEqual(got.volume, 80)
        self.assertEqual(got.output, "exclusive")
        self.assertEqual(got.exclusive_device, "hw:CARD=Qutest,DEV=0")

    def test_invalid_exclusive_falls_back_to_system(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "output": "exclusive",
                    "exclusive_device": "plughw:CARD=X,DEV=0",
                }
            ),
            encoding="utf-8",
        )
        got = load_settings()
        self.assertEqual(got.output, "system")
        self.assertEqual(got.exclusive_device, "")
