from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.auth import require_current_user
from app.core.config import ROOT, app_config
from app.services import tts_qwen, runninghub, voice_profiles, settings_store
from app.services.llm import LLMConfig, LLMServiceError, llm_service

router = APIRouter(dependencies=[Depends(require_current_user)])

MIN_SPEECH_RATE = 0.8
NORMAL_SPEECH_RATE = 1.0
MAX_SPEECH_RATE = 1.5
RUNNINGHUB_TASKS_URL = "https://www.runninghub.cn/bill-task"
RUNNINGHUB_WORKS_URL = "https://www.runninghub.cn/user-center"

# In-memory task store: task_id -> task state dict
_tasks: dict[str, dict] = {}


class RunningHubSettingsUpdate(BaseModel):
    api_key: Optional[str] = Field(default=None)
    concurrent_limit: Optional[int] = Field(default=None, ge=1, le=10)
    instance_type: Optional[str] = Field(default=None)


class LLMSettingsUpdate(BaseModel):
    base_url: Optional[str] = Field(default=None, max_length=500)
    api_key: Optional[str] = Field(default=None, max_length=1000)
    model: Optional[str] = Field(default=None, max_length=200)
    clear_api_key: bool = False


class LLMSettingsTest(BaseModel):
    base_url: Optional[str] = Field(default=None, max_length=500)
    api_key: Optional[str] = Field(default=None, max_length=1000)
    model: Optional[str] = Field(default=None, max_length=200)


def _get_config():
    return app_config


def _output_root(cfg: dict) -> Path:
    output_root = Path(cfg["server"]["output_dir"])
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    output_root.mkdir(parents=True, exist_ok=True)
    return output_root


def _public_output_url(path: Path) -> str:
    cfg = _get_config()
    output_root = _output_root(cfg).resolve()
    relative_path = path.resolve().relative_to(output_root).as_posix()
    return f"/output/{relative_path}"


def _resolve_output_file(public_url: str) -> Path:
    if not public_url.startswith("/output/"):
        raise HTTPException(status_code=422, detail="audio_url must start with /output/")

    cfg = _get_config()
    output_root = _output_root(cfg).resolve()
    relative = public_url.removeprefix("/output/").lstrip("/")
    resolved = (output_root / relative).resolve()

    if output_root not in resolved.parents and resolved != output_root:
        raise HTTPException(status_code=422, detail="audio_url is outside output directory")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return resolved


def _tts_model_path(cfg: dict, tts_mode: str) -> str:
    tts_cfg = cfg["tts"]
    if tts_mode == "base":
        return tts_cfg.get("base_model_path") or ""
    return tts_cfg.get("customvoice_model_path") or tts_cfg.get("model_path") or ""


def _require_tts_model_path(cfg: dict, tts_mode: str) -> str:
    model_path = _tts_model_path(cfg, tts_mode)
    if model_path:
        return model_path

    if tts_mode == "base":
        raise HTTPException(
            status_code=422,
            detail=(
                "语音克隆需要配置 tts.base_model_path。当前后端只配置了 CustomVoice 模型，"
                "请切换到“预置音色”，或配置 Qwen3-TTS Base 模型路径后重启后端。"
            ),
        )

    raise HTTPException(
        status_code=422,
        detail="预置音色需要配置 tts.customvoice_model_path 或旧版 tts.model_path。",
    )


def _raise_tts_model_error(exc: ValueError, tts_mode: str):
    detail = str(exc)
    if tts_mode == "base" and "does not support generate_voice_clone" in detail:
        detail = (
            "当前后端加载的是 CustomVoice 模型，不支持语音克隆。"
            "请切换到“预置音色”，或在 config.yaml 中配置 tts.base_model_path 为 Qwen3-TTS Base 模型路径后重启后端。"
        )
    elif tts_mode == "customvoice" and "generate_custom_voice" in detail:
        detail = (
            "当前后端加载的模型不支持预置音色。"
            "请检查 config.yaml 中的 tts.customvoice_model_path 是否指向 Qwen3-TTS CustomVoice 模型。"
        )
    raise HTTPException(status_code=422, detail=detail) from None


