"""
malva.audio.devices — Device discovery with explicit, typed failures.

Blueprint §8 / audit P0.1:
  * System audio MUST come from a real WASAPI loopback endpoint.
  * If no loopback endpoint exists, we raise AudioDeviceError. We NEVER
    fall back to the default input device (that would capture the
    microphone and label it as system audio).

Functions take the PyAudio-compatible object as an argument, so the
selection logic is testable with a fake backend on any OS.
"""

from __future__ import annotations

from dataclasses import dataclass

# PortAudio host API type id for WASAPI (paWASAPI).
PA_WASAPI = 13

ERR_DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
ERR_LOOPBACK_UNAVAILABLE = "LOOPBACK_UNAVAILABLE"
ERR_OPEN_FAILED = "OPEN_FAILED"
ERR_DEVICE_LOST = "DEVICE_LOST"


class AudioDeviceError(RuntimeError):
    """Raised when a requested audio source cannot be opened. `code` is stable."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DeviceInfo:
    index: int
    name: str
    max_input_channels: int
    default_sample_rate: float
    is_loopback: bool = False

    @classmethod
    def from_pa(cls, info: dict) -> "DeviceInfo":
        return cls(
            index=int(info["index"]),
            name=str(info.get("name", "")),
            max_input_channels=int(info.get("maxInputChannels", 0) or 0),
            default_sample_rate=float(info.get("defaultSampleRate", 0.0) or 0.0),
            is_loopback=bool(info.get("isLoopbackDevice", False)),
        )


def find_default_microphone(pa) -> DeviceInfo:
    """Default input device for microphone capture."""
    try:
        info = pa.get_default_input_device_info()
    except Exception as e:  # PortAudio raises IOError when no input exists
        raise AudioDeviceError(
            ERR_DEVICE_NOT_FOUND,
            "Tidak ada mikrofon default. Hubungkan mikrofon lalu coba lagi.",
        ) from e
    dev = DeviceInfo.from_pa(info)
    if dev.max_input_channels < 1:
        raise AudioDeviceError(ERR_DEVICE_NOT_FOUND, "Perangkat input default tidak memiliki channel input.")
    return dev


def find_loopback_device(pa) -> DeviceInfo:
    """
    Locate the WASAPI loopback endpoint that mirrors the default output device.

    `pa` must be a PyAudioWPatch PyAudio instance. Raises AudioDeviceError with
    LOOPBACK_UNAVAILABLE when WASAPI or a matching loopback endpoint is missing.
    """
    try:
        host = pa.get_host_api_info_by_type(PA_WASAPI)
    except Exception as e:
        raise AudioDeviceError(
            ERR_LOOPBACK_UNAVAILABLE,
            "WASAPI tidak tersedia di sistem ini, jadi audio sistem tidak bisa direkam.",
        ) from e

    try:
        default_out = pa.get_device_info_by_index(host["defaultOutputDevice"])
    except Exception as e:
        raise AudioDeviceError(
            ERR_LOOPBACK_UNAVAILABLE,
            "Tidak ada perangkat output default untuk direkam.",
        ) from e

    # Some builds expose the default output already as its loopback twin.
    if default_out.get("isLoopbackDevice"):
        return DeviceInfo.from_pa(default_out)

    out_name = str(default_out.get("name", ""))
    try:
        for lb in pa.get_loopback_device_info_generator():
            # Loopback endpoint names are "<output name> [Loopback]" style.
            if out_name and out_name in str(lb.get("name", "")):
                return DeviceInfo.from_pa(lb)
    except Exception as e:
        raise AudioDeviceError(
            ERR_LOOPBACK_UNAVAILABLE,
            f"Gagal membaca daftar loopback untuk '{out_name}': {e}",
        ) from e

    raise AudioDeviceError(
        ERR_LOOPBACK_UNAVAILABLE,
        f"Tidak ditemukan loopback WASAPI untuk output '{out_name}'. "
        "Audio sistem tidak direkam (tidak dialihkan ke mikrofon).",
    )
