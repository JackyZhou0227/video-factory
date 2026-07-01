from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from services import tts_qwen, runninghub, voice_profiles

router = APIRouter()

# In-memory task store: task_id -> task state dict
_tasks: dict[str, dict] = {}


def _get_config():
    """Import config lazily to avoid circular imports."""
    from main import app_config
    return app_config


def _output_root(cfg: dict) -> Path:
    from main import ROOT

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
        return tts_cfg.get("base_model_path") or tts_cfg.get("model_path") or ""
    return tts_cfg.get("customvoice_model_path") or tts_cfg.get("model_path") or ""


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


def _new_preview_audio_path() -> tuple[str, Path, Path]:
    cfg = _get_config()
    output_root = _output_root(cfg)
    audio_id = uuid.uuid4().hex
    audio_dir = output_root / "tts" / audio_id
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_id, audio_dir, audio_dir / "preview.wav"


# ---------------------------------------------------------------------------
# POST /tts/customvoice/preview
# ---------------------------------------------------------------------------

@router.post("/tts/customvoice/preview")
async def preview_customvoice_tts(
    text: str = Form(...),
    speaker: str = Form("Uncle_Fu"),
    language: str = Form("Chinese"),
    instruct: Optional[str] = Form(None),
):
    """Generate preview audio with Qwen3-TTS CustomVoice."""
    if not text.strip():
        raise HTTPException(status_code=422, detail="text is required")
    if tts_qwen.get_speaker(speaker) is None:
        raise HTTPException(status_code=422, detail=f"Unsupported speaker: {speaker}")

    cfg = _get_config()
    audio_id, _, audio_path = _new_preview_audio_path()

    await tts_qwen.synthesize(
        text=text.strip(),
        output_path=audio_path,
        model_path=_tts_model_path(cfg, "customvoice"),
        device=cfg["tts"]["device"],
        mode="customvoice",
        speaker=speaker,
        language=language,
        instruct=instruct.strip() if instruct and instruct.strip() else None,
    )

    return {
        "audio_id": audio_id,
        "audio_url": _public_output_url(audio_path),
        "tts_mode": "customvoice",
        "speaker": speaker,
        "language": language,
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

    await tts_qwen.synthesize(
        text=text.strip(),
        output_path=audio_path,
        model_path=_tts_model_path(cfg, "base"),
        device=cfg["tts"]["device"],
        mode="base",
        language=language,
        ref_audio=resolved_ref_audio,
        ref_text=resolved_ref_text,
    )

    return {
        "audio_id": audio_id,
        "audio_url": _public_output_url(audio_path),
        "tts_mode": "base",
        "voice_profile_id": voice_profile_id,
        "language": language,
    }


# ---------------------------------------------------------------------------
# POST /generate-video
# ---------------------------------------------------------------------------
@router.post("/generate-video")
async def generate_video(
    image: UploadFile = File(...),
    mode: str = Form("preview"),  # "preview" | "audio"
    audio_url: Optional[str] = Form(None),
    audio: Optional[UploadFile] = File(None),
):
    """Generate video from confirmed audio and character image."""
    if mode not in ("preview", "audio"):
        raise HTTPException(status_code=422, detail="mode must be 'preview' or 'audio'")
    if mode == "preview" and not audio_url:
        raise HTTPException(status_code=422, detail="audio_url is required in preview mode")
    if mode == "audio" and audio is None:
        raise HTTPException(status_code=422, detail="audio file is required in audio mode")

    cfg = _get_config()
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
        "status": "pending",
        "progress": 0,
        "message": "任务已创建，等待提交 RunningHub...",
        "video_url": None,
        "error": None,
    }

    asyncio.create_task(
        _run_video_generation(
            task_id=task_id,
            task_dir=task_dir,
            image_path=image_path,
            audio_path=audio_path,
            cfg=cfg,
        )
    )

    return {"task_id": task_id}


# ---------------------------------------------------------------------------
# GET /task/{task_id}
# ---------------------------------------------------------------------------

@router.get("/task/{task_id}")
def get_task(task_id: str):
    task = _tasks.get(task_id)
    if task is None:
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
    cfg: dict,
):
    def _update(status: str, progress: int, message: str):
        _tasks[task_id].update(status=status, progress=progress, message=message)

    try:
        _update("running", 55, "音频已确认，正在提交 RunningHub 数字人工作流...")

        video_path = task_dir / "final.mp4"
        await runninghub.generate_digital_human(
            image_path=image_path,
            audio_path=audio_path,
            output_path=video_path,
            workflow_id=cfg["workflow"]["digital_human_id"],
            api_key=cfg["runninghub"]["api_key"],
            instance_type=cfg["runninghub"].get("instance_type"),
        )

        _tasks[task_id].update(
            status="completed",
            progress=100,
            message="生成完成。",
            video_url=f"/output/{task_id}/final.mp4",
        )

    except Exception as exc:
        _tasks[task_id].update(
            status="failed",
            progress=0,
            message=f"生成失败：{exc}",
            error=str(exc),
        )
