"""FastAPI entry point. Serves the API and the built React app from ``frontend/dist``.

    .venv/bin/uvicorn backend.main:app --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router
from backend.core.config import FRONTEND_DIST, get_settings

app = FastAPI(title="TrueOffer", version="1.0.0",
              description="Compare job offers by what they're really worth after taxes, rent and living costs.")
app.add_middleware(CORSMiddleware, allow_origins=list(get_settings().cors_origins), allow_methods=["GET", "POST"],
                   allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Conservative security headers; the app loads nothing from third-party origins."""
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Content-Security-Policy",
                            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                            "script-src 'self'; connect-src 'self'; font-src 'self' data:")
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


app.include_router(router)

if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    """Serve the single-page app (any non-API path falls back to index.html)."""
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    f = (FRONTEND_DIST / path).resolve()
    if path and f.is_file() and FRONTEND_DIST.resolve() in f.parents:
        return FileResponse(f)
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"detail": "Frontend not built. Run `npm run build` in frontend/, or use the Vite dev server."},
                        status_code=404)
