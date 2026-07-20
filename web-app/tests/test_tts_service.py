from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.tts import (
    EDGE_TTS_MODEL,
    QWEN3_TTS_BASE_MODEL,
    QWEN3_TTS_CUSTOM_VOICE_MODEL,
    TTSRequest,
    create_tts_service,
)
from app.services.tts.providers import qwen3_tts


class TTSServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_edge_listing_does_not_load_legacy_qwen_module(self):
        sys.modules.pop("app.services.tts_qwen", None)
        service = create_tts_service({"tts": {}})
        voices = service.list_voices(EDGE_TTS_MODEL)
        self.assertGreater(len(voices), 5)
        self.assertNotIn("app.services.tts_qwen", sys.modules)
        self.assertEqual(
            service.model_names(),
            [EDGE_TTS_MODEL, QWEN3_TTS_CUSTOM_VOICE_MODEL, QWEN3_TTS_BASE_MODEL],
        )

    async def test_qwen_providers_map_to_customvoice_and_base_modes(self):
        calls = []

        async def synthesize(**kwargs):
            calls.append(kwargs)
            Path(kwargs["output_path"]).write_bytes(b"audio")

        fake_module = SimpleNamespace(synthesize=synthesize, list_speakers=lambda: [{"id": "Vivian"}])
        config = {
            "tts": {
                "customvoice_model_path": "custom-model",
                "base_model_path": "base-model",
                "device": "cpu",
            }
        }
        service = create_tts_service(config)

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            qwen3_tts, "_legacy_qwen_module", return_value=fake_module
        ):
            await service.synthesize(
                QWEN3_TTS_CUSTOM_VOICE_MODEL,
                TTSRequest(text="custom", voice_id="Vivian", instruct="warm"),
                Path(temp_dir) / "custom.wav",
            )
            reference = Path(temp_dir) / "reference.wav"
            reference.write_bytes(b"reference")
            await service.synthesize(
                QWEN3_TTS_BASE_MODEL,
                TTSRequest(text="base", reference_audio=reference, reference_text="reference text"),
                Path(temp_dir) / "base.wav",
            )

        self.assertEqual(calls[0]["mode"], "customvoice")
        self.assertEqual(calls[0]["model_path"], "custom-model")
        self.assertEqual(calls[1]["mode"], "base")
        self.assertEqual(calls[1]["model_path"], "base-model")
        self.assertEqual(calls[1]["ref_audio"], reference)


if __name__ == "__main__":
    unittest.main()
