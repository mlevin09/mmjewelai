"""Existing control-host composition; only the TLS-pinned HTTPS entrance can reach it."""

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import uvicorn
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from starlette.responses import JSONResponse
from starlette.routing import Route

from .backend import ManagedSecrets, NativeBackendAccess
from .contracts import Inputs
from .https_auth import OAuthConfig
from .https_gateway import create_app
from .native_jobs import NativeRunnerActions
from .workspace_auth import CALLBACK, CLIENT, WorkspaceAuth


class ProxyFence:
    def __init__(self, app, email, audience):
        self.app, self.email, self.audience = app, email, audience

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        raw = dict(scope.get("headers", [])).get(b"x-jewelai-proxy", b"")
        try:
            if not 1 <= len(raw) <= 8192:
                raise ValueError("proxy_identity_required")
            claims = await anyio.to_thread.run_sync(
                lambda: id_token.verify_oauth2_token(
                    raw.decode(), GoogleRequest(), audience=self.audience
                )
            )
            if claims.get("email") != self.email or claims.get("email_verified") is not True:
                raise ValueError("proxy_identity_required")
        except Exception:
            return await JSONResponse({"error": "proxy_identity_required"}, status_code=403)(
                scope, receive, send
            )
        return await self.app(scope, receive, send)


def application(config):
    origin = config["origin"]
    auth = WorkspaceAuth(
        config["auth_state"],
        origin,
        config["identity_project"],
        config["owner_uid"],
        config["browser_key"],
    )
    access = NativeBackendAccess(config["access"], ManagedSecrets(config["access"]["gcloud"]))
    actions = NativeRunnerActions(
        access,
        Inputs(config["corpus"], config["manifest"]),
        config["guest_paths"],
        guest_ready=config["guest_verified"],
        refresh_approval=access._refresh,
    )
    oauth = OAuthConfig(
        resource_url=origin + "/mcp",
        issuer_url=origin + "/",
        discovery_url=origin + "/.well-known/oauth-authorization-server",
        client_id=CLIENT,
        allowed_subjects=[config["owner_uid"]],
        callback_url=CALLBACK,
    )
    app = create_app(oauth, native_actions=actions, auth_provider=auth)
    original_lifespan = app.router.lifespan_context

    async def finish_pending():
        while True:
            try:
                await anyio.to_thread.run_sync(actions.reconcile_finish)
            except Exception:
                # Leave the immutable finish intent for retry; never log payloads.
                pass
            await anyio.sleep(10)

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            async with anyio.create_task_group() as group:
                group.start_soon(finish_pending)
                try:
                    yield
                finally:
                    group.cancel_scope.cancel()

    app.router.lifespan_context = lifespan
    app.routes[:] = [
        r
        for r in app.routes
        if r.path not in {"/.well-known/oauth-authorization-server", "/revoke"}
    ]
    app.routes.extend(
        [
            Route("/.well-known/oauth-authorization-server", auth.metadata),
            Route("/consent", auth.consent, methods=["GET"]),
            Route("/consent", auth.confirm, methods=["POST"]),
            Route("/revoke", auth.revocation, methods=["POST"]),
            Route(
                "/health",
                lambda _: JSONResponse(
                    {
                        "status": "ok",
                        "runner_bound": True,
                        "guest_verified": config["guest_verified"],
                    }
                ),
            ),
        ]
    )
    return ProxyFence(app, config["proxy_email"], config["proxy_audience"])


def main():
    logging.disable(logging.CRITICAL)
    path = Path(os.environ["JEWELAI_WORKSPACE_CONFIG"])
    if path.stat().st_mode & 0o077:
        raise ValueError("private_config_required")
    config = json.loads(path.read_text())
    uvicorn.run(
        application(config),
        host="0.0.0.0",
        port=8081,
        access_log=False,
        ssl_keyfile=config["tls_key"],
        ssl_certfile=config["tls_cert"],
    )


if __name__ == "__main__":
    main()