def _resolve_base_voice_inputs(
    voice_profile_id: Optional[str],
    ref_audio: Optional[Path],
    ref_text: Optional[str],
) -> tuple[Optional[Path], Optional[str]]:
    if voice_profile_id:
        voice_profile = voice_profiles.get_voice_profile(voice_profile_id)
        if voice_profile is None:
            raise HTTPException(status_code=404, detail="Voice profile not found")
        return voice_profiles.get_voice_audio_path(voice_profile_id), voice_profile.get("ref_text")
    return ref_audio, ref_text


def _resolve_runninghub_inputs(
    user_id: str,
    api_key: Optional[str],
    instance_type: Optional[str],
) -> tuple[str, str, Optional[str]]:
    stored = settings_store.get_runninghub_settings(user_id)

    resolved_api_key = (api_key or stored["api_key"]).strip()
    resolved_workflow_id = settings_store.FIXED_DIGITAL_HUMAN_WORKFLOW_ID
    resolved_instance_type = instance_type
    if isinstance(resolved_instance_type, str):
        resolved_instance_type = resolved_instance_type.strip() or None
    if resolved_instance_type is None:
        resolved_instance_type = stored["instance_type"] or None

    if not resolved_api_key:
        raise HTTPException(status_code=422, detail="请先在设置页配置 RunningHub API Key")

    return resolved_api_key, resolved_workflow_id, resolved_instance_type


# ---------------------------------------------------------------------------
# GET/PUT /settings
# ---------------------------------------------------------------------------

@router.get("/settings")
def get_settings(user: dict = Depends(require_current_user)):
    return {
        "runninghub": settings_store.public_runninghub_settings(user=user, user_id=user["id"]),
        "llm": settings_store.public_llm_settings(user_id=user["id"]),
    }


@router.put("/settings/runninghub")
def update_runninghub_settings(payload: RunningHubSettingsUpdate, user: dict = Depends(require_current_user)):
    updated = settings_store.update_runninghub_settings(
        user_id=user["id"],
        api_key=payload.api_key,
        concurrent_limit=payload.concurrent_limit,
        instance_type=payload.instance_type,
    )
    return settings_store.public_runninghub_settings(updated, user=user, user_id=user["id"])


@router.put("/settings/llm")
def update_llm_settings(payload: LLMSettingsUpdate, user: dict = Depends(require_current_user)):
    updated = settings_store.update_llm_settings(
        user_id=user["id"],
        base_url=payload.base_url,
        api_key=payload.api_key,
        model=payload.model,
        clear_api_key=payload.clear_api_key,
    )
    return settings_store.public_llm_settings(updated, user_id=user["id"])


@router.post("/settings/llm/test")
async def test_llm_settings(payload: LLMSettingsTest, user: dict = Depends(require_current_user)):
    stored = settings_store.get_llm_settings(user["id"])
    config = LLMConfig(
        base_url=stored["base_url"] if payload.base_url is None else payload.base_url.strip(),
        api_key=stored["api_key"] if payload.api_key is None else payload.api_key.strip(),
        model=stored["model"] if payload.model is None else payload.model.strip(),
    )
    try:
        response = await llm_service.test_connection(config)
    except LLMServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"ok": True, "response": response[:100]}


# ---------------------------------------------------------------------------
# GET /speakers
# ---------------------------------------------------------------------------

@router.get("/speakers")
def get_speakers():
    """Return the list of available TTS speakers."""
    return tts_qwen.list_speakers()


@router.get("/tts/languages")
def get_tts_languages():
    """Return languages supported by the local Qwen3-TTS model."""
    return tts_qwen.list_languages()


@router.get("/voice-profiles")
def get_voice_profiles():
    return voice_profiles.list_voice_profiles()


@router.get("/voice-profiles/{voice_profile_id}/audio")
def get_voice_profile_audio(voice_profile_id: str):
    audio_path = voice_profiles.get_voice_audio_path(voice_profile_id)
    return FileResponse(audio_path)


