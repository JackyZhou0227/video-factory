from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

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

LANGUAGE_LABELS = {item["id"]: item["label"] for item in SUPPORTED_LANGUAGES}

# 9 built-in speakers for Qwen3-TTS-CustomVoice.
# The model can speak all languages in SUPPORTED_LANGUAGES, while native_language
# is the recommended language from the official model README.
SPEAKERS = [
    {
        "id": "Vivian",
        "name": "Vivian",
        "label": "薇薇安",
        "display_name": "薇薇安 Vivian",
        "native_language": "Chinese",
        "native_language_label": "中文",
        "short_description": "明亮年轻女声，清晰有精神。",
        "description": "明亮、略带锋芒的年轻女声，适合清晰、有精神的口播。",
    },
    {
        "id": "Serena",
        "name": "Serena",
        "label": "赛琳娜",
        "display_name": "赛琳娜 Serena",
        "native_language": "Chinese",
        "native_language_label": "中文",
        "short_description": "温柔年轻女声，亲和舒缓。",
        "description": "温暖、柔和的年轻女声，适合亲和、舒缓的表达。",
    },
    {
        "id": "Uncle_Fu",
        "name": "Uncle Fu",
        "label": "傅叔",
        "display_name": "傅叔 Uncle Fu",
        "native_language": "Chinese",
        "native_language_label": "中文",
        "short_description": "低醇成熟男声，稳重可信。",
        "description": "成熟稳重的低醇男声，厚实、有信任感，适合知识、财经和讲解类内容。",
    },
    {
        "id": "Dylan",
        "name": "Dylan",
        "label": "迪伦",
        "display_name": "迪伦 Dylan",
        "native_language": "Chinese",
        "native_language_label": "中文（北京口音）",
        "short_description": "清朗北京男声，自然生活感。",
        "description": "年轻清朗的北京男声，自然干净，适合轻松、有生活感的口播。",
    },
    {
        "id": "Eric",
        "name": "Eric",
        "label": "艾瑞克",
        "display_name": "艾瑞克 Eric",
        "native_language": "Chinese",
        "native_language_label": "中文（四川口音）",
        "short_description": "活泼成都男声，明亮略沙哑。",
        "description": "活泼的成都男声，略带沙哑和明亮感，适合接地气、节奏轻快的内容。",
    },
    {
        "id": "Ryan",
        "name": "Ryan",
        "label": "瑞安",
        "display_name": "瑞安 Ryan",
        "native_language": "English",
        "native_language_label": "英语",
        "short_description": "动感英文男声，节奏强。",
        "description": "富有动感的男声，节奏驱动力强，适合英文宣传、解说和高能内容。",
    },
    {
        "id": "Aiden",
        "name": "Aiden",
        "label": "艾登",
        "display_name": "艾登 Aiden",
        "native_language": "English",
        "native_language_label": "英语（美式）",
        "short_description": "阳光美式男声，清晰自然。",
        "description": "阳光清晰的美式男声，中频明朗，适合自然可信的英文口播。",
    },
    {
        "id": "Ono_Anna",
        "name": "Ono Anna",
        "label": "小野安娜",
        "display_name": "小野安娜 Ono Anna",
        "native_language": "Japanese",
        "native_language_label": "日语",
        "short_description": "轻盈日文女声，俏皮灵动。",
        "description": "俏皮轻盈的日文女声，灵动、轻快，适合活泼的角色或短视频内容。",
    },
    {
        "id": "Sohee",
        "name": "Sohee",
        "label": "昭熙",
        "display_name": "昭熙 Sohee",
        "native_language": "Korean",
        "native_language_label": "韩语",
        "short_description": "温暖韩文女声，情绪丰富。",
        "description": "温暖且情绪丰富的韩文女声，适合柔和、叙事和情感类表达。",
    },
]

_model = None
_model_lock = asyncio.Lock()


def list_speakers() -> list[dict]:
    return [
        {
            **speaker,
            "supported_languages": SUPPORTED_LANGUAGES,
            "supported_language_labels": "、".join(item["label"] for item in SUPPORTED_LANGUAGES),
            "supported_language_summary": f"{len(SUPPORTED_LANGUAGES)} 种语言",
        }
        for speaker in SPEAKERS
    ]


def list_languages() -> list[dict]:
    return SUPPORTED_LANGUAGES


def get_speaker(speaker_id: str) -> Optional[dict]:
    return next((speaker for speaker in SPEAKERS if speaker["id"] == speaker_id), None)


async def _load_model(model_path: str, device: str):
    """Lazy-load Qwen3-TTS model (loaded once, kept in memory)."""
    global _model
    async with _model_lock:
        if _model is not None:
            return _model
        import torch
        from qwen_tts import Qwen3TTSModel

        dtype = torch.bfloat16
        _model = Qwen3TTSModel.from_pretrained(
            model_path,
            device_map=device,
            dtype=dtype,
        )
        return _model


async def synthesize(
    text: str,
    output_path: Path,
    model_path: str,
    device: str,
    speaker: str = "Uncle_Fu",
    language: str = "Chinese",
    instruct: Optional[str] = None,
) -> Path:
    """
    Generate speech and write to output_path (.wav).
    Runs model inference in a thread executor to avoid blocking the event loop.
    """
    model = await _load_model(model_path, device)

    loop = asyncio.get_event_loop()

    def _infer():
        kwargs = {"text": text, "language": language, "speaker": speaker}
        if instruct:
            kwargs["instruct"] = instruct
        wavs, sr = model.generate_custom_voice(**kwargs)
        return wavs[0], sr

    wav, sr = await loop.run_in_executor(None, _infer)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), wav, sr)
    return output_path
