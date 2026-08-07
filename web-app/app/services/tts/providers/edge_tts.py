from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

from app.services.tts.base import EDGE_TTS_MODEL, TTSRequest, TTSResult, TTSServiceError, TTSTiming

_LEGACY_EDGE_VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓", "gender": "female", "description": "温暖自然"},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊", "gender": "female", "description": "活泼明亮"},
    {"id": "zh-CN-XiaochenNeural", "name": "晓辰", "gender": "female", "description": "清晰专业"},
    {"id": "zh-CN-XiaohanNeural", "name": "晓涵", "gender": "female", "description": "柔和亲切"},
    {"id": "zh-CN-XiaomengNeural", "name": "晓梦", "gender": "female", "description": "轻快甜美"},
    {"id": "zh-CN-XiaomoNeural", "name": "晓墨", "gender": "female", "description": "成熟沉稳"},
    {"id": "zh-CN-XiaoxuanNeural", "name": "晓萱", "gender": "female", "description": "自然舒缓"},
    {"id": "zh-CN-XiaoyanNeural", "name": "晓颜", "gender": "female", "description": "清晰服务感"},
    {"id": "zh-CN-YunxiNeural", "name": "云希", "gender": "male", "description": "年轻自然"},
    {"id": "zh-CN-YunjianNeural", "name": "云健", "gender": "male", "description": "稳重有力"},
    {"id": "zh-CN-YunfengNeural", "name": "云枫", "gender": "male", "description": "清晰专业"},
    {"id": "zh-CN-YunhaoNeural", "name": "云皓", "gender": "male", "description": "广告表现力"},
    {"id": "zh-CN-YunyeNeural", "name": "云野", "gender": "male", "description": "纪录片质感"},
]

EDGE_VOICE_CATALOG_PATH = Path(__file__).resolve().parents[4] / "data" / "edge_tts_voices.json"
EDGE_CHINESE_NAMES = {
    "zh-CN-XiaoxiaoNeural": "晓晓",
    "zh-CN-XiaoyiNeural": "晓伊",
    "zh-CN-YunjianNeural": "云健",
    "zh-CN-YunxiNeural": "云希",
    "zh-CN-YunxiaNeural": "云夏",
    "zh-CN-YunyangNeural": "云扬",
    "zh-CN-liaoning-XiaobeiNeural": "晓北（辽宁）",
    "zh-CN-shaanxi-XiaoniNeural": "晓妮（陕西）",
    "zh-HK-HiuGaaiNeural": "晓佳（香港）",
    "zh-HK-HiuMaanNeural": "晓曼（香港）",
    "zh-HK-WanLungNeural": "云龙（香港）",
    "zh-TW-HsiaoChenNeural": "晓臻（台湾）",
    "zh-TW-YunJheNeural": "云哲（台湾）",
    "zh-TW-HsiaoYuNeural": "晓雨（台湾）",
}
EDGE_CHINESE_DESCRIPTIONS = {
    "zh-CN-XiaoxiaoNeural": "温暖自然",
    "zh-CN-XiaoyiNeural": "活泼明亮",
    "zh-CN-YunjianNeural": "沉稳有力",
    "zh-CN-YunxiNeural": "年轻自然",
    "zh-CN-YunxiaNeural": "亲切柔和",
    "zh-CN-YunyangNeural": "清晰阳光",
    "zh-CN-liaoning-XiaobeiNeural": "东北口音，爽朗自然",
    "zh-CN-shaanxi-XiaoniNeural": "陕西口音，亲切自然",
    "zh-HK-HiuGaaiNeural": "粤语女声，明快自然",
    "zh-HK-HiuMaanNeural": "粤语女声，温柔亲和",
    "zh-HK-WanLungNeural": "粤语男声，稳重清晰",
    "zh-TW-HsiaoChenNeural": "台湾女声，温柔自然",
    "zh-TW-YunJheNeural": "台湾男声，沉稳清晰",
    "zh-TW-HsiaoYuNeural": "台湾女声，轻柔亲切",
}
EDGE_CHINESE_REGION_ORDER = {
    "zh-CN-liaoning-XiaobeiNeural": 1,
    "zh-CN-shaanxi-XiaoniNeural": 2,
    "zh-TW-HsiaoChenNeural": 3,
    "zh-TW-YunJheNeural": 3,
    "zh-TW-HsiaoYuNeural": 3,
    "zh-HK-HiuGaaiNeural": 4,
    "zh-HK-HiuMaanNeural": 4,
    "zh-HK-WanLungNeural": 4,
}


