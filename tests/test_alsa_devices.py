"""ALSA listing parser. No aplay required."""

from __future__ import annotations

import unittest

from felix.engine.alsa_devices import parse_aplay_listing


APLAY = """
**** List of PLAYBACK Hardware Devices ****
card 0: PCH [HDA Intel PCH], device 0: ALC1220 Analog [ALC1220 Analog]
card 1: Qutest [Qutest], device 0: USB Audio [USB Audio]
card 1: Qutest [Qutest], device 1: USB Audio [USB Audio #1]
"""


class TestAplayListing(unittest.TestCase):
    def test_parses_hw_cards(self) -> None:
        devices = parse_aplay_listing(APLAY)
        self.assertEqual(devices[0].hw_device, "hw:CARD=PCH,DEV=0")
        self.assertEqual(devices[1].hw_device, "hw:CARD=Qutest,DEV=0")
        self.assertEqual(devices[1].name, "Qutest — USB Audio")
        self.assertEqual(devices[2].hw_device, "hw:CARD=Qutest,DEV=1")

    def test_empty(self) -> None:
        self.assertEqual(parse_aplay_listing("no cards"), [])
