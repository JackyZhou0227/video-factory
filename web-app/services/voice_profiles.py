from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile

_voice_lock = asyncio.Lock()


def _root() -> Path:
    from main import ROOT

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
        "audio_url": f"/api/voice-profiles/{voice['id']}/audio",
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

    suffix = Path(ref_audio.filename or "").suffix or ".wav"
    audio_path = voice_dir / f"reference{suffix}"
    audio_path.write_bytes(await ref_audio.read())

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

    return _with_audio_url(voice)
