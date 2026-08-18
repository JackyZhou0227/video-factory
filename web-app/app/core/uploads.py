from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from fastapi import HTTPException, UploadFile

UPLOAD_CHUNK_SIZE = 1024 * 1024

MAX_AUDIO_FILE_SIZE = 50 * 1024 * 1024
MAX_IMAGE_FILE_SIZE = 20 * 1024 * 1024
MAX_VIDEO_FILE_SIZE = 500 * 1024 * 1024
MAX_JSON_FILE_SIZE = 1 * 1024 * 1024

GENERIC_MIME_TYPES = {"", "application/octet-stream", "binary/octet-stream"}

AUDIO_MIME_TYPES = {
    "audio/aac",
    "audio/flac",
    "audio/m4a",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/wave",
    "audio/x-flac",
    "audio/x-m4a",
    "audio/x-wav",
}
IMAGE_MIME_TYPES = {
    "image/bmp",
    "image/jpeg",
    "image/png",
    "image/webp",
}
VIDEO_MIME_TYPES = {
    "video/avi",
    "video/mp4",
    "video/quicktime",
    "video/x-m4v",
    "video/x-matroska",
    "video/x-msvideo",
    "video/webm",
}
JSON_MIME_TYPES = {"application/json", "text/json"}


class UploadValidationError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=422, detail=detail)


def _normalise_mime_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _extension(filename: str | None, default_suffix: str | None = None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix:
        return suffix
    return (default_suffix or "").lower()


def _display_name(upload: UploadFile, filename: str | None = None) -> str:
    return filename or upload.filename or "未命名文件"


def validate_upload(
    upload: UploadFile,
    *,
    allowed_extensions: Iterable[str],
    allowed_mime_types: Iterable[str],
    max_size: int,
    default_suffix: str | None = None,
    filename: str | None = None,
    label: str = "文件",
) -> str:
    """Validate metadata before writing an UploadFile and return its suffix."""
    display_name = _display_name(upload, filename)
    allowed_suffixes = {str(item).lower() for item in allowed_extensions}
    suffix = _extension(display_name, default_suffix)
    if suffix not in allowed_suffixes:
        raise UploadValidationError(f"不支持的{label}格式：{display_name}")

    declared_mime = _normalise_mime_type(getattr(upload, "content_type", None))
    allowed_types = {str(item).lower() for item in allowed_mime_types}
    if declared_mime not in GENERIC_MIME_TYPES and declared_mime not in allowed_types:
        raise UploadValidationError(f"{label} MIME 类型不匹配：{declared_mime}")

    declared_size = getattr(upload, "size", None)
    if declared_size is not None and declared_size > max_size:
        raise UploadValidationError(f"{label}不能超过 {max_size // (1024 * 1024)} MB")
    return suffix


async def save_upload(
    upload: UploadFile,
    destination: Path,
    *,
    allowed_extensions: Iterable[str],
    allowed_mime_types: Iterable[str],
    max_size: int,
    default_suffix: str | None = None,
    filename: str | None = None,
    label: str = "文件",
) -> int:
    """Stream an upload to disk, atomically replacing the destination on success."""
    validate_upload(
        upload,
        allowed_extensions=allowed_extensions,
        allowed_mime_types=allowed_mime_types,
        max_size=max_size,
        default_suffix=default_suffix,
        filename=filename,
        label=label,
    )

    destination = Path(destination)
    temporary_path = destination.with_name(f".{destination.name}.part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path.unlink(missing_ok=True)
    total = 0
    try:
        with temporary_path.open("wb") as output:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_size:
                    raise UploadValidationError(f"{label}不能超过 {max_size // (1024 * 1024)} MB")
                output.write(chunk)
            output.flush()
        temporary_path.replace(destination)
        return total
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def safe_upload_filename(filename: str | None, fallback: str) -> str:
    value = Path(filename or fallback).name
    safe = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", value, flags=re.UNICODE).strip("._")
    return safe or fallback