def _load_edge_voice_catalog() -> list[dict]:
    """Load voices successfully probed by scripts/check_edge_tts_voices.py."""
    if EDGE_VOICE_CATALOG_PATH.is_file():
        try:
            payload = json.loads(EDGE_VOICE_CATALOG_PATH.read_text(encoding="utf-8"))
            voices = payload.get("voices", payload) if isinstance(payload, (dict, list)) else []
            if isinstance(voices, list):
                selected_voices = [
                    {
                        **voice,
                        "name": EDGE_CHINESE_NAMES.get(voice["id"], voice.get("name") or voice["id"]),
                        "description": EDGE_CHINESE_DESCRIPTIONS.get(voice["id"], "中文在线音色"),
                        "language": "zh-CN",
                        "language_label": "中文",
                    }
                    for voice in voices
                    if isinstance(voice, dict)
                    and voice.get("id") in EDGE_CHINESE_NAMES
                    and voice.get("available") is True
                ]
                return sorted(
                    selected_voices,
                    key=lambda voice: (
                        1 if voice["id"] in EDGE_CHINESE_REGION_ORDER else 0,
                        EDGE_CHINESE_REGION_ORDER.get(voice["id"], 0),
                        voice["name"],
                    ),
                )
        except (OSError, TypeError, ValueError):
            pass
    return []


def _percent(value: float) -> str:
    rounded = round(value)
    return f"{rounded:+d}%"


def _probe_duration(path: Path) -> float:
    if shutil.which("ffprobe") is None:
        return 0.0
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return 0.0
    try:
        return max(0.0, float(result.stdout.strip()))
    except ValueError:
        return 0.0


class EdgeTtsProvider:
    provider_id = "edge_tts"
    model_name = EDGE_TTS_MODEL
    capabilities = frozenset({"preset_voice", "speed", "volume"})

    def __init__(self, *, default_voice: str = "zh-CN-XiaoxiaoNeural"):
        self.default_voice = default_voice

    def status(self, *, refresh: bool = False) -> dict:
        return {
            "id": self.provider_id,
            "model_name": self.model_name,
            "display_name": "预设音色",
            "runtime": "cloud",
            "enabled": True,
            "available": True,
            "status": "available",
            "reason": None,
            "validation": "static",
            "checks": {"configuration": "passed", "network": "skipped"},
        }

    def list_voices(self) -> list[dict]:
        return [{**voice, "model_name": self.model_name} for voice in _load_edge_voice_catalog()]

    async def synthesize(self, request: TTSRequest, output_path: Path) -> TTSResult:
        text = request.text.strip()
        if not text:
            raise TTSServiceError("TTS 文本不能为空")
        voice_id = request.voice_id or self.default_voice
        if voice_id not in {voice["id"] for voice in _load_edge_voice_catalog()}:
            raise TTSServiceError(f"Edge-TTS 不支持音色：{voice_id}")

        try:
            import edge_tts
        except ImportError as exc:
            raise TTSServiceError("Edge-TTS 未安装，请安装 edge-tts 依赖") from exc

        speed = max(0.5, min(2.0, float(request.speed)))
        volume = max(0, min(100, int(request.volume)))
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            communicator = edge_tts.Communicate(
                text,
                voice_id,
                rate=_percent((speed - 1.0) * 100),
                volume=_percent(volume - 100),
            )
            timings: list[TTSTiming] = []
            with output_path.open("wb") as audio_file:
                async for chunk in communicator.stream():
                    if chunk["type"] == "audio":
                        audio_file.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        start = max(0.0, float(chunk.get("offset") or 0) / 10_000_000)
                        duration = max(0.0, float(chunk.get("duration") or 0) / 10_000_000)
                        timings.append(
                            TTSTiming(
                                text=str(chunk.get("text") or ""),
                                start=start,
                                end=start + duration,
                            )
                        )
        except Exception as exc:
            raise TTSServiceError(f"Edge-TTS 生成失败：{exc}") from exc

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise TTSServiceError("Edge-TTS 未生成有效音频文件")

        duration = await asyncio.to_thread(_probe_duration, output_path)
        return TTSResult(
            output_path=output_path,
            duration=duration,
            model_name=self.model_name,
            voice_id=voice_id,
            timings=tuple(timings),
        )
