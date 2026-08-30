from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.digital_human import router as digital_human_router
from app.api.output import router as output_router
from app.api.poster_video import router as poster_video_router
from app.api.smart_editing import router as smart_editing_router
from app.api.stats import router as stats_router
from app.api.template_production import router as template_production_router
from app.api.tasks import router as tasks_router
from app.api.tts_studio import router as tts_studio_router
from app.core.config import ROOT, app_config
from app.core.security import install_security_middleware
from app.db.engine import require_postgresql_url
from app.services import auth_store, settings_store, task_store
from app.services.tts import tts_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_application: FastAPI):
    try:
        await tts_service.prewarm_provider_statuses_async()
    except Exception:
        logger.exception("Failed to prewarm TTS provider statuses")
    yield


def create_app() -> FastAPI:
    require_postgresql_url(app_config)
    settings_store.init_db(app_config)
    auth_store.init_auth_schema()
    task_store.mark_incomplete_tasks_failed()

    application = FastAPI(
        title="Video Factory",
        description="AI 驱动的数字人口播视频 Web 应用",
        version="0.1.0",
        lifespan=lifespan,
    )

    install_security_middleware(application, app_config)

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError):
        parts = []
        for error in exc.errors():
            loc = ".".join(str(item) for item in error.get("loc", []) if item != "body")
            message = error.get("msg", "参数校验失败")
            parts.append(f"{loc}: {message}" if loc else message)
        return JSONResponse(status_code=422, content={"detail": "；".join(parts) or "请求参数校验失败"})

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception):
        logger.exception("Unhandled server error", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后重试"})

    application.include_router(auth_router, prefix="/api")
    application.include_router(admin_router, prefix="/api")
    application.include_router(stats_router, prefix="/api")
    application.include_router(output_router)
    application.include_router(digital_human_router, prefix="/api")
    application.include_router(tts_studio_router, prefix="/api")
    application.include_router(poster_video_router, prefix="/api")
    application.include_router(template_production_router, prefix="/api")
    application.include_router(smart_editing_router, prefix="/api")
    application.include_router(tasks_router, prefix="/api")

    @application.get("/api/health")
    def health():
        return {"status": "ok"}

    frontend_dist = ROOT / "frontend" / "dist"
    if frontend_dist.exists():
        application.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return application


app = create_app()
