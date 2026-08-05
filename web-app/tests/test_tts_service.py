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
    TTSRequest,
    create_tts_service,
)
from app.services.tts.providers import edge_tts, qwen3_tts


class TTSServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_edge_listing_does_not_load_legacy_qwen_module(self):
        sys.modules.pop("app.services.tts_qwen", None)
        service = create_tts_service({"tts": {}})
        voices = service.list_voices(EDGE_TTS_MODEL)
        self.assertGreater(len(voices), 5)
        self.assertNotIn("app.services.tts_qwen", sys.modules)
        self.assertEqual(
            service.model_names(),
            [EDGE_TTS_MODEL, QWEN3_TTS_BASE_MODEL],
        )

    async def test_qwen_base_provider_maps_to_voice_clone_mode(self):
        calls = []

        async def synthesize(**kwargs):
            calls.append(kwargs)
            Path(kwargs["output_path"]).write_bytes(b"audio")

        fake_module = SimpleNamespace(synthesize=synthesize)
        config = {
            "tts": {
                "base_model_path": "base-model",
                "device": "cpu",
            }
        }
        service = create_tts_service(config)

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            qwen3_tts, "_legacy_qwen_module", return_value=fake_module
        ):
            reference = Path(temp_dir) / "reference.wav"
            reference.write_bytes(b"reference")
            await service.synthesize(
                QWEN3_TTS_BASE_MODEL,
                TTSRequest(text="base", reference_audio=reference, reference_text="reference text"),
                Path(temp_dir) / "base.wav",
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model_path"], "base-model")
        self.assertEqual(calls[0]["ref_audio"], reference)
        self.assertEqual(calls[0]["ref_text"], "reference text")

    async def test_edge_provider_collects_word_boundaries(self):
        class FakeCommunicate:
            def __init__(self, *_args, **_kwargs):
                pass

            async def stream(self):
                yield {"type": "audio", "data": b"audio"}
                yield {"type": "WordBoundary", "text": "湖北", "offset": 10_000_000, "duration": 5_000_000}

        fake_module = SimpleNamespace(Communicate=FakeCommunicate)
        service = create_tts_service({"tts": {}})
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(sys.modules, {"edge_tts": fake_module}), patch.object(
            edge_tts, "_probe_duration", return_value=2.0
        ):
            result = await service.synthesize(
                EDGE_TTS_MODEL,
                TTSRequest(text="湖北"),
                Path(temp_dir) / "edge.mp3",
            )

        self.assertEqual(result.duration, 2.0)
        self.assertEqual(len(result.timings), 1)
        self.assertEqual(result.timings[0].text, "湖北")
        self.assertEqual(result.timings[0].start, 1.0)
        self.assertEqual(result.timings[0].end, 1.5)


if __name__ == "__main__":
    unittest.main()
