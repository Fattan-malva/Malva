"""
malva.asr.service — Decides whether speech may be sent to the cloud and opens streams.

Cloud speech is approved by product decision (Blueprint §3, §9): it runs whenever
GEMINI_API_KEY is set and CLOUD_ENABLED is not turned off. A missing key or a disabled
cloud is reported to the user; audio is never sent anywhere else.
"""

from __future__ import annotations

from typing import Any, Callable

from malva.asr.gemini_live import MODEL_DEFAULT, GeminiLiveStream, language_codes_for
from malva.asr.types import ASR_CLOUD_DISABLED, ASR_NOT_CONFIGURED

REASON_MESSAGES = {
    ASR_NOT_CONFIGURED: "Transkripsi belum diatur. Isi GEMINI_API_KEY di file .env.",
    ASR_CLOUD_DISABLED: "Transkripsi memakai Gemini cloud, tetapi CLOUD_ENABLED=false di .env.",
}


class ASRService:
    def __init__(
        self,
        *,
        privacy: Any,
        api_key: str,
        model: str = MODEL_DEFAULT,
        language_getter: Callable[[], str],
        client_factory: Callable[[], Any] | None = None,
        types_module: Any | None = None,
    ):
        self._privacy = privacy
        self._api_key = (api_key or "").strip()
        self._model = model or MODEL_DEFAULT
        self._language_getter = language_getter
        self._client_factory = client_factory
        self._types_module = types_module

    @property
    def model_name(self) -> str:
        return self._model

    def block_reason(self) -> str:
        """Empty string when transcription may run; otherwise the reason it may not."""
        if not self._api_key:
            return ASR_NOT_CONFIGURED
        if self._privacy is None or not self._privacy.allows_cloud_asr():
            return ASR_CLOUD_DISABLED
        return ""

    def open_stream(
        self,
        label: str,
        on_partial: Callable[[str], None],
        on_final: Callable[[str], None],
        on_error: Callable[[str, str], None],
    ) -> GeminiLiveStream | None:
        reason = self.block_reason()
        if reason:
            on_error(reason, REASON_MESSAGES[reason])
            return None
        stream = GeminiLiveStream(
            label,
            api_key=self._api_key,
            model=self._model,
            language_codes=language_codes_for(self._language_getter()),
            on_partial=on_partial,
            on_final=on_final,
            on_error=on_error,
            client_factory=self._client_factory,
            types_module=self._types_module,
        )
        stream.start()
        return stream

    def status(self) -> dict:
        reason = self.block_reason()
        return {
            "model": self._model,
            "configured": bool(self._api_key),
            "cloud_allowed": bool(self._privacy and self._privacy.allows_cloud_asr()),
            "ready": reason == "",
            "reason": REASON_MESSAGES.get(reason, ""),
            "language_setting": self._language_getter(),
        }
