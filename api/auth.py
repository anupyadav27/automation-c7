"""
Optional bearer-token auth.

Off by default so local development is frictionless. Set API_TOKEN and every
/api/v1/* request must carry `Authorization: Bearer <token>`; /health stays
open for probes. This is the gate that must be on before the API is exposed
beyond localhost.
"""
import hmac
import os

from fastapi import Request
from fastapi.responses import JSONResponse


async def token_auth_middleware(request: Request, call_next):
    expected = os.getenv("API_TOKEN")
    path = request.url.path
    if expected and path.startswith("/api/"):
        header = request.headers.get("authorization", "")
        supplied = header[7:] if header.lower().startswith("bearer ") else ""
        if not hmac.compare_digest(supplied, expected):
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "unauthorized",
                                   "message": "valid bearer token required",
                                   "detail": None}},
            )
    return await call_next(request)
