from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

from app.services.tts.base import EDGE_TTS_MODEL, TTSRequest, TTSResult, TTSServiceError

EDGE_VOICES = [
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
    model_name = EDGE_TTS_MODEL
    capabilities = frozenset({"preset_voice", "speed", "volume"})

    def __init__(self, *, default_voice: str = "zh-CN-XiaoxiaoNeural"):
        self.default_voice = default_voice

    def list_voices(self) -> list[dict]:
        return [{**voice, "model_name": self.model_name} for voice in EDGE_VOICES]

    async def synthesize(self, request: TTSRequest, output_path: Path) -> TTSResult:
        text = request.text.strip()
        if not text:
            raise TTSServiceError("TTS 文本不能为空")
        voice_id = request.voice_id or self.default_voice
        if voice_id not in {voice["id"] for voice in EDGE_VOICES}:
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
            await communicator.save(str(output_path))
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
        )
