"""
malva.audio.analysis — Real frequency-band analysis for the UI visualizer.

Pure numpy, no audio device dependency, so it can be unit-tested anywhere.

Contract (documented, Blueprint §8/§5):
  SpectrumAnalyzer.process(samples) -> list[float] of length n_bands,
  every value in [0.0, 1.0]. 0.0 = silence / baseline, 1.0 = loud.

Bands are logarithmically spaced between f_min and f_max, which matches
how speech energy is distributed (more bins for low frequencies).
Values are smoothed with separate attack/release coefficients so the bars
rise quickly and fall gently, without flicker.

Nothing here is random or synthetic: an all-zero input always decays to
zero, and a sine wave always raises the band that contains its frequency.
"""

from __future__ import annotations

import math

import numpy as np

# Full-scale int16 input is normalised to [-1, 1] before analysis.
_INT16_SCALE = 32768.0
# dBFS window mapped onto the 0..1 output range.
_FLOOR_DB = -60.0
_CEIL_DB = 0.0


class SpectrumAnalyzer:
    def __init__(
        self,
        sample_rate: int = 16000,
        n_bands: int = 5,
        fft_size: int = 1024,
        f_min: float = 80.0,
        f_max: float | None = None,
        attack: float = 0.6,
        release: float = 0.15,
    ):
        if n_bands < 1:
            raise ValueError("n_bands must be >= 1")
        if not (0.0 < attack <= 1.0 and 0.0 < release <= 1.0):
            raise ValueError("attack and release must be in (0, 1]")

        self.sample_rate = int(sample_rate)
        self.n_bands = int(n_bands)
        self.fft_size = int(fft_size)
        self.attack = float(attack)
        self.release = float(release)

        nyquist = self.sample_rate / 2.0
        top = min(f_max if f_max is not None else 8000.0, nyquist)
        bottom = min(max(f_min, 1.0), top / 2.0)

        edges = np.geomspace(bottom, top, self.n_bands + 1)
        freqs = np.fft.rfftfreq(self.fft_size, d=1.0 / self.sample_rate)
        self._masks: list[np.ndarray] = []
        for i in range(self.n_bands):
            lo, hi = edges[i], edges[i + 1]
            if i == self.n_bands - 1:
                mask = (freqs >= lo) & (freqs <= hi)
            else:
                mask = (freqs >= lo) & (freqs < hi)
            self._masks.append(mask)

        self._window = np.hanning(self.fft_size)
        # Scale so a full-scale sine at a bin centre measures ~0 dBFS.
        self._gain = 2.0 / float(np.sum(self._window))
        self._smoothed = np.zeros(self.n_bands, dtype=np.float64)

    # ------------------------------------------------------------------ public

    @property
    def band_edges_hz(self) -> list[tuple[float, float]]:
        """Human-readable band edges (for logs and tests)."""
        freqs = np.fft.rfftfreq(self.fft_size, d=1.0 / self.sample_rate)
        out = []
        for mask in self._masks:
            if mask.any():
                out.append((float(freqs[mask][0]), float(freqs[mask][-1])))
            else:
                out.append((0.0, 0.0))
        return out

    def process(self, samples) -> list[float]:
        """Analyse the most recent frame. Never raises on bad input."""
        frame = self._prepare_frame(samples)
        if frame is None:
            return self._decay()

        spectrum = np.abs(np.fft.rfft(frame * self._window)) * self._gain
        targets = np.zeros(self.n_bands, dtype=np.float64)
        for i, mask in enumerate(self._masks):
            if not mask.any():
                continue
            band = spectrum[mask]
            # RMS of the band's magnitudes → one amplitude per band.
            amp = math.sqrt(float(np.mean(band * band)))
            db = 20.0 * math.log10(max(amp, 1e-9))
            targets[i] = (db - _FLOOR_DB) / (_CEIL_DB - _FLOOR_DB)

        targets = np.clip(np.nan_to_num(targets, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
        coeff = np.where(targets > self._smoothed, self.attack, self.release)
        self._smoothed = self._smoothed + (targets - self._smoothed) * coeff
        self._smoothed = np.clip(self._smoothed, 0.0, 1.0)
        return [round(float(v), 4) for v in self._smoothed]

    def reset(self) -> list[float]:
        """Snap every band to baseline (used on stop, pause, sleep, device loss)."""
        self._smoothed = np.zeros(self.n_bands, dtype=np.float64)
        return [0.0] * self.n_bands

    # ------------------------------------------------------------------ helpers

    def _decay(self) -> list[float]:
        """No usable samples this frame: release towards zero."""
        self._smoothed = np.clip(self._smoothed * (1.0 - self.release), 0.0, 1.0)
        return [round(float(v), 4) for v in self._smoothed]

    def _prepare_frame(self, samples) -> np.ndarray | None:
        try:
            x = np.asarray(samples, dtype=np.float64).reshape(-1)
        except (TypeError, ValueError):
            return None
        if x.size == 0:
            return None
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        if np.max(np.abs(x)) > 1.5:  # raw int16 PCM → normalise
            x = x / _INT16_SCALE
        x = np.clip(x, -1.0, 1.0)
        if x.size >= self.fft_size:
            return x[-self.fft_size:]
        padded = np.zeros(self.fft_size, dtype=np.float64)
        padded[-x.size:] = x
        return padded
