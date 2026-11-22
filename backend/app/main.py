import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import errors, routes_availability, routes_master, routes_rosters
from app.config import get_settings
from app.db import engine

app = FastAPI(title="Smart Roster Management System", version="0.3.0",
              description="Plan, generate, validate and manage monthly rosters across brands, processes and pods.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
errors.install(app)
app.include_router(routes_master.router)
app.include_router(routes_availability.router)
app.include_router(routes_rosters.router)


@app.get("/api/health", tags=["health"])
def health():
    """Liveness plus a database round-trip. Returns 503 when the database is unreachable,
    so platform health checks (e.g. Render) detect a broken deployment."""
    body = {"status": "ok", "database": "ok", "version": app.version,
            "commit": (os.getenv("RENDER_GIT_COMMIT") or "")[:7] or None}
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as exc:  # reported, not raised; never leaks connection details
        body.update(status="error", database=f"error: {exc.__class__.__name__}")
        return JSONResponse(body, status_code=503)
    return body
