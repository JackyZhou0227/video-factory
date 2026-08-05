from __future__ import annotations

import math
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.auth import require_current_user
from app.core.config import app_config, resolve_output_dir
from app.services import tts_qwen, voice_profiles
from app.services.tts import (
    EDGE_TTS_MODEL,
    QWEN3_TTS_BASE_MODEL,
    TTSRequest,
    TTSServiceError,
    tts_service,
)

router = APIRouter(prefix="/tts-studio", dependencies=[Depends(require_current_user)])

MIN_SPEECH_RATE = 1.0
NORMAL_SPEECH_RATE = 1.0
MAX_SPEECH_RATE = 1.5
_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_AUDIO_SUFFIX_PATTERN = re.compile(r"^\.[A-Za-z0-9]{1,10}$")


def _user_id(user: dict) -> str:
    user_id = str(user.get("id") or "").strip()
    if not _USER_ID_PATTERN.fullmatch(user_id):
        raise HTTPException(status_code=422, detail="Invalid user id")
    return user_id


def _output_root() -> Path:
    return resolve_output_dir(app_config).resolve()


def _user_output_root(user_id: str) -> Path:
    output_root = _output_root()
    user_root = (output_root / "tts-studio" / user_id).resolve()
    try:
        user_root.relative_to(output_root)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid output directory") from None
    return user_root


def _public_output_url(path: Path) -> str:
    output_root = _output_root()
    try:
        relative_path = path.resolve().relative_to(output_root)
    except ValueError:
        raise HTTPException(status_code=422, detail="Audio file is outside output directory") from None
    return f"/output/{relative_path.as_posix()}"


def _resolve_user_output_file(public_url: str, user_id: str) -> Path:
    if not public_url.startswith("/output/"):
        raise HTTPException(status_code=422, detail="audio_url must start with /output/")

    output_root = _output_root()
    relative_path = public_url.removeprefix("/output/").lstrip("/")
    resolved_path = (output_root / relative_path).resolve()
    user_root = _user_output_root(user_id)

    try:
        resolved_path.relative_to(user_root)
    except ValueError:
        raise HTTPException(status_code=422, detail="audio_url is outside this user's TTS Studio output") from None

    if not resolved_path.exists() or not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return resolved_path


def _new_preview_audio_path(user_id: str, suffix: str = ".wav") -> tuple[str, Path, Path]:
    audio_id = uuid.uuid4().hex
    audio_dir = _user_output_root(user_id) / audio_id
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_id, audio_dir, audio_dir / f"preview_original{suffix}"


def _normalize_speech_rate(speech_rate: float) -> float:
    try:
        rate = float(speech_rate)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="speech_rate must be a number") from None

    if not math.isfinite(rate) or rate < MIN_SPEECH_RATE or rate > MAX_SPEECH_RATE:
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

    output_format = audio_path.suffix.removeprefix(".") or "wav"
    audio = AudioSegment.from_file(audio_path)
    if rate > NORMAL_SPEECH_RATE:
        speedup(audio, playback_speed=rate, chunk_size=50, crossfade=25).export(
            temp_path,
            format=output_format,
        )
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
            except subprocess.CalledProcessError as exc:
                detail = exc.stderr.strip() or exc.stdout.strip() or "speech slowdown failed"
                raise HTTPException(status_code=500, detail=detail) from None
        else:
            slowed = audio._spawn(
                audio.raw_data,
                overrides={"frame_rate": max(1, int(audio.frame_rate * rate))},
            ).set_frame_rate(audio.frame_rate)
            slowed.export(temp_path, format=output_format)

    temp_path.replace(variant_path)
    return variant_path


def _safe_audio_suffix(filename: Optional[str]) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if _AUDIO_SUFFIX_PATTERN.fullmatch(suffix) else ".wav"


def _require_known_edge_voice(voice_id: str) -> str:
    normalized_voice_id = voice_id.strip()
    if not normalized_voice_id:
        raise HTTPException(status_code=422, detail="voice_id is required")
    voices = tts_service.list_voices(EDGE_TTS_MODEL)
    if not any(item.get("id") == normalized_voice_id for item in voices):
        raise HTTPException(status_code=422, detail=f"Unsupported Edge-TTS voice: {normalized_voice_id}")
    return normalized_voice_id


def _raise_tts_error(exc: TTSServiceError) -> None:
    raise HTTPException(status_code=422, detail=str(exc)) from None


def _with_tts_studio_audio_url(voice: dict) -> dict:
    return {
        **voice,
        "audio_url": f"/api/tts-studio/voice-profiles/{voice['id']}/audio",
    }


@router.get("/edge-tts/voices")
def get_edge_tts_voices():
    return tts_service.list_voices(EDGE_TTS_MODEL)


@router.get("/languages")
def get_languages():
    return tts_qwen.list_languages()


@router.get("/voice-profiles")
def get_voice_profiles():
    return [_with_tts_studio_audio_url(voice) for voice in voice_profiles.list_voice_profiles()]


@router.get("/voice-profiles/{voice_profile_id}/audio")
def get_voice_profile_audio(voice_profile_id: str):
    return FileResponse(voice_profiles.get_voice_audio_path(voice_profile_id))


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
    return _with_tts_studio_audio_url(voice)


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
    return _with_tts_studio_audio_url(voice)


