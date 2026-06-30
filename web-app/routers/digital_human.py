from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from services import tts_qwen, runninghub

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


# ---------------------------------------------------------------------------
# POST /tts/preview
# ---------------------------------------------------------------------------

@router.post("/tts/preview")
async def preview_tts(
    text: str = Form(...),
    tts_mode: str = Form("customvoice"),
    speaker: str = Form("Uncle_Fu"),
    language: str = Form("Chinese"),
    instruct: Optional[str] = Form(None),
    ref_audio: Optional[UploadFile] = File(None),
    ref_text: Optional[str] = Form(None),
):
    """Generate local Qwen3-TTS audio and expose it for browser preview."""
    if not text.strip():
        raise HTTPException(status_code=422, detail="text is required")
    if tts_mode == "customvoice" and tts_qwen.get_speaker(speaker) is None:
        raise HTTPException(status_code=422, detail=f"Unsupported speaker: {speaker}")
    if tts_mode == "base" and ref_audio is None:
        raise HTTPException(status_code=422, detail="ref_audio is required in base mode")
    if tts_mode == "base" and not ref_text:
        raise HTTPException(status_code=422, detail="ref_text is required in base mode")

    cfg = _get_config()
    output_root = _output_root(cfg)
    audio_id = uuid.uuid4().hex
    audio_dir = output_root / "tts" / audio_id
    audio_path = audio_dir / "preview.wav"

    ref_audio_path: Optional[Path] = None
    if ref_audio is not None:
        ref_audio_path = audio_dir / f"ref_audio{Path(ref_audio.filename).suffix or '.wav'}"
        ref_audio_path.write_bytes(await ref_audio.read())

    await tts_qwen.synthesize(
        text=text.strip(),
        output_path=audio_path,
        model_path=_tts_model_path(cfg, tts_mode),
        device=cfg["tts"]["device"],
        mode=tts_mode,
        speaker=speaker,
        language=language,
        instruct=instruct.strip() if instruct and instruct.strip() else None,
        ref_audio=ref_audio_path,
        ref_text=ref_text,
    )

    return {
        "audio_id": audio_id,
        "audio_url": _public_output_url(audio_path),
        "tts_mode": tts_mode,
        "speaker": speaker,
        "language": language,
    }


# ---------------------------------------------------------------------------
# POST /generate
# ---------------------------------------------------------------------------

@router.post("/generate")
async def generate(
    image: UploadFile = File(...),
    mode: str = Form(...),              # "text" | "audio"
    text: Optional[str] = Form(None),
    audio: Optional[UploadFile] = File(None),
    tts_mode: str = Form("customvoice"),
    speaker: str = Form("Uncle_Fu"),
    language: str = Form("Chinese"),
    instruct: Optional[str] = Form(None),
    ref_audio: Optional[UploadFile] = File(None),
    ref_text: Optional[str] = Form(None),
):
    # --- Validate inputs ---
    if mode not in ("text", "audio"):
        raise HTTPException(status_code=422, detail="mode must be 'text' or 'audio'")
    if mode == "text" and not text:
        raise HTTPException(status_code=422, detail="text is required in text mode")
    if mode == "audio" and audio is None:
        raise HTTPException(status_code=422, detail="audio file is required in audio mode")
    if mode == "text" and tts_mode == "base":
        if ref_audio is None:
            raise HTTPException(status_code=422, detail="ref_audio is required in base mode")
        if not ref_text:
            raise HTTPException(status_code=422, detail="ref_text is required in base mode")

    cfg = _get_config()
    output_root = Path(cfg["server"]["output_dir"])

    task_id = uuid.uuid4().hex
    task_dir = output_root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    # Save uploaded image
    image_path = task_dir / f"character{Path(image.filename).suffix or '.jpg'}"
    image_path.write_bytes(await image.read())

    # Prepare audio path placeholder
    audio_path: Optional[Path] = None
    ref_audio_path: Optional[Path] = None

    if mode == "audio":
        audio_path = task_dir / f"input_audio{Path(audio.filename).suffix or '.wav'}"
        audio_path.write_bytes(await audio.read())
    elif tts_mode == "base":
        ref_audio_path = task_dir / f"ref_audio{Path(ref_audio.filename).suffix or '.wav'}"
        ref_audio_path.write_bytes(await ref_audio.read())

    # Register task
    _tasks[task_id] = {
        "status": "pending",
        "progress": 0,
        "message": "任务已创建，等待处理…",
        "video_url": None,
        "error": None,
    }

    # Kick off background generation
    asyncio.create_task(
        _run_generation(
            task_id=task_id,
            task_dir=task_dir,
            image_path=image_path,
            audio_path=audio_path,
            mode=mode,
            text=text,
            tts_mode=tts_mode,
            speaker=speaker,
            language=language,
            instruct=instruct,
            ref_audio=ref_audio_path,
            ref_text=ref_text,
            cfg=cfg,
        )
    )

    return {"task_id": task_id}


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
        "message": "任务已创建，等待提交 RunningHub…",
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

async def _run_generation(
    task_id: str,
    task_dir: Path,
    image_path: Path,
    audio_path: Optional[Path],
    mode: str,
    text: Optional[str],
    tts_mode: str,
    speaker: str,
    language: str,
    instruct: Optional[str],
    ref_audio: Optional[Path],
    ref_text: Optional[str],
    cfg: dict,
):
    def _update(status: str, progress: int, message: str):
        _tasks[task_id].update(status=status, progress=progress, message=message)

    try:
        _update("running", 10, "开始处理…")

        if mode == "text":
            if tts_mode == "base":
                _update("running", 20, "正在使用 Base 模型克隆声音…")
            else:
                _update("running", 20, "正在生成语音（Qwen3-TTS）…")
            audio_path = task_dir / "narration.wav"
            await tts_qwen.synthesize(
                text=text or "",
                output_path=audio_path,
                model_path=_tts_model_path(cfg, tts_mode),
                device=cfg["tts"]["device"],
                mode=tts_mode,
                speaker=speaker,
                language=language,
                instruct=instruct or None,
                ref_audio=ref_audio,
                ref_text=ref_text,
            )
            _update("running", 55, "语音生成完成，提交数字人工作流…")
        else:
            _update("running", 55, "音频已就绪，提交数字人工作流…")

        if audio_path is None:
            raise RuntimeError("Audio file is missing.")

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
            message="生成完成！",
            video_url=f"/output/{task_id}/final.mp4",
        )

    except Exception as exc:
        _tasks[task_id].update(
            status="failed",
            progress=0,
            message=f"生成失败：{exc}",
            error=str(exc),
        )


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
        _update("running", 55, "音频已确认，正在提交 RunningHub 数字人工作流…")

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
            message="生成完成！",
            video_url=f"/output/{task_id}/final.mp4",
        )

    except Exception as exc:
        _tasks[task_id].update(
            status="failed",
            progress=0,
            message=f"生成失败：{exc}",
            error=str(exc),
        )
