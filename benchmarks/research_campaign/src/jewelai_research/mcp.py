"""Stateless MCP Streamable HTTP (JSON responses). No shell or generic HTTP tools.

OAuth authorization server is external; this is a resource server, not an identity system.
All requests, including discovery of tool names, require verified identity. No raw access logs.
"""

import base64
import hashlib
import hmac
import http.client
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode, urlsplit

from native_llm_bench.contracts import InvalidArtifact, canonical, decode, require

from .contracts import PROFILES, VERSION
from .controller import READ, TOOLS

PROTOCOLS = ("2025-03-26", "2025-06-18", "2025-11-25")
READ_SCOPE, WRITE_SCOPE = "campaign.read", "campaign.execute"


@dataclass(frozen=True)
class Principal:
    subject: str
    scopes: frozenset[str]


class LocalToken:
    """Loopback offline test/developer access only; not ChatGPT OAuth configuration."""

    def __init__(self, token_sha256, subject):
        self.sha, self.subject = token_sha256, subject

    def verify(self, token):
        require(
            hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), self.sha),
            "unauthorized",
        )
        return Principal(self.subject, frozenset((READ_SCOPE, WRITE_SCOPE)))


class OAuthIntrospection:
    """Pinned HTTPS RFC7662 endpoint, no discovery from untrusted token/issuer claims.

    Credentials are server-side operator configuration; no token pass-through to GCP/Qwen.
    Require issuer, resource audience, expiry and subject. Inactive/unavailable fails closed.
    Provider must explicitly support resource-bound introspection before live hosting.
    """

    def __init__(self, endpoint, issuer, resource, client_id, client_secret, *, clock=time.time):
        u = urlsplit(endpoint)
        require(
            u.scheme == "https"
            and u.hostname
            and not u.username
            and not u.password
            and not u.fragment
            and not u.query,
            "invalid_introspection_endpoint",
        )
        require(
            resource.startswith("https://") and issuer.startswith("https://"),
            "https_resource_issuer_required",
        )
        self.url, self.issuer, self.resource = u, issuer, resource
        self.client_id, self.client_secret, self.clock = client_id, client_secret, clock

    def verify(self, token):
        connection = http.client.HTTPSConnection(self.url.hostname, self.url.port or 443, timeout=5)
        try:
            auth = base64.b64encode((self.client_id + ":" + self.client_secret).encode()).decode()
            connection.request(
                "POST",
                self.url.path or "/",
                urlencode({"token": token}),
                {
                    "Authorization": "Basic " + auth,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            response = connection.getresponse()
            raw = response.read(16385)
            require(response.status == 200 and len(raw) <= 16384, "unauthorized")
            return self.claims(decode(raw))
        except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError):
            raise InvalidArtifact("unauthorized") from None
        finally:
            connection.close()

    def claims(self, data):
        require(isinstance(data, dict) and data.get("active") is True, "unauthorized")
        audience = data.get("aud", [])
        if isinstance(audience, str):
            audience = [audience]
        require(
            data.get("iss") == self.issuer
            and isinstance(audience, list)
            and self.resource in audience,
            "unauthorized",
        )
        expiry = data.get("exp")
        require(type(expiry) in (int, float) and self.clock() < expiry, "unauthorized")
        require(isinstance(data.get("sub"), str) and bool(data["sub"]), "unauthorized")
        require(isinstance(data.get("scope"), str), "unauthorized")
        return Principal(data["sub"], frozenset(data["scope"].split()))


def tool_schema(name):
    string = {"type": "string", "minLength": 1, "maxLength": 4000}
    props = {"campaign_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$"}}
    if name not in READ:
        props["idempotency_key"] = {"type": "string", "maxLength": 80}
    if name in (
        "propose_and_register_experiment",
        "execute_registered_experiment",
        "get_experiment_results",
    ):
        props["experiment_id"] = {"type": "string", "maxLength": 80}
    if name == "propose_and_register_experiment":
        props.update(
            {
                "profile": {"type": "string", "enum": list(PROFILES)},
                "sessions": {"type": "array", "items": string, "minItems": 1, "uniqueItems": True},
                "hypothesis": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "statement": string,
                        "alternatives": {
                            "type": "array",
                            "items": string,
                            "minItems": 1,
                            "maxItems": 5,
                        },
                        "primary_variable": string,
                        "falsification": string,
                        "rationale": string,
                        "evidence_experiments": {"type": "array", "items": string},
                    },
                    "required": [
                        "statement",
                        "alternatives",
                        "primary_variable",
                        "falsification",
                        "rationale",
                        "evidence_experiments",
                    ],
                },
            }
        )
    if name == "list_ledger":
        props.update(
            {
                "offset": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            }
        )
    if name == "finalize_campaign":
        props["conclusion"] = string
    if name == "stop_campaign":
        props["reason"] = {"type": "string", "minLength": 1, "maxLength": 500}
    descriptions = {
        "campaign_status": "Use to recover the authorized campaign, limits, profiles and queue.",
        "propose_and_register_experiment": "Use after reviewing evidence. Register a falsifiable "
        "hypothesis and select a sealed experiment type/sample. Reserves full worst-case cost. "
        "No holdouts, gold writes, arbitrary prompts, commands or infrastructure parameters.",
        "execute_registered_experiment": "Queue one registered experiment. Returns quickly; "
        "durable worker executes independently. Poll results; do not blindly retry unknown work.",
        "get_experiment_results": "Read immutable raw runner evidence and measured counts. "
        "Evaluate hypotheses and choose the next experiment type within the same assignment. "
        "Professional quality remains REVIEW_REQUIRED, not a certified score.",
        "list_ledger": "Read append-only hypotheses, decisions and execution receipts; paginate.",
        "finalize_campaign": "After all work is terminal and shutdown verified, emit one immutable "
        "campaign report. Mark interpretations as hypotheses. Never claim synthetic is live.",
        "stop_campaign": "Emergency durable stop. Prevents new work and requests worker cleanup. "
        "Call campaign_status to verify shutdown; request acceptance is not verified cleanup.",
    }
    return {
        "name": name,
        "description": descriptions[name],
        "inputSchema": {
            "type": "object",
            "properties": props,
            "required": list(props),
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": name in READ,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "_meta": {
            "securitySchemes": [
                {"type": "oauth2", "scopes": [READ_SCOPE if name in READ else WRITE_SCOPE]}
            ]
        },
    }


