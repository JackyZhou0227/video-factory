from __future__ import annotations

import asyncio
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

    def test_edge_provider_status_is_static_without_network_detection(self):
        service = create_tts_service({"tts": {}})

        status = service.provider_status(EDGE_TTS_MODEL)

        self.assertEqual(status["status"], "available")
        self.assertEqual(status["validation"], "static")
        self.assertEqual(status["checks"]["network"], "skipped")

    def test_startup_prewarm_skips_static_edge_provider(self):
        service = create_tts_service({
            "tts": {
                "qwen3_tts_base": {
                    "enabled": True,
                    "model_path": "",
                    "device": "cpu",
                }
            }
        })
        edge_provider = service.get_provider(EDGE_TTS_MODEL)
        qwen_provider = service.get_provider(QWEN3_TTS_BASE_MODEL)

        with patch.object(edge_provider, "status", wraps=edge_provider.status) as edge_status, patch.object(
            qwen_provider, "status", wraps=qwen_provider.status
        ) as qwen_status:
            service.prewarm_provider_statuses()

        edge_status.assert_not_called()
        qwen_status.assert_called_once_with(refresh=True)

    async def test_qwen_base_provider_maps_to_voice_clone_mode(self):
        calls = []

        async def synthesize(**kwargs):
            calls.append(kwargs)
            Path(kwargs["output_path"]).write_bytes(b"audio")

        fake_module = SimpleNamespace(synthesize=synthesize)
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "base-model"
            model_path.mkdir()
            (model_path / "config.json").write_text(
                '{"architectures":["Qwen3TTSForConditionalGeneration"],"model_type":"qwen3_tts","tts_model_type":"base"}',
                encoding="utf-8",
            )
            (model_path / "model.safetensors").write_bytes(b"weights")
            config = {
                "tts": {
                    "qwen3_tts_base": {
                        "enabled": True,
                        "model_path": str(model_path),
                        "device": "cpu",
                    }
                }
            }
            service = create_tts_service(config)
            reference = Path(temp_dir) / "reference.wav"
            reference.write_bytes(b"reference")
            with patch.object(qwen3_tts, "_missing_dependencies", return_value=[]), patch.object(
                qwen3_tts, "_runtime_validation_error", return_value=None
            ), patch.object(qwen3_tts, "_legacy_qwen_module", return_value=fake_module):
                await service.synthesize(
                    QWEN3_TTS_BASE_MODEL,
                    TTSRequest(text="base", reference_audio=reference, reference_text="reference text"),
                    Path(temp_dir) / "base.wav",
                )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model_path"], str(model_path.resolve()))
        self.assertEqual(calls[0]["ref_audio"], reference)
        self.assertEqual(calls[0]["ref_text"], "reference text")

    def test_qwen_provider_reads_concurrent_limit_from_config(self):
        service = create_tts_service(
            {
                "tts": {
                    "qwen3_tts_base": {
                        "enabled": False,
                        "concurrent_limit": 3,
                    }
                }
            }
        )

        provider = service.get_provider(QWEN3_TTS_BASE_MODEL)

        self.assertEqual(provider.concurrent_limit, 3)

    async def test_qwen_provider_limits_inference_concurrency(self):
        active = 0
        peak = 0
        release = asyncio.Event()

        async def synthesize(**_kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await release.wait()
            active -= 1

        fake_module = SimpleNamespace(synthesize=synthesize)
        service = create_tts_service(
            {
                "tts": {
                    "qwen3_tts_base": {
                        "enabled": False,
                        "concurrent_limit": 2,
                    }
                }
            }
        )
        provider = service.get_provider(QWEN3_TTS_BASE_MODEL)
        request = TTSRequest(
            text="text",
            reference_audio=Path("reference.wav"),
            reference_text="reference text",
        )

        with patch.object(provider, "status", return_value={"available": True}), patch.object(
            qwen3_tts, "_legacy_qwen_module", return_value=fake_module
        ), patch.object(qwen3_tts, "_probe_duration", return_value=0.0):
            tasks = [
                asyncio.create_task(provider.synthesize(request, Path(f"output-{index}.wav")))
                for index in range(3)
            ]
            try:
                await asyncio.sleep(0)
                await asyncio.sleep(0.05)
                self.assertEqual(active, 2)
                self.assertEqual(peak, 2)
            finally:
                release.set()
                await asyncio.gather(*tasks, return_exceptions=True)

    def test_disabled_qwen_provider_skips_all_local_checks(self):
        service = create_tts_service(
            {
                "tts": {
                    "qwen3_tts_base": {
                        "enabled": False,
                        "model_path": "missing-model",
                        "device": "cuda",
                    }
                }
            }
        )

        with patch.object(qwen3_tts, "_missing_dependencies") as dependencies, patch.object(
            qwen3_tts, "_runtime_validation_error"
        ) as runtime_check:
            status = service.provider_status(QWEN3_TTS_BASE_MODEL)

        self.assertEqual(status["status"], "disabled")
        self.assertFalse(status["enabled"])
        self.assertFalse(status["available"])
        dependencies.assert_not_called()
        runtime_check.assert_not_called()

    def test_enabled_qwen_provider_reports_missing_model_path(self):
        service = create_tts_service(
            {"tts": {"qwen3_tts_base": {"enabled": True, "model_path": "", "device": "cpu"}}}
        )

        status = service.provider_status(QWEN3_TTS_BASE_MODEL)

        self.assertEqual(status["status"], "unavailable")
        self.assertEqual(status["checks"]["model_path"], "failed")
        self.assertIn("未配置", status["reason"])

    def test_qwen_provider_accepts_indexed_cuda_device(self):
        self.assertTrue(qwen3_tts._is_supported_device("cuda:0"))
        self.assertTrue(qwen3_tts._is_supported_device("cuda:12"))
        self.assertFalse(qwen3_tts._is_supported_device("cuda:gpu"))

    def test_qwen_provider_rejects_non_base_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir)
            (model_path / "config.json").write_text(
                '{"architectures":["Qwen3TTSForConditionalGeneration"],"model_type":"qwen3_tts","tts_model_type":"custom_voice"}',
                encoding="utf-8",
            )
            (model_path / "model.safetensors").write_bytes(b"weights")
            service = create_tts_service(
                {
                    "tts": {
                        "qwen3_tts_base": {
                            "enabled": True,
                            "model_path": str(model_path),
                            "device": "cpu",
                        }
                    }
                }
            )

            status = service.provider_status(QWEN3_TTS_BASE_MODEL)

        self.assertEqual(status["status"], "unavailable")
        self.assertEqual(status["checks"]["model_config"], "failed")
        self.assertIn("不是支持音色克隆", status["reason"])

    def test_runtime_validation_explains_duplicate_openmp_runtime(self):
        result = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="OMP: Error #15: libiomp5md.dll already initialized.",
        )
        with patch.object(qwen3_tts.subprocess, "run", return_value=result):
            error = qwen3_tts._runtime_validation_error("cpu")

        self.assertIn("OpenMP 运行库冲突", error)

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
