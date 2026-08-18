from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile

from app.core import uploads

_voice_lock = asyncio.Lock()

AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac"}


def _root() -> Path:
    from app.core.config import ROOT

    return ROOT


def _library_dir() -> Path:
    return _root() / "data" / "voice_profiles"


def _index_path() -> Path:
    return _library_dir() / "index.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_library_dir() -> None:
    _library_dir().mkdir(parents=True, exist_ok=True)


def _load_index() -> dict:
    _ensure_library_dir()
    path = _index_path()
    if not path.exists():
        return {"voices": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"voices": []}


def _write_index(data: dict) -> None:
    _ensure_library_dir()
    path = _index_path()
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _voice_dir(voice_id: str) -> Path:
    return _library_dir() / voice_id


def _voice_audio_path(voice: dict) -> Path:
    return _voice_dir(voice["id"]) / (voice.get("audio_filename") or "reference.wav")


def _with_audio_url(voice: dict) -> dict:
    return {
        **voice,
        "audio_url": f"/api/tts-studio/voice-profiles/{voice['id']}/audio",
    }


def list_voice_profiles() -> list[dict]:
    data = _load_index()
    voices = data.get("voices", [])
    voices.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
    return [_with_audio_url(voice) for voice in voices]


def get_voice_profile(voice_id: str) -> Optional[dict]:
    for voice in _load_index().get("voices", []):
        if voice.get("id") == voice_id:
            return _with_audio_url(voice)
    return None


def get_voice_audio_path(voice_id: str) -> Path:
    voice = get_voice_profile(voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="Voice profile not found")
    audio_path = _voice_audio_path(voice)
    if not audio_path.exists() or not audio_path.is_file():
        raise HTTPException(status_code=404, detail="Voice audio not found")
    return audio_path


async def create_voice_profile(
    name: str,
    language: str,
    ref_text: str,
    ref_audio: UploadFile,
) -> dict:
    if not name.strip():
        raise HTTPException(status_code=422, detail="name is required")
    if not ref_text.strip():
        raise HTTPException(status_code=422, detail="ref_text is required")

    voice_id = uuid.uuid4().hex
    voice_dir = _voice_dir(voice_id)
    voice_dir.mkdir(parents=True, exist_ok=True)

    suffix = uploads.validate_upload(
        ref_audio,
        allowed_extensions=AUDIO_EXTENSIONS,
        allowed_mime_types=uploads.AUDIO_MIME_TYPES,
        max_size=uploads.MAX_AUDIO_FILE_SIZE,
        default_suffix=".wav",
        label="参考音频",
    )
    audio_path = voice_dir / f"reference{suffix}"
    try:
        await uploads.save_upload(
            ref_audio,
            audio_path,
            allowed_extensions=AUDIO_EXTENSIONS,
            allowed_mime_types=uploads.AUDIO_MIME_TYPES,
            max_size=uploads.MAX_AUDIO_FILE_SIZE,
            default_suffix=".wav",
            label="参考音频",
        )

        voice = {
            "id": voice_id,
            "name": name.strip(),
            "language": language.strip() or "Chinese",
            "ref_text": ref_text.strip(),
            "audio_filename": audio_path.name,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }

        async with _voice_lock:
            data = _load_index()
            voices = [item for item in data.get("voices", []) if item.get("id") != voice_id]
            voices.append(voice)
            data["voices"] = voices
            _write_index(data)
    except Exception:
        shutil.rmtree(voice_dir, ignore_errors=True)
        raise

    return _with_audio_url(voice)


async def update_voice_profile(
    voice_id: str,
    name: str,
    language: str,
    ref_text: str,
    ref_audio: Optional[UploadFile] = None,
) -> dict:
    if not name.strip():
        raise HTTPException(status_code=422, detail="name is required")
    if not ref_text.strip():
        raise HTTPException(status_code=422, detail="ref_text is required")

    suffix = None
    if ref_audio is not None:
        suffix = uploads.validate_upload(
            ref_audio,
            allowed_extensions=AUDIO_EXTENSIONS,
            allowed_mime_types=uploads.AUDIO_MIME_TYPES,
            max_size=uploads.MAX_AUDIO_FILE_SIZE,
            default_suffix=".wav",
            label="参考音频",
        )

    async with _voice_lock:
        data = _load_index()
        voices = data.get("voices", [])
        voice_index = next((index for index, item in enumerate(voices) if item.get("id") == voice_id), -1)
        if voice_index < 0:
            raise HTTPException(status_code=404, detail="Voice profile not found")

        voice = dict(voices[voice_index])
        voice_dir = _voice_dir(voice_id)
        voice_dir.mkdir(parents=True, exist_ok=True)

        if suffix is not None:
            audio_path = voice_dir / f"reference{suffix}"
            old_audio_path = _voice_audio_path(voice)
            await uploads.save_upload(
                ref_audio,
                audio_path,
                allowed_extensions=AUDIO_EXTENSIONS,
                allowed_mime_types=uploads.AUDIO_MIME_TYPES,
                max_size=uploads.MAX_AUDIO_FILE_SIZE,
                default_suffix=".wav",
                label="参考音频",
            )
            if old_audio_path != audio_path and old_audio_path.exists():
                old_audio_path.unlink()
            voice["audio_filename"] = audio_path.name

        voice.update(
            {
                "name": name.strip(),
                "language": language.strip() or "Chinese",
                "ref_text": ref_text.strip(),
                "updated_at": _now_iso(),
            }
        )
        voices[voice_index] = voice
        data["voices"] = voices
        _write_index(data)

    return _with_audio_url(voice)


async def delete_voice_profile(voice_id: str) -> None:
    async with _voice_lock:
        data = _load_index()
        voices = data.get("voices", [])
        next_voices = [item for item in voices if item.get("id") != voice_id]
        if len(next_voices) == len(voices):
            raise HTTPException(status_code=404, detail="Voice profile not found")
        data["voices"] = next_voices
        _write_index(data)

    shutil.rmtree(_voice_dir(voice_id), ignore_errors=True)
