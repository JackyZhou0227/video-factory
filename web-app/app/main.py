from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.digital_human import router as digital_human_router
from app.api.poster_video import router as poster_video_router
from app.api.template_production import router as template_production_router
from app.api.tts_studio import router as tts_studio_router
from app.core.config import ROOT, app_config, resolve_output_dir
from app.services import auth_store, settings_store


def create_app() -> FastAPI:
    settings_store.init_db(app_config)
    auth_store.init_auth_schema()

    output_dir = resolve_output_dir(app_config)

    application = FastAPI(
        title="Video Factory",
        description="AI 驱动的数字人口播视频 Web 应用",
        version="0.1.0",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(auth_router, prefix="/api")
    application.include_router(admin_router, prefix="/api")
    application.include_router(digital_human_router, prefix="/api")
    application.include_router(tts_studio_router, prefix="/api")
    application.include_router(poster_video_router, prefix="/api")
    application.include_router(template_production_router, prefix="/api")

    @application.get("/api/health")
    def health():
        return {"status": "ok"}

    application.mount("/output", StaticFiles(directory=str(output_dir)), name="output")

    frontend_dist = ROOT / "frontend" / "dist"
    if frontend_dist.exists():
        application.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return application


app = create_app()