@router.delete("/voice-profiles/{voice_profile_id}")
async def delete_voice_profile(voice_profile_id: str):
    await voice_profiles.delete_voice_profile(voice_profile_id)
    return {"deleted": True}


@router.post("/preview/speech-rate")
async def update_preview_speech_rate(
    audio_url: str = Form(...),
    speech_rate: float = Form(1.0),
    user: dict = Depends(require_current_user),
):
    user_id = _user_id(user)
    audio_path = _resolve_user_output_file(audio_url, user_id)
    output_audio_path = _create_speech_rate_variant(audio_path, speech_rate)
    adjusted_audio_url = _public_output_url(output_audio_path) if output_audio_path != audio_path else None
    return {
        "audio_url": _public_output_url(output_audio_path),
        "original_audio_url": _public_output_url(audio_path),
        "processed_audio_url": adjusted_audio_url,
        "adjusted_audio_url": adjusted_audio_url,
        "speech_rate": _normalize_speech_rate(speech_rate),
    }


@router.post("/edge-tts/preview")
async def preview_edge_tts(
    text: str = Form(...),
    voice_id: str = Form("zh-CN-XiaoxiaoNeural"),
    language: str = Form(""),
    speech_rate: float = Form(1.0),
    user: dict = Depends(require_current_user),
):
    normalized_text = text.strip()
    if not normalized_text:
        raise HTTPException(status_code=422, detail="text is required")

    _normalize_speech_rate(speech_rate)
    normalized_voice_id = _require_known_edge_voice(voice_id)
    edge_voice = next(item for item in tts_service.list_voices(EDGE_TTS_MODEL) if item.get("id") == normalized_voice_id)
    voice_language = str(edge_voice.get("language") or edge_voice.get("locale") or "").strip()
    normalized_language = language.strip() or voice_language
    if voice_language and normalized_language != voice_language:
        raise HTTPException(status_code=422, detail="language does not match the selected Edge-TTS voice")
    audio_id, _, audio_path = _new_preview_audio_path(_user_id(user), suffix=".mp3")
    try:
        await tts_service.synthesize(
            EDGE_TTS_MODEL,
            TTSRequest(
                text=normalized_text,
                voice_id=normalized_voice_id,
                language=normalized_language,
                speed=NORMAL_SPEECH_RATE,
            ),
            audio_path,
        )
    except TTSServiceError as exc:
        _raise_tts_error(exc)

    if not audio_path.is_file():
        raise HTTPException(status_code=500, detail="TTS did not produce an audio file")
    return {
        "audio_id": audio_id,
        "audio_url": _public_output_url(audio_path),
        "original_audio_url": _public_output_url(audio_path),
        "processed_audio_url": None,
        "adjusted_audio_url": None,
        "tts_mode": "edge-tts",
        "voice_id": normalized_voice_id,
        "language": normalized_language,
        "speech_rate": NORMAL_SPEECH_RATE,
    }


@router.post("/voice-clone/preview")
async def preview_voice_clone_tts(
    text: str = Form(...),
    language: str = Form("Chinese"),
    voice_profile_id: Optional[str] = Form(None),
    ref_audio: Optional[UploadFile] = File(None),
    ref_text: Optional[str] = Form(None),
    speech_rate: float = Form(1.0),
    user: dict = Depends(require_current_user),
):
    normalized_text = text.strip()
    if not normalized_text:
        raise HTTPException(status_code=422, detail="text is required")
    if not voice_profile_id and ref_audio is None:
        raise HTTPException(status_code=422, detail="ref_audio or voice_profile_id is required")
    if not voice_profile_id and not (ref_text and ref_text.strip()):
        raise HTTPException(status_code=422, detail="ref_text is required")

    user_id = _user_id(user)
    _normalize_speech_rate(speech_rate)
    audio_id, audio_dir, audio_path = _new_preview_audio_path(user_id)
    if voice_profile_id:
        voice = voice_profiles.get_voice_profile(voice_profile_id)
        if voice is None:
            raise HTTPException(status_code=404, detail="Voice profile not found")
        reference_audio = voice_profiles.get_voice_audio_path(voice_profile_id)
        reference_text = voice.get("ref_text")
    else:
        reference_audio = audio_dir / f"reference{_safe_audio_suffix(ref_audio.filename)}"
        reference_audio.write_bytes(await ref_audio.read())
        reference_text = ref_text.strip() if ref_text else None

    try:
        await tts_service.synthesize(
            QWEN3_TTS_BASE_MODEL,
            TTSRequest(
                text=normalized_text,
                language=language.strip() or "Chinese",
                speed=NORMAL_SPEECH_RATE,
                reference_audio=reference_audio,
                reference_text=reference_text,
            ),
            audio_path,
        )
    except TTSServiceError as exc:
        _raise_tts_error(exc)

    if not audio_path.is_file():
        raise HTTPException(status_code=500, detail="TTS did not produce an audio file")
    return {
        "audio_id": audio_id,
        "audio_url": _public_output_url(audio_path),
        "original_audio_url": _public_output_url(audio_path),
        "processed_audio_url": None,
        "adjusted_audio_url": None,
        "tts_mode": "base",
        "voice_profile_id": voice_profile_id,
        "language": language.strip() or "Chinese",
        "speech_rate": NORMAL_SPEECH_RATE,
    }
