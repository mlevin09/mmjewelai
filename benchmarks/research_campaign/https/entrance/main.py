"""TLS-pinned reverse entrance to the EXISTING control host; no research or GCP authority."""

import asyncio
import logging
import os
import ssl

import google.auth.transport.requests
import google.oauth2.id_token
import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

logging.disable(logging.CRITICAL)
AUDIENCE = "https://jewelai-native-runner.internal"
BACKEND = os.environ["RESEARCH_BACKEND"]
HOST = os.environ["RESEARCH_PUBLIC_HOST"]
CONTEXT = ssl.create_default_context(cafile="/app/backend.crt")
ALLOWED = {
    "/mcp",
    "/health",
    "/authorize",
    "/token",
    "/revoke",
    "/consent",
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-protected-resource/mcp",
}


async def forward(request: Request):
    if request.url.path not in ALLOWED:
        return JSONResponse({"error": "not_found"}, status_code=404)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 32768:
            return Response(status_code=413)
    try:
        token = await asyncio.to_thread(
            google.oauth2.id_token.fetch_id_token,
            google.auth.transport.requests.Request(),
            AUDIENCE,
        )
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower()
            in {
                "authorization",
                "content-type",
                "accept",
                "mcp-protocol-version",
                "mcp-session-id",
                "origin",
                "cookie",
            }
        }
        headers.update({"host": HOST, "x-jewelai-proxy": token})
        async with httpx.AsyncClient(
            verify=CONTEXT, timeout=55, follow_redirects=False, trust_env=False
        ) as client:
            result = await client.request(
                request.method,
                BACKEND + request.url.path,
                params=request.query_params,
                content=bytes(body),
                headers=headers,
            )
        # OAuth locations/cookies are internal application-generated, no platform/raw logs.
        out = {
            k: v
            for k, v in result.headers.items()
            if k.lower()
            in {
                "content-type",
                "location",
                "www-authenticate",
                "cache-control",
                "content-security-policy",
                "referrer-policy",
                "x-content-type-options",
            }
        }
        response = Response(result.content, status_code=result.status_code, headers=out)
        for cookie in result.headers.get_list("set-cookie"):
            response.headers.append("set-cookie", cookie)
        return response
    except Exception:
        return JSONResponse({"error": "research_connection_unavailable"}, status_code=503)


app = Starlette(
    routes=[Route("/{path:path}", forward, methods=["GET", "POST", "DELETE", "OPTIONS"])]
)