@router.post("/voice-profiles")
async def create_voice_profile(
    name: str = Form(...),
    language: str = Form("Chinese"),
    ref_text: str = Form(...),
    ref_audio: UploadFile = File(...),
):
    voice = await voice_profiles.create_voice_profile(
        name=name,
        language=language,
        ref_text=ref_text,
        ref_audio=ref_audio,
    )
    return voice


@router.put("/voice-profiles/{voice_profile_id}")
async def update_voice_profile(
    voice_profile_id: str,
    name: str = Form(...),
    language: str = Form("Chinese"),
    ref_text: str = Form(...),
    ref_audio: Optional[UploadFile] = File(None),
):
    voice = await voice_profiles.update_voice_profile(
        voice_id=voice_profile_id,
        name=name,
        language=language,
        ref_text=ref_text,
        ref_audio=ref_audio,
    )
    return voice


@router.delete("/voice-profiles/{voice_profile_id}")
async def delete_voice_profile(voice_profile_id: str):
    await voice_profiles.delete_voice_profile(voice_profile_id)
    return {"deleted": True}


def _new_preview_audio_path() -> tuple[str, Path, Path]:
    cfg = _get_config()
    output_root = _output_root(cfg)
    audio_id = uuid.uuid4().hex
    audio_dir = output_root / "tts" / audio_id
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_id, audio_dir, audio_dir / "preview_original.wav"


def _normalize_speech_rate(speech_rate: float) -> float:
    try:
        rate = float(speech_rate)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="speech_rate must be a number") from None

    if rate < MIN_SPEECH_RATE or rate > MAX_SPEECH_RATE:
        raise HTTPException(
            status_code=422,
            detail=f"speech_rate must be between {MIN_SPEECH_RATE:.1f} and {MAX_SPEECH_RATE:.1f}",
        )
    return round(rate, 2)


