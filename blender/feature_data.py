"""Loader + helper for per-frame audio feature JSON produced by analyze.py."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


class FeatureData:
    """Wraps the analyzer JSON, exposes per-frame lookups and helpers."""

    def __init__(self, payload: dict[str, Any]):
        self.meta = payload["meta"]
        self.frames = payload["frames"]
        self.events = payload.get("events", {})

        self.fps = int(self.meta["fps"])
        self.n_frames = int(self.meta["n_frames"])
        self.duration = float(self.meta["duration"])
        self.tempo = float(self.meta["tempo"])
        self.source = self.meta["source"]

        self._beats: list[int] = list(self.events.get("beats", []))

    @classmethod
    def load(cls, path: Path) -> "FeatureData":
        return cls(json.loads(Path(path).read_text()))

    # Per-frame scalar lookups (frame indexed from 0).
    def rms(self, f: int) -> float:
        return self._safe(self.frames["rms"], f)

    def onset(self, f: int) -> float:
        return self._safe(self.frames["onset"], f)

    def centroid(self, f: int) -> float:
        return self._safe(self.frames["centroid"], f)

    def flatness(self, f: int) -> float:
        return self._safe(self.frames["flatness"], f)

    def drop(self, f: int) -> float:
        return self._safe(self.frames["drop"], f)

    def beat_phase(self, f: int) -> float:
        return self._safe(self.frames["beat_phase"], f)

    def chroma_class(self, f: int) -> int:
        idx = max(0, min(self.n_frames - 1, f))
        try:
            return int(self.frames["chroma_class"][idx])
        except (IndexError, KeyError):
            return 0

    def chroma_strength(self, f: int) -> float:
        return self._safe(self.frames["chroma_strength"], f)

    def band(self, name: str, f: int) -> float:
        return self._safe(self.frames["bands"][name], f)

    def beats(self) -> list[int]:
        return list(self._beats)

    def is_beat(self, f: int, tol: int = 0) -> bool:
        if not self._beats:
            return False
        for b in self._beats:
            if abs(b - f) <= tol:
                return True
        return False

    @staticmethod
    def _safe(arr: list[float], f: int) -> float:
        if not arr:
            return 0.0
        idx = max(0, min(len(arr) - 1, f))
        return float(arr[idx])

    # Helpers for chroma → colour. Maps the 12 pitch classes around a hue
    # wheel, but offset so C is a cool blue and the wheel rotates clockwise.
    @staticmethod
    def chroma_to_hue(cls_idx: int) -> float:
        # 0..1 hue. Offset so that C = 0.55 (blue), G = 0.0 (red).
        return ((cls_idx / 12.0) + 0.55) % 1.0

    # Smooth a per-frame channel by averaging with neighbouring frames.
    def smooth(self, channel: str, f: int, window: int = 3) -> float:
        try:
            data = self.frames[channel]
        except KeyError:
            return 0.0
        if not data:
            return 0.0
        lo = max(0, f - window)
        hi = min(len(data), f + window + 1)
        return float(sum(data[lo:hi]) / max(1, hi - lo))

    @staticmethod
    def hsv_to_rgb(h: float, s: float, v: float) -> tuple[float, float, float]:
        i = math.floor(h * 6)
        fr = h * 6 - i
        p = v * (1 - s)
        q = v * (1 - fr * s)
        t = v * (1 - (1 - fr) * s)
        i %= 6
        if i == 0: return (v, t, p)
        if i == 1: return (q, v, p)
        if i == 2: return (p, v, t)
        if i == 3: return (p, q, v)
        if i == 4: return (t, p, v)
        return (v, p, q)
