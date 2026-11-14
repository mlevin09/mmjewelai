"""Official-SDK MCP: status-only by default; explicit narrow native Runner mode.

Runner mode reuses scoped SSH/leases without exposing shell or Tunnel credentials.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import anyio
from mcp import types
from mcp.server.auth.provider import ProviderTokenVerifier
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl

from .contracts import TARGET
from .https_auth import STATUS_SCOPE, OAuthConfig, OAuthTokenVerifier


class StatusUnavailable(RuntimeError):
    pass


class ComputeStatus:
    """ADC is acquired lazily, only after OAuth + tool/argument authorization."""

    def __call__(self) -> dict:
        import google.auth
        from google.auth.exceptions import GoogleAuthError
        from google.auth.transport.requests import AuthorizedSession
        from requests.exceptions import RequestException

        url = (
            "https://compute.googleapis.com/compute/v1/projects/"
            f"{TARGET['project']}/zones/{TARGET['zone']}/instances/{TARGET['vm']}"
        )
        try:
            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/compute.readonly"]
            )
            with AuthorizedSession(credentials) as session:
                response = session.get(
                    url,
                    params={
                        "fields": "name,status,scheduling(maxRunDuration,instanceTerminationAction)"
                    },
                    timeout=10,
                    allow_redirects=False,
                )
                if response.status_code != 200:
                    raise StatusUnavailable("vm_status_unavailable")
                value = response.json()
            if value.get("name") != TARGET["vm"] or value.get("status") not in {
                "PROVISIONING",
                "STAGING",
                "RUNNING",
                "STOPPING",
                "SUSPENDING",
                "SUSPENDED",
                "REPAIRING",
                "TERMINATED",
            }:
                raise StatusUnavailable("vm_status_unavailable")
            scheduling = value.get("scheduling", {})
            seconds = int(scheduling.get("maxRunDuration", {}).get("seconds", 0))
            return {
                "target": dict(TARGET),
                "status": value["status"],
                "maximum_runtime_seconds": seconds if seconds > 0 else None,
                "automatic_stop_configured": (
                    seconds > 0 and scheduling.get("instanceTerminationAction") == "STOP"
                ),
                "observed_at": datetime.now(UTC).isoformat(),
            }
        except (GoogleAuthError, RequestException, ValueError, TypeError, AttributeError):
            raise StatusUnavailable("vm_status_unavailable") from None


def create_app(
    config: OAuthConfig, *, fetch=None, status_reader=None, native_actions=None, auth_provider=None
):
    verifier = (
        ProviderTokenVerifier(auth_provider)
        if auth_provider
        else OAuthTokenVerifier(config, **({"fetch": fetch} if fetch else {}))
    )
    status_reader = status_reader or ComputeStatus()
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    tool = types.Tool(
        name="vm_status",
        description="Read status and shutdown safeguard of the single authorized Qwen VM.",
        inputSchema=schema,
        annotations=types.ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
        _meta={"securitySchemes": [{"type": "oauth2", "scopes": [STATUS_SCOPE]}]},
    )
    tools, required_scope = [tool], STATUS_SCOPE
    if native_actions is not None:
        from .native_jobs import EXECUTE_SCOPE, READ_SCOPE, TOOLS

        required_scope = READ_SCOPE
        tools = [
            types.Tool(
                name=name,
                description={
                    "native_runner_catalog": "Read pinned samples and existing Runner controls.",
                    "native_runner_vm_status": "Read VM/owned-lease state without starting it.",
                    "native_runner_start": "Start the pinned VM inside an Owner run window.",
                    "native_runner_stop": "Stop only the VM incarnation owned by this connection.",
                    "native_runner_submit": "Submit a bounded job to the existing Native Runner.",
                    "native_runner_status": "Read job status without restart or resubmission.",
                    "native_runner_result": "Read an immutable Runner export in bounded chunks.",
                }[name],
                inputSchema={
                    "type": "object",
                    "properties": props,
                    "required": list(props),
                    "additionalProperties": False,
                },
                annotations=types.ToolAnnotations(
                    readOnlyHint=name
                    in {
                        "native_runner_catalog",
                        "native_runner_vm_status",
                        "native_runner_status",
                        "native_runner_result",
                    },
                    destructiveHint=False,
                    openWorldHint=False,
                ),
                _meta={
                    "securitySchemes": [
                        {
                            "type": "oauth2",
                            "scopes": [READ_SCOPE]
                            + (
                                [EXECUTE_SCOPE]
                                if name
                                in {
                                    "native_runner_submit",
                                    "native_runner_start",
                                    "native_runner_stop",
                                }
                                else []
                            ),
                        }
                    ]
                },
            )
            for name, props in TOOLS.items()
        ]

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=tools)

    async def call_tool(ctx, params):
        if native_actions is not None:
            from mcp.server.auth.middleware.auth_context import get_access_token

            token = get_access_token()
            try:
                result = await anyio.to_thread.run_sync(
                    native_actions.call,
                    token,
                    params.name,
                    params.arguments or {},
                )
            except (ValueError, OSError):
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text="native_runner_request_rejected")],
                    isError=True,
                )
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(result))],
                structuredContent=result,
            )
        # Manual validation keeps SDK/jsonschema errors from reflecting supplied
        # argument values. In particular vm_start never reaches a GCP client.
        if params.name != "vm_status" or params.arguments not in (None, {}):
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="tool_or_arguments_not_allowed")],
                isError=True,
            )
        try:
            result = await anyio.to_thread.run_sync(status_reader)
        except StatusUnavailable:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="vm_status_unavailable")], isError=True
            )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result))],
            structuredContent=result,
        )

    server = Server(
        "JewelAI VM Status", version="1.0.0", on_list_tools=list_tools, on_call_tool=call_tool
    )
    host = urlsplit(config.resource_url).netloc
    app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        max_request_body_size=32_768,
        auth=AuthSettings(
            issuer_url=config.issuer_url,
            resource_server_url=config.resource_url,
            required_scopes=[required_scope],
            validate_token_resource=True,
            client_registration_options=(
                ClientRegistrationOptions(enabled=False, valid_scopes=[READ_SCOPE, EXECUTE_SCOPE])
                if auth_provider
                else None
            ),
            revocation_options=RevocationOptions(enabled=True) if auth_provider else None,
        ),
        token_verifier=verifier,
        auth_server_provider=auth_provider,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[host, host + ":443"], allowed_origins=["https://" + host]
        ),
    )
    if native_actions is not None:
        from mcp.server.auth.routes import create_protected_resource_routes

        app.routes[:] = [
            r for r in app.routes if not r.path.startswith("/.well-known/oauth-protected-resource")
        ]
        app.routes.extend(
            create_protected_resource_routes(
                resource_url=AnyHttpUrl(config.resource_url),
                authorization_servers=[AnyHttpUrl(config.issuer_url)],
                scopes_supported=[READ_SCOPE, EXECUTE_SCOPE],
            )
        )
    return app


def main():
    import logging

    import uvicorn

    # No request headers, payloads, SDK debug traces or exception messages in
    # process logs. Cloud Run's platform request logs must also exclude headers.
    logging.disable(logging.CRITICAL)
    config = OAuthConfig(**json.loads(Path(os.environ["JEWELAI_MCP_OAUTH_CONFIG"]).read_text()))
    native_actions = None
    if os.environ.get("JEWELAI_NATIVE_RUNNER_CONFIG"):
        from native_llm_bench.contracts import keys, load, require

        from .backend import ManagedSecrets, NativeBackendAccess
        from .contracts import Inputs
        from .native_jobs import NativeRunnerActions

        path = Path(os.environ["JEWELAI_NATIVE_RUNNER_CONFIG"])
        require(path.stat().st_mode & 0o077 == 0, "private_native_config_required")
        native = load(path)
        keys(native, ("access", "corpus", "manifest", "guest_paths", "guest_verified"))
        access = NativeBackendAccess(native["access"], ManagedSecrets(native["access"]["gcloud"]))
        native_actions = NativeRunnerActions(
            access,
            Inputs(native["corpus"], native["manifest"]),
            native["guest_paths"],
            guest_ready=native["guest_verified"],
            refresh_approval=access._refresh,
        )
    app = create_app(config, native_actions=native_actions)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), access_log=False)


if __name__ == "__main__":
    main()
