from __future__ import annotations

import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.core import uploads
from app.core.config import app_config, resolve_output_dir
from app.db.engine import require_postgresql_url
from app.db.models import User, VoiceProfile
from app.db.session import get_session_factory, session_scope as orm_session_scope


AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac"}
MAX_VOICE_PROFILES_PER_USER = 20


@contextmanager
def _orm_session() -> Iterator[OrmSession]:
    database_url = require_postgresql_url(app_config)
    with orm_session_scope(get_session_factory(database_url)) as session:
        yield session


def _output_root() -> Path:
    return resolve_output_dir(app_config).resolve()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _profile_record(profile: VoiceProfile) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "language": profile.language,
        "ref_text": profile.ref_text,
        "audio_filename": Path(profile.relative_path).name,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
        "audio_url": f"/api/tts-studio/voice-profiles/{profile.id}/audio",
    }


def _profile_audio_path(profile: VoiceProfile) -> Path:
    output_root = _output_root()
    path = (output_root / profile.relative_path).resolve()
    owner_root = (output_root / "voice_profiles" / profile.user_id / profile.id).resolve()
    try:
        path.relative_to(owner_root)
    except ValueError:
        raise HTTPException(status_code=404, detail="Voice audio not found") from None
    return path


def _profile_dir(user_id: str, voice_id: str) -> Path:
    output_root = _output_root()
    path = (output_root / "voice_profiles" / user_id / voice_id).resolve()
    try:
        path.relative_to(output_root / "voice_profiles")
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid voice profile path") from None
    return path


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(_output_root()).as_posix()
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid voice profile path") from None


def _fetch_profile(
    session: OrmSession,
    user_id: str,
    voice_id: str,
    *,
    for_update: bool = False,
) -> VoiceProfile | None:
    query = select(VoiceProfile).where(
        VoiceProfile.id == voice_id,
        VoiceProfile.user_id == user_id,
    )
    if for_update:
        query = query.with_for_update()
    return session.scalar(query)


def list_voice_profiles(user_id: str) -> list[dict]:
    with _orm_session() as session:
        profiles = session.scalars(
            select(VoiceProfile)
            .where(VoiceProfile.user_id == user_id)
            .order_by(VoiceProfile.updated_at.desc())
        ).all()
        return [_profile_record(profile) for profile in profiles]


def get_voice_profile(user_id: str, voice_id: str) -> Optional[dict]:
    with _orm_session() as session:
        profile = _fetch_profile(session, user_id, voice_id)
        return _profile_record(profile) if profile is not None else None


def get_voice_audio_path(user_id: str, voice_id: str) -> Path:
    with _orm_session() as session:
        profile = _fetch_profile(session, user_id, voice_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Voice profile not found")
        audio_path = _profile_audio_path(profile)
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail="Voice audio not found")
    return audio_path


def _validate_fields(name: str, ref_text: str) -> tuple[str, str]:
    normalized_name = name.strip()
    normalized_ref_text = ref_text.strip()
    if not normalized_name:
        raise HTTPException(status_code=422, detail="name is required")
    if not normalized_ref_text:
        raise HTTPException(status_code=422, detail="ref_text is required")
    return normalized_name, normalized_ref_text


async def create_voice_profile(
    *,
    user_id: str,
    name: str,
    language: str,
    ref_text: str,
    ref_audio: UploadFile,
) -> dict:
    normalized_name, normalized_ref_text = _validate_fields(name, ref_text)
    suffix = uploads.validate_upload(
        ref_audio,
        allowed_extensions=AUDIO_EXTENSIONS,
        allowed_mime_types=uploads.AUDIO_MIME_TYPES,
        max_size=uploads.MAX_AUDIO_FILE_SIZE,
        default_suffix=".wav",
        label="参考音频",
    )
    voice_id = uuid.uuid4().hex
    voice_dir = _profile_dir(user_id, voice_id)
    audio_path = voice_dir / f"reference-{uuid.uuid4().hex}{suffix}"
    try:
        file_size = await uploads.save_upload(
            ref_audio,
            audio_path,
            allowed_extensions=AUDIO_EXTENSIONS,
            allowed_mime_types=uploads.AUDIO_MIME_TYPES,
            max_size=uploads.MAX_AUDIO_FILE_SIZE,
            default_suffix=".wav",
            label="参考音频",
        )
        now = _now_iso()
        with _orm_session() as session:
            owner = session.scalar(select(User).where(User.id == user_id).with_for_update())
            if owner is None:
                raise HTTPException(status_code=404, detail="User not found")
            count = session.scalar(
                select(func.count()).select_from(VoiceProfile).where(VoiceProfile.user_id == user_id)
            ) or 0
            if count >= MAX_VOICE_PROFILES_PER_USER:
                raise HTTPException(
                    status_code=422,
                    detail=f"每个用户最多保存 {MAX_VOICE_PROFILES_PER_USER} 个音色档案",
                )
            profile = VoiceProfile(
                id=voice_id,
                user_id=user_id,
                name=normalized_name,
                language=language.strip() or "Chinese",
                ref_text=normalized_ref_text,
                relative_path=_relative_path(audio_path),
                file_size=file_size,
                created_at=now,
                updated_at=now,
            )
            session.add(profile)
            session.flush()
            record = _profile_record(profile)
    except Exception:
        shutil.rmtree(voice_dir, ignore_errors=True)
        raise
    return record


async def update_voice_profile(
    *,
    user_id: str,
    voice_id: str,
    name: str,
    language: str,
    ref_text: str,
    ref_audio: Optional[UploadFile] = None,
) -> dict:
    normalized_name, normalized_ref_text = _validate_fields(name, ref_text)
    with _orm_session() as session:
        if _fetch_profile(session, user_id, voice_id) is None:
            raise HTTPException(status_code=404, detail="Voice profile not found")
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

    voice_dir = _profile_dir(user_id, voice_id)
    new_audio_path = None
    file_size = None
    if suffix is not None:
        new_audio_path = voice_dir / f"reference-{uuid.uuid4().hex}{suffix}"
        file_size = await uploads.save_upload(
            ref_audio,
            new_audio_path,
            allowed_extensions=AUDIO_EXTENSIONS,
            allowed_mime_types=uploads.AUDIO_MIME_TYPES,
            max_size=uploads.MAX_AUDIO_FILE_SIZE,
            default_suffix=".wav",
            label="参考音频",
        )

    old_audio_path = None
    try:
        with _orm_session() as session:
            profile = _fetch_profile(session, user_id, voice_id, for_update=True)
            if profile is None:
                raise HTTPException(status_code=404, detail="Voice profile not found")
            if new_audio_path is not None:
                old_audio_path = _profile_audio_path(profile)
                profile.relative_path = _relative_path(new_audio_path)
                profile.file_size = int(file_size or 0)
            profile.name = normalized_name
            profile.language = language.strip() or "Chinese"
            profile.ref_text = normalized_ref_text
            profile.updated_at = _now_iso()
            session.flush()
            record = _profile_record(profile)
    except Exception:
        if new_audio_path is not None:
            new_audio_path.unlink(missing_ok=True)
        raise

    if old_audio_path is not None and old_audio_path != new_audio_path:
        old_audio_path.unlink(missing_ok=True)
    return record


def delete_voice_profile(user_id: str, voice_id: str) -> None:
    with _orm_session() as session:
        profile = _fetch_profile(session, user_id, voice_id, for_update=True)
        if profile is None:
            raise HTTPException(status_code=404, detail="Voice profile not found")
        voice_dir = _profile_audio_path(profile).parent
        session.delete(profile)
    shutil.rmtree(voice_dir, ignore_errors=True)
