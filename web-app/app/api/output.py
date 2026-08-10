from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.auth import require_current_user
from app.services import task_store

router = APIRouter(prefix="/output", tags=["output"], dependencies=[Depends(require_current_user)])


@router.get("/{relative_path:path}")
def get_output_file(relative_path: str, user: dict = Depends(require_current_user)):
    try:
        path = task_store.resolve_output_file_for_user(relative_path, user["id"])
    except task_store.ArtifactNotFoundError:
        raise HTTPException(status_code=404, detail="Output file not found") from None
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, content_disposition_type="inline")
