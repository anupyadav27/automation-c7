"""
Cloud Estate Console API — the UI's data plane.

    .venv/bin/python -m uvicorn api.server:app --port 8090

One router per domain (platform-standards.md §4), everything reads through
store/ — files or postgres backend, same payloads.
"""
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import store
from api.auth import token_auth_middleware
from api.routers import architecture, inventory, overview, pipeline

app = FastAPI(
    title="Cloud Estate Console API",
    description="discover → assets → architecture",
    version="1.0.0",
)

app.middleware("http")(token_auth_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

for domain_router in (inventory.router, architecture.router,
                        overview.router, pipeline.router):
    app.include_router(domain_router)


@app.get("/health")
def health():
    backend = store.get_backend()
    return {"status": "ok", "backend": getattr(backend, "NAME", "unknown")}
