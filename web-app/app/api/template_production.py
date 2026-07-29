from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.auth import require_current_user
from app.core.config import app_config, resolve_output_dir
from app.services import settings_store, template_production
from app.services.llm import LLMConfig, LLMMessage, LLMServiceError, llm_service
from app.services.tts import EDGE_TTS_MODEL, TTSRequest, tts_service

router = APIRouter(prefix="/template-production", tags=["template-production"])

MAX_GENERATE_COUNT = 50
MAX_MATERIAL_COUNT = 20
MAX_SUBTITLE_REPLACEMENTS = 30
MAX_SUBTITLE_TERM_LENGTH = 80
TEMPLATE_TTS_VOICE_ID = "zh-CN-YunjianNeural"
TEMPLATE_TTS_SPEED = 1.0
TEMPLATE_TTS_VOLUME = 100
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MATERIAL_RULES = {
    "zhongyi-xunfang": {
        "doctor-scene": ("video", 1, 5),
        "clinic-scene": ("video", 1, 3),
    },
    "doctor-intro": {
        "doctor-image": ("image", 1, 3),
        "hospital-scene": ("video", 1, 3),
    },
}

_tasks: dict[str, dict[str, Any]] = {}


class ScriptGenerateRequest(BaseModel):
    template_id: str
    variables: dict[str, str]
    count: int = Field(default=3, ge=1, le=10)
    material_context: dict[str, int] = Field(default_factory=dict)


class ScriptRewriteRequest(BaseModel):
    template_id: str
    variables: dict[str, str]
    original_script: str = Field(..., min_length=10, max_length=5000)
    material_context: dict[str, int] = Field(default_factory=dict)


def _public_output_url(path: Path) -> str:
    output_root = resolve_output_dir(app_config).resolve()
    relative = path.resolve().relative_to(output_root).as_posix()
    return f"/output/{relative}"


def _safe_filename(filename: str, fallback: str) -> str:
    value = Path(filename or fallback).name
    safe = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", value, flags=re.UNICODE).strip("._")
    return safe or fallback


def _parse_json_field(value: str, label: str, expected_type: type) -> Any:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"{label} 必须是有效 JSON") from exc
    if not isinstance(parsed, expected_type):
        raise HTTPException(status_code=422, detail=f"{label} 格式不正确")
    return parsed


def _parse_subtitle_replacements(value: str) -> list[dict[str, str]]:
    parsed = _parse_json_field(value or "[]", "subtitle_replacements", list)
    if len(parsed) > MAX_SUBTITLE_REPLACEMENTS:
        raise HTTPException(status_code=422, detail=f"字幕替换规则最多添加 {MAX_SUBTITLE_REPLACEMENTS} 条")

    replacements: list[dict[str, str]] = []
    seen_sources: set[str] = set()
    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail=f"第 {index} 条字幕替换规则格式不正确")
        source = str(item.get("source") or "").strip()
        replacement = str(item.get("replacement") or "").strip()
        if not source or not replacement:
            raise HTTPException(status_code=422, detail=f"第 {index} 条字幕替换规则需要填写原词和替换词")
        if "\n" in source or "\r" in source or "\n" in replacement or "\r" in replacement:
            raise HTTPException(status_code=422, detail=f"第 {index} 条字幕替换规则不能包含换行")
        if len(source) > MAX_SUBTITLE_TERM_LENGTH or len(replacement) > MAX_SUBTITLE_TERM_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"第 {index} 条字幕替换规则的词语长度不能超过 {MAX_SUBTITLE_TERM_LENGTH} 个字符",
            )
        if source == replacement:
            raise HTTPException(status_code=422, detail=f"第 {index} 条字幕替换规则的原词和替换词不能相同")
        if source in seen_sources:
            raise HTTPException(status_code=422, detail=f"字幕原词“{source}”重复添加")
        seen_sources.add(source)
        replacements.append({"source": source, "replacement": replacement})
    return replacements


