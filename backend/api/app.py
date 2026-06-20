"""FastAPI application factory.

Mounts the REST + WS routers and (when built) the static frontend. During
frontend dev, CORS is open to the Vite dev server; in production the built
SPA is served from backend/static.
"""
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import app_paths
from api.settings_api import router as settings_router
from api.device_api import router as device_router
from api.run_api import router as run_router
from api.run_ws import router as run_ws_router
from api.graphs_api import router as graphs_router
from api.assets_api import router as assets_router
from api.scenarios_api import router as scenarios_router
from api.ai_api import router as ai_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="coc-studio backend", version="0.1.0")

    # Vite dev server origins — harmless in local-only use.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Always revalidate HTML (index.html) so a rebuilt SPA shows up on reload
    # without a hard refresh; the hashed JS/CSS assets stay cacheable.
    @app.middleware("http")
    async def _no_cache_html(request, call_next):
        resp = await call_next(request)
        if resp.headers.get("content-type", "").startswith("text/html"):
            resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp

    app.include_router(settings_router)
    app.include_router(device_router)
    app.include_router(run_router)
    app.include_router(run_ws_router)
    app.include_router(graphs_router)
    app.include_router(assets_router)
    app.include_router(scenarios_router)
    app.include_router(ai_router)

    @app.get("/api/health")
    def health():
        return {"ok": True, "service": "coc-studio"}

    # Serve the built SPA if present (production). Mounted last so /api and
    # /ws routes take precedence.
    if os.path.isdir(app_paths.STATIC_DIR):
        app.mount(
            "/",
            StaticFiles(directory=app_paths.STATIC_DIR, html=True),
            name="static",
        )
        logger.info("Serving static frontend from %s", app_paths.STATIC_DIR)
    else:
        logger.info("No static frontend yet — run the Vite dev server on :5173")

    return app
