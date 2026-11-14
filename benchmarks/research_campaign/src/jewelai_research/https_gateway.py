"""Official-SDK HTTPS MCP: authenticated read-only access to one existing VM.

No BackendAccess, tunnel credentials, shell, SSH, leases or VM mutation paths.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import anyio
from mcp import types
from mcp.server.auth.settings import AuthSettings
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings

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


def create_app(config: OAuthConfig, *, fetch=None, status_reader=None):
    verifier = OAuthTokenVerifier(config, **({"fetch": fetch} if fetch else {}))
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

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=[tool])

    async def call_tool(ctx, params):
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
    return server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        max_request_body_size=32_768,
        auth=AuthSettings(
            issuer_url=config.issuer_url,
            resource_server_url=config.resource_url,
            required_scopes=[STATUS_SCOPE],
            validate_token_resource=True,
        ),
        token_verifier=verifier,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[host, host + ":443"], allowed_origins=["https://" + host]
        ),
    )


def main():
    import logging

    import uvicorn

    # No request headers, payloads, SDK debug traces or exception messages in
    # process logs. Cloud Run's platform request logs must also exclude headers.
    logging.disable(logging.CRITICAL)
    config = OAuthConfig(**json.loads(Path(os.environ["JEWELAI_MCP_OAUTH_CONFIG"]).read_text()))
    app = create_app(config)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), access_log=False)


if __name__ == "__main__":
    main()