def dispatch(controller, principal, message):
    require(isinstance(message, dict) and message.get("jsonrpc") == "2.0", "invalid_rpc")
    method, params = message.get("method"), message.get("params", {})
    require(isinstance(params, dict), "invalid_rpc_params")
    if method not in ("notifications/initialized", "notifications/cancelled"):
        require("id" in message and type(message["id"]) in (int, str), "missing_rpc_id")
    if method == "initialize":
        requested = params.get("protocolVersion")
        return {
            "protocolVersion": requested if requested in PROTOCOLS else PROTOCOLS[-1],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "jewelai-research-campaign", "version": VERSION},
            "instructions": "One campaign assignment; adapt experiment type from evidence, "
            "register then queue, poll results, preserve hypotheses, stop at limits and finalize. "
            "Unknown outcomes are charged; no blind retries. No gold changes or live activation.",
        }
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {}
    if method == "tools/list":
        require(READ_SCOPE in principal.scopes, "insufficient_scope")
        return {
            "tools": [tool_schema(t) for t in TOOLS if t in READ or WRITE_SCOPE in principal.scopes]
        }
    require(method == "tools/call", "unknown_method")
    require(set(params) == {"name", "arguments"}, "invalid_tool_parameters")
    result = controller.call(principal, params["name"], params["arguments"])
    return {
        "content": [{"type": "text", "text": canonical(result).decode()}],
        "structuredContent": result,
        "isError": False,
    }