def _validate_material_manifest(template_id: str, manifest: list[dict], file_count: int) -> None:
    rules = MATERIAL_RULES[template_id]
    counts = {key: 0 for key in rules}
    indexes: set[int] = set()
    for item in manifest:
        requirement_id = str(item.get("requirement_id") or "")
        if requirement_id not in rules:
            raise HTTPException(status_code=422, detail=f"未知的素材分组：{requirement_id}")
        try:
            file_index = int(item.get("file_index"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="素材清单缺少有效 file_index") from exc
        if file_index < 0 or file_index >= file_count or file_index in indexes:
            raise HTTPException(status_code=422, detail="素材清单中的 file_index 无效或重复")
        expected_type = rules[requirement_id][0]
        if item.get("media_type") != expected_type:
            raise HTTPException(status_code=422, detail=f"{requirement_id} 需要{expected_type}素材")
        indexes.add(file_index)
        counts[requirement_id] += 1

    if indexes != set(range(file_count)):
        raise HTTPException(status_code=422, detail="素材清单与上传文件数量不一致")
    for requirement_id, (_, minimum, maximum) in rules.items():
        count = counts[requirement_id]
        if count < minimum or count > maximum:
            raise HTTPException(
                status_code=422,
                detail=f"素材分组 {requirement_id} 需要 {minimum}-{maximum} 个文件，当前为 {count} 个",
            )


@router.post("/scripts/generate")
async def generate_scripts(payload: ScriptGenerateRequest, user: dict = Depends(require_current_user)):
    try:
        prompt = template_production.build_script_prompt(
            payload.template_id,
            payload.variables,
            payload.count,
            payload.material_context,
        )
    except template_production.TemplateProductionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    stored = settings_store.get_llm_settings(user["id"])
    config = LLMConfig(**stored)
    messages = [
        LLMMessage(role="system", content="你是专业、克制的中文短视频文案编导，必须严格遵守事实边界和输出格式。"),
        LLMMessage(role="user", content=prompt),
    ]
    try:
        content = await llm_service.generate(
            config,
            messages,
            temperature=0.75,
            max_tokens=2400,
        )
    except LLMServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    scripts = template_production.parse_generated_scripts(content, payload.count)
    if not scripts:
        raise HTTPException(status_code=502, detail="LLM 没有返回可用文案，请重试或手工添加")
    return {"scripts": scripts}


@router.post("/scripts/rewrite")
async def rewrite_script(payload: ScriptRewriteRequest, user: dict = Depends(require_current_user)):
    try:
        prompt = template_production.build_script_prompt(
            payload.template_id,
            payload.variables,
            1,
            payload.material_context,
        )
    except template_production.TemplateProductionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    rewrite_prompt = (
        f"{prompt}\n\n【单条重写要求】\n"
        "下面是需要替换的当前候选文案。请保留用户事实，换一个切入角度和表达方式完整重写，"
        "不要复述原句，只返回 1 条符合上述 JSON 格式的候选。\n"
        f"当前候选：\n{payload.original_script}"
    )
    config = LLMConfig(**settings_store.get_llm_settings(user["id"]))
    try:
        content = await llm_service.generate(
            config,
            [
                LLMMessage(role="system", content="你是专业、克制的中文短视频文案编导，必须严格遵守事实边界和输出格式。"),
                LLMMessage(role="user", content=rewrite_prompt),
            ],
            temperature=0.85,
            max_tokens=1200,
        )
    except LLMServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    scripts = template_production.parse_generated_scripts(content, 1)
    if not scripts:
        raise HTTPException(status_code=502, detail="LLM 没有返回可用文案，请重试")
    return {"script": scripts[0]}


@router.post("/tasks")
async def create_task(
    template_id: str = Form(...),
    scripts: str = Form(...),
    generate_count: int = Form(...),
    video_config: str = Form(...),
    subtitle_replacements: str = Form("[]"),
    material_manifest: str = Form(...),
    materials: list[UploadFile] = File(...),
    user: dict = Depends(require_current_user),
):
    try:
        template_id = template_production.require_template(template_id)
        template_production.require_ffmpeg()
    except template_production.TemplateProductionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if generate_count < 1 or generate_count > MAX_GENERATE_COUNT:
        raise HTTPException(status_code=422, detail=f"generate_count 必须在 1-{MAX_GENERATE_COUNT} 之间")
    if not materials or len(materials) > MAX_MATERIAL_COUNT:
        raise HTTPException(status_code=422, detail=f"素材数量必须在 1-{MAX_MATERIAL_COUNT} 之间")

    script_values = [str(item).strip() for item in _parse_json_field(scripts, "scripts", list) if str(item).strip()]
    if not script_values or len(script_values) > MAX_GENERATE_COUNT:
        raise HTTPException(status_code=422, detail="文案数量必须在 1-50 之间")
    video = _parse_json_field(video_config, "video_config", dict)
    parsed_replacements = _parse_subtitle_replacements(subtitle_replacements)
    if parsed_replacements and template_id != template_production.ZHONGYI_TEMPLATE_ID:
        raise HTTPException(status_code=422, detail="当前模板暂不支持字幕替换")
    manifest = _parse_json_field(material_manifest, "material_manifest", list)
    _validate_material_manifest(template_id, manifest, len(materials))

    ratio = str(video.get("ratio") or "9:16")
    try:
        template_production.ratio_size(ratio)
    except template_production.TemplateProductionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    output_root = resolve_output_dir(app_config)
    task_id = uuid.uuid4().hex
    task_dir = output_root / "template_production" / task_id
    input_dir = task_dir / "input"
    output_dir = task_dir / "output"
    temp_dir = task_dir / "temp"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    manifest_by_index = {int(item["file_index"]): item for item in manifest}
    saved_materials: list[dict[str, Any]] = []
    for index, upload in enumerate(materials):
        item = manifest_by_index[index]
        media_type = item["media_type"]
        suffix = Path(upload.filename or "").suffix.lower()
        allowed = IMAGE_EXTENSIONS if media_type == "image" else VIDEO_EXTENSIONS
        if suffix not in allowed:
            raise HTTPException(status_code=422, detail=f"不支持的{media_type}格式：{upload.filename}")
        material_id = uuid.uuid4().hex
        safe_name = _safe_filename(upload.filename or f"material_{index}{suffix}", f"material_{index}{suffix}")
        input_path = input_dir / f"{material_id}{suffix}"
        input_path.write_bytes(await upload.read())
        saved_materials.append(
            {
                "id": material_id,
                "name": safe_name,
                "media_type": media_type,
                "requirement_id": item["requirement_id"],
                "input_path": input_path,
            }
        )

    task_items = [
        {
            "id": uuid.uuid4().hex,
            "index": index + 1,
            "script": script_values[index % len(script_values)],
            "status": "pending",
            "message": "等待生成",
            "video_url": None,
            "error": None,
        }
        for index in range(generate_count)
    ]
    _tasks[task_id] = {
        "user_id": user["id"],
        "template_id": template_id,
        "status": "pending",
        "progress": 0,
        "message": "任务已创建，等待处理",
        "items": task_items,
        "zip_url": None,
        "error": None,
    }
    asyncio.create_task(
        _run_task(
            task_id=task_id,
            task_dir=task_dir,
            output_dir=output_dir,
            temp_dir=temp_dir,
            materials=saved_materials,
            ratio=ratio,
            subtitle_replacements=parsed_replacements,
        )
    )
    return {"task_id": task_id}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, user: dict = Depends(require_current_user)):
    task = _tasks.get(task_id)
    if task is None or task.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


