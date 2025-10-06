# -*- coding: utf-8 -*-
import time, audioop
from dataclasses import dataclass
from typing import Callable

@dataclass(frozen=True)
class SegmenterConfig:
    silence_ms: int = 500
    rms_thresh: int = 400
    min_bytes: int = 24000

class Segmenter:
    """
    Callback-basiertes Turn-Taking über RMS-Schwelle + Stille-Fenster.
    API bleibt identisch: feed20ms(frame16k_20ms) / feed16k(pcm16k).
    """
    def __init__(self, on_segment: Callable[[bytes], None], cfg: SegmenterConfig | None = None):
        self.on_segment = on_segment
        self.cfg = cfg or SegmenterConfig()
        self.buf = bytearray()
        self._last = time.time()
        self._silent_ms = 0

    def feed16k(self, pcm: bytes):
        self.buf.extend(pcm)
        try:
            rms = audioop.rms(pcm, 2)
        except Exception:
            rms = 0

        now = time.time()
        dt_ms = (now - self._last) * 1000.0
        self._last = now

        self._silent_ms = self._silent_ms + dt_ms if rms < self.cfg.rms_thresh else 0

        if self._silent_ms >= self.cfg.silence_ms and len(self.buf) > self.cfg.min_bytes:
            seg = bytes(self.buf)
            self.buf.clear()
            self._silent_ms = 0
            try:
                self.on_segment(seg)
            except Exception as e:
                print("[SEG] callback error:", e)

    def feed20ms(self, frame16k_20ms: bytes):
        self.feed16k(frame16k_20ms)
