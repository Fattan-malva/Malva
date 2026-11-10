"""Shared fixtures. Tests never touch real audio hardware, Windows APIs, or the network."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeStream:
    """Stands in for a PyAudio input stream. Returns silence, paced like real hardware."""

    def __init__(self, rate: int, channels: int):
        self.rate = rate
        self.channels = channels
        self.closed = False

    def read(self, frames, exception_on_overflow=False):
        time.sleep(0.002)
        return b"\x00\x00" * frames * self.channels

    def stop_stream(self):
        pass

    def close(self):
        self.closed = True


class FakePA:
    """Minimal PyAudio-compatible backend. Records every open attempt."""

    instances: list["FakePA"] = []

    def __init__(self, devices=(), default_input=None, wasapi_default_output=None,
                 loopbacks=(), fail_rates=(), wasapi=True):
        self.devices = {d["index"]: d for d in devices}
        self.default_input = default_input
        self.wasapi_default_output = wasapi_default_output
        self.loopbacks = list(loopbacks)
        self.fail_rates = set(fail_rates)
        self.wasapi = wasapi
        self.opened: list[dict] = []
        self.terminated = False
        FakePA.instances.append(self)

    # --- enumeration -------------------------------------------------------
    def get_default_input_device_info(self):
        if self.default_input is None:
            raise OSError("No default input device available")
        return self.devices[self.default_input]

    def get_device_info_by_index(self, index):
        return self.devices[index]

    def get_host_api_info_by_type(self, _type):
        if not self.wasapi:
            raise OSError("Host API not found")
        return {"defaultOutputDevice": self.wasapi_default_output}

    def get_loopback_device_info_generator(self):
        yield from self.loopbacks

    # --- streams -----------------------------------------------------------
    def open(self, format, channels, rate, input, input_device_index, frames_per_buffer):
        self.opened.append({"device": input_device_index, "rate": rate, "channels": channels})
        if rate in self.fail_rates:
            raise OSError(f"Invalid sample rate {rate}")
        return FakeStream(rate, channels)

    def terminate(self):
        self.terminated = True


def device(index, name, inputs=1, rate=16000.0, loopback=False):
    return {
        "index": index,
        "name": name,
        "maxInputChannels": inputs,
        "defaultSampleRate": rate,
        "isLoopbackDevice": loopback,
    }


@pytest.fixture(autouse=True)
def _reset_fake_pa_registry():
    FakePA.instances.clear()
    yield
    FakePA.instances.clear()


@pytest.fixture
def fake_mic_only(monkeypatch):
    """Machine with a microphone and NO WASAPI loopback (common on Windows without Stereo Mix)."""
    import malva.audio.capture as capture

    mic_devices = [device(0, "Microphone (USB)", inputs=1, rate=16000.0)]

    def make_pa():
        return FakePA(devices=mic_devices, default_input=0, wasapi=False)

    monkeypatch.setattr(capture, "pyaudio", type("PyAudioModule", (), {
        "PyAudio": staticmethod(make_pa), "paInt16": 8,
    }))
    monkeypatch.setattr(capture, "pyaudio_wp", type("WPModule", (), {
        "PyAudio": staticmethod(lambda: FakePA(devices=mic_devices, wasapi=False)),
    }))
    monkeypatch.setattr(capture, "_HAS_WPATCH", True)
    return capture
