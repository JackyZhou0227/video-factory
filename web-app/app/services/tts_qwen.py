from __future__ import annotations

import asyncio
from pathlib import Path

import soundfile as sf

SUPPORTED_LANGUAGES = [
    {"id": "Chinese", "label": "中文"},
    {"id": "English", "label": "英语"},
    {"id": "Japanese", "label": "日语"},
    {"id": "Korean", "label": "韩语"},
    {"id": "German", "label": "德语"},
    {"id": "French", "label": "法语"},
    {"id": "Russian", "label": "俄语"},
    {"id": "Portuguese", "label": "葡萄牙语"},
    {"id": "Spanish", "label": "西班牙语"},
    {"id": "Italian", "label": "意大利语"},
]

_model_cache: dict[tuple[str, str], object] = {}
_model_lock = asyncio.Lock()


def list_languages() -> list[dict]:
    return SUPPORTED_LANGUAGES


async def _load_model(model_path: str, device: str):
    """Lazy-load the Qwen3-TTS Base model, cached by path and device."""
    cache_key = (str(Path(model_path).resolve()), device)
    async with _model_lock:
        if cache_key in _model_cache:
            return _model_cache[cache_key]
        import torch
        from qwen_tts import Qwen3TTSModel

        model = Qwen3TTSModel.from_pretrained(
            model_path,
            device_map=device,
            dtype=torch.bfloat16,
        )
        _model_cache[cache_key] = model
        return model


async def synthesize(
    text: str,
    output_path: Path,
    model_path: str,
    device: str,
    language: str = "Chinese",
    ref_audio: Path | None = None,
    ref_text: str | None = None,
) -> Path:
    """Clone a voice with Qwen3-TTS Base and write a WAV file."""
    if ref_audio is None:
        raise ValueError("ref_audio is required for base voice clone mode")
    if not ref_text or not ref_text.strip():
        raise ValueError("ref_text is required for base voice clone mode")

    model = await _load_model(model_path, device)
    loop = asyncio.get_event_loop()

    def _infer():
        wavs, sample_rate = model.generate_voice_clone(
            text=text,
            language=language,
            ref_audio=str(ref_audio),
            ref_text=ref_text.strip(),
        )
        return wavs[0], sample_rate

    wav, sample_rate = await loop.run_in_executor(None, _infer)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), wav, sample_rate)
    return output_path
