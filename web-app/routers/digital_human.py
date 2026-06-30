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
    speaker: str = Form("Uncle_Fu"),
    language: str = Form("Chinese"),
    instruct: Optional[str] = Form(None),
):
    """Generate local Qwen3-TTS audio and expose it for browser preview."""
    if not text.strip():
        raise HTTPException(status_code=422, detail="text is required")
    if tts_qwen.get_speaker(speaker) is None:
        raise HTTPException(status_code=422, detail=f"Unsupported speaker: {speaker}")

    cfg = _get_config()
    output_root = _output_root(cfg)
    audio_id = uuid.uuid4().hex
    audio_dir = output_root / "tts" / audio_id
    audio_path = audio_dir / "preview.wav"

    await tts_qwen.synthesize(
        text=text.strip(),
        output_path=audio_path,
        model_path=cfg["tts"]["model_path"],
        device=cfg["tts"]["device"],
        speaker=speaker,
        language=language,
        instruct=instruct.strip() if instruct and instruct.strip() else None,
    )

    return {
        "audio_id": audio_id,
        "audio_url": _public_output_url(audio_path),
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
    speaker: str = Form("Uncle_Fu"),
    language: str = Form("Chinese"),
    instruct: Optional[str] = Form(None),
):
    # --- Validate inputs ---
    if mode not in ("text", "audio"):
        raise HTTPException(status_code=422, detail="mode must be 'text' or 'audio'")
    if mode == "text" and not text:
        raise HTTPException(status_code=422, detail="text is required in text mode")
    if mode == "audio" and audio is None:
        raise HTTPException(status_code=422, detail="audio file is required in audio mode")

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

    if mode == "audio":
        audio_path = task_dir / f"input_audio{Path(audio.filename).suffix or '.wav'}"
        audio_path.write_bytes(await audio.read())

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
            speaker=speaker,
            language=language,
            instruct=instruct,
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
    speaker: str,
    language: str,
    instruct: Optional[str],
    cfg: dict,
):
    def _update(status: str, progress: int, message: str):
        _tasks[task_id].update(status=status, progress=progress, message=message)

    try:
        _update("running", 10, "开始处理…")

        if mode == "text":
            _update("running", 20, "正在生成语音（Qwen3-TTS）…")
            audio_path = task_dir / "narration.wav"
            await tts_qwen.synthesize(
                text=text or "",
                output_path=audio_path,
                model_path=cfg["tts"]["model_path"],
                device=cfg["tts"]["device"],
                speaker=speaker,
                language=language,
                instruct=instruct or None,
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