def server(controller, verifier, *, port=0, resource=None, issuer=None, origins=(), hosts=()):
    # Local origin only. A reviewed HTTPS gateway/tunnel must forward a pinned Host value;
    # never trust X-Forwarded-* to select identities, issuers, resources or destinations.
    if isinstance(verifier, LocalToken):
        with controller.ledger.connect() as db:
            for (cid,) in db.execute("SELECT DISTINCT campaign FROM events"):
                require(
                    controller.state(db, cid)["envelope"]["mode"] == "SYNTHETIC",
                    "local_token_synthetic_only",
                )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def send(self, status, body=None, extra=None):
            payload = canonical(body) if body is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(payload)

        def allowed(self):
            expected = {f"127.0.0.1:{self.server.server_port}", *hosts}
            return self.headers.get("Host") in expected and (
                self.headers.get("Origin") is None or self.headers["Origin"] in origins
            )

        def do_GET(self):
            if not self.allowed():
                self.send(403)
            elif (
                self.path
                in (
                    "/.well-known/oauth-protected-resource",
                    "/.well-known/oauth-protected-resource/mcp",
                )
                and resource
                and issuer
            ):
                self.send(
                    200,
                    {
                        "resource": resource,
                        "authorization_servers": [issuer],
                        "scopes_supported": [READ_SCOPE, WRITE_SCOPE],
                        "bearer_methods_supported": ["header"],
                    },
                )
            else:
                self.send(405, extra={"Allow": "POST"})

        def do_POST(self):
            if self.path != "/mcp":
                self.send(404)
                return
            if not self.allowed():
                self.send(403)
                return
            try:
                auth = self.headers.get("Authorization", "")
                require(auth.startswith("Bearer ") and 0 < len(auth[7:]) <= 8192, "unauthorized")
                principal = verifier.verify(auth[7:])
            except (InvalidArtifact, OSError):
                challenge = 'Bearer error="invalid_token"'
                if resource:
                    challenge += (
                        ', resource_metadata="'
                        + resource.rsplit("/mcp", 1)[0]
                        + '/.well-known/oauth-protected-resource/mcp"'
                    )
                self.send(401, extra={"WWW-Authenticate": challenge})
                return
            if self.headers.get("MCP-Protocol-Version", "2025-03-26") not in PROTOCOLS:
                self.send(400)
                return
            if "application/json" not in self.headers.get(
                "Accept", ""
            ) or "text/event-stream" not in self.headers.get("Accept", ""):
                self.send(406)
                return
            message = None
            try:
                require(
                    self.headers.get("Content-Type", "").split(";")[0] == "application/json"
                    and not self.headers.get("Transfer-Encoding"),
                    "invalid_content_type",
                )
                length = int(self.headers.get("Content-Length", "0"))
                require(0 < length <= 65536, "request_too_large")
                message = decode(self.rfile.read(length))
                result = dispatch(controller, principal, message)
                if result is None:
                    self.send(202)
                else:
                    require("id" in message and type(message["id"]) in (int, str), "missing_rpc_id")
                    self.send(200, {"jsonrpc": "2.0", "id": message["id"], "result": result})
            except (InvalidArtifact, KeyError, TypeError, ValueError) as exc:
                rid = message.get("id") if isinstance(message, dict) else None
                # Only bounded local reason codes can escape. Provider/OS exceptions never do.
                code = str(exc) if isinstance(exc, InvalidArtifact) else "campaign_request_rejected"
                if code not in {
                    "campaign_budget_exhausted",
                    "campaign_deadline",
                    "campaign_closed",
                    "campaign_forbidden",
                    "insufficient_scope",
                    "idempotency_conflict",
                    "sample_not_authorized",
                    "profile_not_authorized",
                    "cleanup_not_verified",
                    "experiments_not_terminal",
                    "experiment_not_registered",
                }:
                    code = "campaign_request_rejected"
                self.send(
                    200, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": code}}
                )
            except Exception:
                self.send(500, {"error": "campaign_internal_error"})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
