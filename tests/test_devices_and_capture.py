"""
Device selection and track opening.

Core regression guard (audit P0.1): when system audio cannot be opened,
Malva must raise a typed error and must NOT open the microphone instead.
"""

import pytest

from conftest import FakePA, device
from malva.audio.devices import (
    ERR_DEVICE_NOT_FOUND,
    ERR_LOOPBACK_UNAVAILABLE,
    AudioDeviceError,
    find_default_microphone,
    find_loopback_device,
)


# ------------------------------------------------------------------ device selection

def test_loopback_found_for_default_output():
    out = device(3, "Speakers (Realtek)", inputs=0, rate=48000.0)
    lb = device(9, "Speakers (Realtek) [Loopback]", inputs=2, rate=48000.0, loopback=True)
    pa = FakePA(devices=[out], wasapi_default_output=3, loopbacks=[lb])
    found = find_loopback_device(pa)
    assert found.index == 9
    assert found.is_loopback is True
    assert found.max_input_channels == 2


def test_default_output_already_loopback_is_used_directly():
    lb = device(4, "Speakers [Loopback]", inputs=2, rate=48000.0, loopback=True)
    pa = FakePA(devices=[lb], wasapi_default_output=4, loopbacks=[])
    assert find_loopback_device(pa).index == 4


def test_missing_loopback_raises_and_never_returns_microphone():
    out = device(3, "Speakers (Realtek)", inputs=0, rate=48000.0)
    mic = device(0, "Microphone", inputs=1)
    pa = FakePA(devices=[out, mic], default_input=0, wasapi_default_output=3, loopbacks=[])
    with pytest.raises(AudioDeviceError) as exc:
        find_loopback_device(pa)
    assert exc.value.code == ERR_LOOPBACK_UNAVAILABLE
    assert "dialihkan ke mikrofon" in exc.value.message  # explicit: no fallback


def test_wasapi_missing_is_a_typed_error():
    pa = FakePA(devices=[], wasapi=False)
    with pytest.raises(AudioDeviceError) as exc:
        find_loopback_device(pa)
    assert exc.value.code == ERR_LOOPBACK_UNAVAILABLE


def test_no_default_microphone_is_typed_error():
    pa = FakePA(devices=[], default_input=None)
    with pytest.raises(AudioDeviceError) as exc:
        find_default_microphone(pa)
    assert exc.value.code == ERR_DEVICE_NOT_FOUND


# ------------------------------------------------------------------ track opening

def test_system_audio_without_loopback_does_not_open_microphone(fake_mic_only):
    capture = fake_mic_only
    from malva.audio.capture import AudioTrack, TrackSource

    track = AudioTrack(TrackSource.SYSTEM_AUDIO, "s1", on_utterance=lambda *a: None)
    with pytest.raises(AudioDeviceError) as exc:
        track.start()
    assert exc.value.code == ERR_LOOPBACK_UNAVAILABLE
    assert track.state.value == "idle"           # never reported as active
    # No stream was opened on any backend.
    assert all(not pa.opened for pa in FakePA.instances)


def test_microphone_track_opens_and_stops_cleanly(fake_mic_only):
    capture = fake_mic_only
    from malva.audio.capture import AudioTrack, TrackSource

    track = AudioTrack(TrackSource.MICROPHONE, "s1", on_utterance=lambda *a: None)
    track.start()
    try:
        assert track.is_active
        assert track.device_name == "Microphone (USB)"
        assert track.sample_rate == 16000
    finally:
        track.stop()
    assert track.state.value == "stopped"
    assert any(pa.terminated for pa in FakePA.instances)


def test_open_failure_on_every_rate_is_reported(monkeypatch):
    import malva.audio.capture as capture

    mic = [device(0, "Mic", inputs=1, rate=16000.0)]
    failing = FakePA(devices=mic, default_input=0, fail_rates=(16000, 44100, 48000))
    monkeypatch.setattr(capture, "pyaudio", type("M", (), {
        "PyAudio": staticmethod(lambda: failing), "paInt16": 8}))

    from malva.audio.capture import AudioTrack, TrackSource
    track = AudioTrack(TrackSource.MICROPHONE, "s1", on_utterance=lambda *a: None)
    with pytest.raises(AudioDeviceError) as exc:
        track.start()
    assert exc.value.code == "OPEN_FAILED"


def test_stereo_loopback_is_opened_with_real_device_format(monkeypatch):
    import malva.audio.capture as capture

    out = device(3, "Speakers", inputs=0, rate=48000.0)
    lb = device(9, "Speakers [Loopback]", inputs=2, rate=48000.0, loopback=True)
    pa_wp = FakePA(devices=[out, lb], wasapi_default_output=3, loopbacks=[lb])
    monkeypatch.setattr(capture, "pyaudio_wp", type("WP", (), {"PyAudio": staticmethod(lambda: pa_wp)}))
    monkeypatch.setattr(capture, "_HAS_WPATCH", True)

    from malva.audio.capture import AudioTrack, TrackSource
    track = AudioTrack(TrackSource.SYSTEM_AUDIO, "s1", on_utterance=lambda *a: None)
    track.start()
    try:
        assert pa_wp.opened[0]["device"] == 9
        assert pa_wp.opened[0]["channels"] == 2     # device's own channel count
        assert pa_wp.opened[0]["rate"] == 48000     # device's own rate, tried first
        assert track.sample_rate == 48000
    finally:
        track.stop()


# ------------------------------------------------------------------ engine invariants

def test_engine_never_creates_duplicate_track(fake_mic_only):
    capture = fake_mic_only
    from malva.audio.capture import AudioEngine, TrackSource

    engine = AudioEngine("s1", "assistant", on_utterance=lambda *a: None)
    first = engine.start_microphone()
    second = engine.start_microphone()
    try:
        assert first is second
        total_opens = sum(len(p.opened) for p in FakePA.instances)
        assert total_opens == 1, "second start must not open another stream"
    finally:
        engine.stop_all()


def test_voice_input_rejects_system_audio_at_engine_level(fake_mic_only):
    from malva.audio.capture import AudioEngine

    engine = AudioEngine("s1", "voice_input", on_utterance=lambda *a: None)
    with pytest.raises(ValueError):
        engine.start_system_audio()
    assert all(not pa.opened for pa in FakePA.instances)


def test_levels_are_tagged_with_source(fake_mic_only):
    import time
    from malva.audio.capture import AudioEngine, TrackSource

    seen = []
    engine = AudioEngine("s1", "assistant", on_utterance=lambda *a: None,
                         on_levels=lambda src, lv: seen.append((src, lv)))
    engine.start_microphone()
    deadline = time.time() + 2.0
    while not seen and time.time() < deadline:
        time.sleep(0.02)
    engine.stop_all()
    assert seen, "no level events emitted"
    src, levels = seen[0]
    assert src == TrackSource.MICROPHONE
    assert len(levels) == 5 and all(0.0 <= v <= 1.0 for v in levels)
