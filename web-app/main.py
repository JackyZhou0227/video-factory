"""
Video Factory — 数字人口播视频 Web 应用

FastAPI 后端入口。
启动：uvicorn main:app --host 0.0.0.0 --port 8001 --reload
"""

from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
config_path = ROOT / "config.yaml"
app_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

# Ensure output dir exists
output_dir = ROOT / app_config["server"]["output_dir"]
output_dir.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Create FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Video Factory",
    description="AI 驱动的数字人口播视频生成平台",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Register routers & static mounts
# ---------------------------------------------------------------------------
from routers.digital_human import router as digital_human_router
from routers.settings import router as settings_router

app.include_router(digital_human_router, prefix="/api")
app.include_router(settings_router, prefix="/api")

app.mount("/output", StaticFiles(directory=str(output_dir)), name="output")

# Mount frontend static files (must be last)
frontend_dist = ROOT / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    cfg = app_config["server"]
    uvicorn.run(
        "main:app",
        host=cfg.get("host", "0.0.0.0"),
        port=cfg.get("port", 8001),
        reload=True,
    )
