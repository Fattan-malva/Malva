"""Spectrum analysis: real frequency content, safe on bad input, documented [0, 1] range."""

import numpy as np
import pytest

from malva.audio.analysis import SpectrumAnalyzer


def _sine(freq, amp=0.5, rate=16000, n=1024):
    t = np.arange(n) / rate
    return (amp * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)


def _settle(analyzer, frame, times=6):
    out = None
    for _ in range(times):
        out = analyzer.process(frame)
    return out


@pytest.mark.parametrize("freq, expected_band", [
    (1000, 2),   # 516–1266 Hz
    (2500, 3),   # 1281–3172 Hz
    (6000, 4),   # 3188–8000 Hz
])
def test_sine_lands_in_matching_band(freq, expected_band):
    a = SpectrumAnalyzer(sample_rate=16000)
    out = _settle(a, _sine(freq))
    assert int(np.argmax(out)) == expected_band
    assert out[expected_band] > 0.3


def test_bands_are_logarithmic_and_cover_speech_range():
    edges = SpectrumAnalyzer(sample_rate=16000).band_edges_hz
    assert len(edges) == 5
    assert edges[0][0] < 150          # starts near 80–100 Hz
    assert edges[-1][1] >= 7800       # reaches ~8 kHz
    widths = [hi / lo for lo, hi in edges]
    assert max(widths) / min(widths) < 1.5  # roughly equal octave-like ratios


def test_silence_stays_at_baseline():
    a = SpectrumAnalyzer()
    assert a.process(np.zeros(1024, dtype=np.int16)) == [0.0] * 5


def test_output_always_in_unit_range():
    a = SpectrumAnalyzer()
    loud = np.full(1024, 32767, dtype=np.int16)
    for _ in range(20):
        out = a.process(loud)
        assert all(0.0 <= v <= 1.0 for v in out)


def test_release_decays_towards_zero_without_snapping():
    a = SpectrumAnalyzer()
    loud = _settle(a, _sine(1000), times=10)
    after_one_silent = a.process(np.zeros(1024, dtype=np.int16))
    assert after_one_silent[2] < loud[2]
    assert after_one_silent[2] > 0.0  # still releasing, not instant


@pytest.mark.parametrize("bad", [
    np.array([np.nan, np.inf, -np.inf]),
    np.array([]),
    "not audio",
    None,
    [[1, 2], [3]],
])
def test_bad_input_never_raises(bad):
    out = SpectrumAnalyzer().process(bad)
    assert len(out) == 5
    assert all(np.isfinite(v) for v in out)


def test_reset_snaps_to_zero():
    a = SpectrumAnalyzer()
    _settle(a, _sine(1000))
    assert a.reset() == [0.0] * 5
    assert a.process(np.zeros(1024)) == [0.0] * 5


def test_short_frames_are_padded_not_rejected():
    a = SpectrumAnalyzer()
    out = _settle(a, _sine(1000, n=256))
    assert len(out) == 5 and all(np.isfinite(v) for v in out)


def test_rejects_invalid_configuration():
    with pytest.raises(ValueError):
        SpectrumAnalyzer(n_bands=0)
    with pytest.raises(ValueError):
        SpectrumAnalyzer(attack=0.0)