def _create_speech_rate_variant(audio_path: Path, speech_rate: float) -> Path:
    rate = _normalize_speech_rate(speech_rate)
    if rate == NORMAL_SPEECH_RATE:
        return audio_path

    try:
        from pydub import AudioSegment
        from pydub.effects import speedup
    except ImportError:
        raise HTTPException(status_code=500, detail="pydub is required for speech speed adjustment") from None

    rate_label = f"{rate:.1f}".replace(".", "_")
    variant_path = audio_path.with_name(f"preview_{rate_label}x{audio_path.suffix}")
    temp_path = audio_path.with_name(f".{variant_path.stem}.tmp{audio_path.suffix}")

    if variant_path.exists():
        return variant_path

    audio = AudioSegment.from_wav(audio_path)

    if rate > NORMAL_SPEECH_RATE:
        audio_fast = speedup(audio, playback_speed=rate, chunk_size=50, crossfade=25)
        audio_fast.export(temp_path, format="wav")
    else:
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            try:
                subprocess.run(
                    [
                        ffmpeg_path,
                        "-y",
                        "-i",
                        str(audio_path),
                        "-filter:a",
                        f"atempo={rate:.2f}",
                        str(temp_path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as err:
                detail = err.stderr.strip() or err.stdout.strip() or "speech slowdown failed"
                raise HTTPException(status_code=500, detail=detail) from None
        else:
            slowed = audio._spawn(
                audio.raw_data,
                overrides={"frame_rate": max(1, int(audio.frame_rate * rate))},
            ).set_frame_rate(audio.frame_rate)
            slowed.export(temp_path, format="wav")

    temp_path.replace(variant_path)
    return variant_path


@router.post("/tts/preview/speech-rate")
async def update_preview_speech_rate(
    audio_url: str = Form(...),
    speech_rate: float = Form(1.0),
):
    """Create a speech-rate variant from an existing preview audio file."""
    audio_path = _resolve_output_file(audio_url)
    output_audio_path = _create_speech_rate_variant(audio_path, speech_rate)

    return {
        "audio_url": _public_output_url(output_audio_path),
        "processed_audio_url": _public_output_url(output_audio_path) if output_audio_path != audio_path else None,
        "speech_rate": _normalize_speech_rate(speech_rate),
    }


# ---------------------------------------------------------------------------
# POST /tts/customvoice/preview
# ---------------------------------------------------------------------------

@router.post("/tts/customvoice/preview")
async def preview_customvoice_tts(
    text: str = Form(...),
    speaker: str = Form("Uncle_Fu"),
    language: str = Form("Chinese"),
    instruct: Optional[str] = Form(None),
    speech_rate: float = Form(1.0),
):
    """Generate preview audio with Qwen3-TTS CustomVoice."""
    if not text.strip():
        raise HTTPException(status_code=422, detail="text is required")
    if tts_qwen.get_speaker(speaker) is None:
        raise HTTPException(status_code=422, detail=f"Unsupported speaker: {speaker}")

    cfg = _get_config()
    audio_id, _, audio_path = _new_preview_audio_path()

    try:
        await tts_qwen.synthesize(
            text=text.strip(),
            output_path=audio_path,
            model_path=_require_tts_model_path(cfg, "customvoice"),
            device=cfg["tts"]["device"],
            mode="customvoice",
            speaker=speaker,
            language=language,
            instruct=instruct.strip() if instruct and instruct.strip() else None,
        )
    except ValueError as exc:
        _raise_tts_model_error(exc, "customvoice")
    output_audio_path = _create_speech_rate_variant(audio_path, speech_rate)

    return {
        "audio_id": audio_id,
        "audio_url": _public_output_url(output_audio_path),
        "original_audio_url": _public_output_url(audio_path),
        "processed_audio_url": _public_output_url(output_audio_path) if output_audio_path != audio_path else None,
        "tts_mode": "customvoice",
        "speaker": speaker,
        "language": language,
        "speech_rate": _normalize_speech_rate(speech_rate),
    }


# ---------------------------------------------------------------------------
# POST /tts/voice-clone/preview
# ---------------------------------------------------------------------------

@router.post("/tts/voice-clone/preview")
async def preview_voice_clone_tts(
    text: str = Form(...),
    language: str = Form("Chinese"),
    voice_profile_id: Optional[str] = Form(None),
    ref_audio: Optional[UploadFile] = File(None),
    ref_text: Optional[str] = Form(None),
    speech_rate: float = Form(1.0),
):
    """Generate preview audio with Qwen3-TTS Base voice clone."""
    if not text.strip():
        raise HTTPException(status_code=422, detail="text is required")
    if not voice_profile_id and ref_audio is None:
        raise HTTPException(status_code=422, detail="ref_audio or voice_profile_id is required")
    if not voice_profile_id and not ref_text:
        raise HTTPException(status_code=422, detail="ref_text is required")

    cfg = _get_config()
    audio_id, audio_dir, audio_path = _new_preview_audio_path()

    ref_audio_path: Optional[Path] = None
    if ref_audio is not None:
        ref_audio_path = audio_dir / f"ref_audio{Path(ref_audio.filename).suffix or '.wav'}"
        ref_audio_path.write_bytes(await ref_audio.read())
    resolved_ref_audio, resolved_ref_text = _resolve_base_voice_inputs(voice_profile_id, ref_audio_path, ref_text)

    try:
        await tts_qwen.synthesize(
            text=text.strip(),
            output_path=audio_path,
            model_path=_require_tts_model_path(cfg, "base"),
            device=cfg["tts"]["device"],
            mode="base",
            language=language,
            ref_audio=resolved_ref_audio,
            ref_text=resolved_ref_text,
        )
    except ValueError as exc:
        _raise_tts_model_error(exc, "base")
    output_audio_path = _create_speech_rate_variant(audio_path, speech_rate)

    return {
        "audio_id": audio_id,
        "audio_url": _public_output_url(output_audio_path),
        "original_audio_url": _public_output_url(audio_path),
        "processed_audio_url": _public_output_url(output_audio_path) if output_audio_path != audio_path else None,
        "tts_mode": "base",
        "voice_profile_id": voice_profile_id,
        "language": language,
        "speech_rate": _normalize_speech_rate(speech_rate),
    }


# ---------------------------------------------------------------------------
# POST /generate-video
# ---------------------------------------------------------------------------
@router.post("/generate-video")
async def generate_video(
    user: dict = Depends(require_current_user),
    image: UploadFile = File(...),
    mode: str = Form("preview"),  # "preview" | "audio"
    audio_url: Optional[str] = Form(None),
    audio: Optional[UploadFile] = File(None),
    runninghub_api_key: Optional[str] = Form(None),
    runninghub_instance_type: Optional[str] = Form(None),
    runninghub_concurrent_limit: int = Form(1),
):
    """Generate video from confirmed audio and character image."""
    if mode not in ("preview", "audio"):
        raise HTTPException(status_code=422, detail="mode must be 'preview' or 'audio'")
    if mode == "preview" and not audio_url:
        raise HTTPException(status_code=422, detail="audio_url is required in preview mode")
    if mode == "audio" and audio is None:
        raise HTTPException(status_code=422, detail="audio file is required in audio mode")
    if runninghub_concurrent_limit < 1 or runninghub_concurrent_limit > 10:
        raise HTTPException(status_code=422, detail="runninghub_concurrent_limit must be between 1 and 10")

    cfg = _get_config()
    runninghub_api_key, runninghub_workflow_id, runninghub_instance_type = _resolve_runninghub_inputs(
        user_id=user["id"],
        api_key=runninghub_api_key,
        instance_type=runninghub_instance_type,
    )
    output_root = _output_root(cfg)

    task_id = uuid.uuid4().hex
    task_dir = output_root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    image_path = task_dir / f"character{Path(image.filename).suffix or '.jpg'}"
    image_path.write_bytes(await image.read())

    if mode == "preview":
        audio_path = _resolve_output_file(audio_url)
    else:
        audio_path = task_dir / f"input_audio{Path(audio.filename).suffix or '.wav'}"
        audio_path.write_bytes(await audio.read())

    _tasks[task_id] = {
        "user_id": user["id"],
        "status": "pending",
        "progress": 0,
        "message": "任务已创建，等待提交 RunningHub...",
        "video_url": None,
        "runninghub_task_id": None,
        "runninghub_task_url": RUNNINGHUB_TASKS_URL,
        "runninghub_works_url": RUNNINGHUB_WORKS_URL,
        "error": None,
    }

    asyncio.create_task(
        _run_video_generation(
            task_id=task_id,
            task_dir=task_dir,
            image_path=image_path,
            audio_path=audio_path,
            api_key=runninghub_api_key,
            workflow_id=runninghub_workflow_id,
            instance_type=runninghub_instance_type,
        )
    )

    return {"task_id": task_id}


# ---------------------------------------------------------------------------
# GET /task/{task_id}
# ---------------------------------------------------------------------------

@router.get("/task/{task_id}")
def get_task(task_id: str, user: dict = Depends(require_current_user)):
    task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------
async def _run_video_generation(
    task_id: str,
    task_dir: Path,
    image_path: Path,
    audio_path: Path,
    api_key: str,
    workflow_id: str,
    instance_type: Optional[str],
):
    def _update(status: str, progress: int, message: str):
        _tasks[task_id].update(status=status, progress=progress, message=message)

    try:
        _update("running", 55, "音频已确认，正在提交 RunningHub 数字人工作流...")

        runninghub_task_id = await runninghub.submit_digital_human(
            image_path=image_path,
            audio_path=audio_path,
            workflow_id=workflow_id,
            api_key=api_key,
            instance_type=instance_type,
        )

        _tasks[task_id].update(
            status="submitted",
            progress=100,
            message="RunningHub 任务已提交成功。生成通常需要较长时间，请到 RunningHub 查看进度和作品。",
            runninghub_task_id=runninghub_task_id,
            runninghub_task_url=RUNNINGHUB_TASKS_URL,
            runninghub_works_url=RUNNINGHUB_WORKS_URL,
        )

    except Exception as exc:
        _tasks[task_id].update(
            status="failed",
            progress=0,
            message=f"生成失败：{exc}",
            error=str(exc),
        )