async def _run_task(
    *,
    task_id: str,
    task_dir: Path,
    output_dir: Path,
    temp_dir: Path,
    materials: list[dict[str, Any]],
    ratio: str,
    subtitle_replacements: list[dict[str, str]],
) -> None:
    task = _tasks[task_id]
    completed_outputs: list[Path] = []
    failed = 0
    try:
        is_zhongyi = task["template_id"] == template_production.ZHONGYI_TEMPLATE_ID
        prepared_segments: list[Path] = []
        if is_zhongyi:
            task.update(status="running", progress=10, message="素材已就绪，正在生成视频")
        else:
            task.update(status="running", progress=1, message="正在标准化素材")
            for index, material in enumerate(materials, start=1):
                segment_path = temp_dir / f"segment_{index:02d}.mp4"
                await asyncio.to_thread(
                    template_production.prepare_material_segment,
                    material["input_path"],
                    segment_path,
                    media_type=material["media_type"],
                    ratio=ratio,
                )
                prepared_segments.append(segment_path)
                task.update(
                    progress=max(2, round(index / len(materials) * 10)),
                    message=f"正在处理素材 {index}/{len(materials)}",
                )

        total = len(task["items"])
        for index, item in enumerate(task["items"], start=1):
            item.update(status="running", message="正在生成配音")
            task.update(
                progress=10 + round((index - 1) / total * 85),
                message=f"正在生成第 {index}/{total} 条视频",
            )
            audio_path = temp_dir / f"audio_{index:03d}.mp3"
            output_path = output_dir / f"template_video_{index:03d}.mp4"
            try:
                tts_text = template_production.script_text_for_tts(item["script"]) if is_zhongyi else item["script"]
                tts_result = await tts_service.synthesize(
                    EDGE_TTS_MODEL,
                    _template_tts_request(tts_text),
                    audio_path,
                )
                audio_duration = tts_result.duration or await asyncio.to_thread(template_production.probe_duration, audio_path)
                item["message"] = "正在合成视频"
                if is_zhongyi:
                    await asyncio.to_thread(
                        template_production.compose_zhongyi_video,
                        materials,
                        audio_path,
                        output_path,
                        script=item["script"],
                        work_dir=temp_dir / f"video_{index:03d}",
                        seed=f"{task_id}:{index}",
                        ratio=ratio,
                        audio_duration=audio_duration,
                        timings=tts_result.timings,
                        subtitle_replacements=subtitle_replacements,
                    )
                else:
                    await asyncio.to_thread(
                        template_production.compose_video,
                        prepared_segments,
                        audio_path,
                        output_path,
                        seed=f"{task_id}:{index}",
                        audio_duration=audio_duration,
                    )
                completed_outputs.append(output_path)
                item.update(
                    status="completed",
                    message="生成完成",
                    video_url=_public_output_url(output_path),
                    error=None,
                )
            except Exception as exc:
                failed += 1
                item.update(status="failed", message="生成失败", error=str(exc))
            finally:
                audio_path.unlink(missing_ok=True)

        if completed_outputs:
            zip_path = task_dir / "template_videos.zip"
            await asyncio.to_thread(_create_zip, zip_path, completed_outputs)
            task["zip_url"] = _public_output_url(zip_path)

        completed = len(completed_outputs)
        status = "failed" if completed == 0 else "completed"
        message = f"批量生成完成：成功 {completed} 条，失败 {failed} 条"
        task.update(status=status, progress=100, message=message, error=message if completed == 0 else None)
    except Exception as exc:
        task.update(status="failed", progress=0, message="模板量产任务失败", error=str(exc))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _create_zip(zip_path: Path, outputs: list[Path]) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in outputs:
            archive.write(path, arcname=path.name)


def _template_tts_request(text: str) -> TTSRequest:
    return TTSRequest(
        text=text,
        voice_id=TEMPLATE_TTS_VOICE_ID,
        speed=TEMPLATE_TTS_SPEED,
        volume=TEMPLATE_TTS_VOLUME,
    )
