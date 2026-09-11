"""TIDAL catalog, auth, and stream resolution. No playback state."""

from felix.tidal.gate import SessionGate, gate_for

__all__ = ["SessionGate", "gate_for"]
