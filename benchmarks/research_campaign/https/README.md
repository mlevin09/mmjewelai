# Read-only HTTPS MCP gateway

This first slice exposes **only `vm_status`** for the existing pinned research VM.
It uses the official Python MCP SDK 2.3.0 and Streamable HTTP at `/mcp`. It never
instantiates `BackendAccess`, reads a Tunnel/SSH secret, writes a lease, executes
a shell, starts/stops a VM or accesses the application database. Existing seven
tools and persistent control-host state are unchanged. No benchmark logic runs.

## Current release status

Implemented and tested locally, **NOT DEPLOYED / AGENT NOT CONNECTED**. Offline
test keys/issuer metadata prove protocol and rejection paths, not live OAuth.
No actual Agent invocation or production OAuth exchange is claimed.

The existing product Identity Platform ID-token issuer's public discovery was
inspected. It has a JWT issuer/JWKS but does **not** advertise authorization or
token endpoints, authorization-code/PKCE support or client registration. The
Google Accounts issuer is also not a substitute: its ordinary Google API access
tokens do not establish this MCP resource's audience, custom scope and client
binding. No compatible, registered MCP authorization server is currently verified.

**One blocking dependency:** an approved real OAuth authorization server/client
configuration for this MCP resource. Its administrator must provide the non-secret
issuer/discovery URL, registered client ID and exact callback from the existing
Agent's connection form; enable authorization code + S256; issue signed RS256
**access tokens** with the exact MCP URL as `aud`, scope
`jewelai.research.vm.status`, and the registered `client_id` (or `azp`); identify
the authorized Owner subject(s). Register only that callback, with no wildcard.
If the shared ChatGPT callback is used, RFC 9207 issuer identification must be
advertised **and returned by the real authorization server**. Otherwise use the
specific callback shown by ChatGPT. Discovery alone cannot verify registration,
consent, returned `iss`, or a complete browser exchange.

The resource server does not implement a fake authorization server, proxy Google
tokens, accept a static bearer credential, or require an OpenAI Platform key.
It deliberately supports **pre-registered clients**; DCR/CIMD are not simulated.
The issuer performs client registration, consent, PKCE/code verification, refresh
and callback handling. If a confidential client is required, provision its secret
directly through the approved secret/account configuration, never in chat or Git.
The resource server needs only public JWKS and non-secret configuration.

## Configuration and execution

Install local packages with the isolated optional dependency profile:

```sh
python -m pip install ./benchmarks/native_llm_stage1 './benchmarks/research_campaign[https]'
```

`JEWELAI_MCP_OAUTH_CONFIG` must name a read-only JSON file containing these fields:

| Field | Meaning |
| --- | --- |
| `resource_url` | Actual stable HTTPS gateway URL ending exactly in `/mcp`; access-token audience |
| `issuer_url` | Exact discovery/token issuer, including its actual trailing slash |
| `discovery_url` | Public HTTPS issuer discovery document on that issuer's host |
| `client_id` | Actual pre-registered ChatGPT OAuth client, not an invented value |
| `allowed_subjects` | Nonempty list of approved issuer subject IDs |
| `callback_url` | Exact registered callback from the existing Agent connection form |
| `client_claim` | `client_id` (default) or the issuer's verified `azp` convention |

There is no default configuration or synthetic/live fallback. Startup validates
real discovery and fails closed. JWKS fetches are HTTPS-only, redirect-free,
size/time bounded and cached. Only RS256 keys of at least 2048 bits are admitted;
issuer, exact single audience, expiry, issued-at, subject and client are verified.
The SDK enforces scope before any tool call. Unknown tools/arguments never acquire
ADC or make a GCP request. The sole GCP adapter requests `compute.readonly` ADC
and performs one fixed instance GET with a field mask. Error payloads are bounded.
Process access/debug/exception logging is disabled; never enable payload/header
capture at a proxy/platform layer. No credentials belong in URLs/query strings.

Run `jewelai-research-https` only after real configuration is present. The process
listens on `PORT` (default 8080) behind managed TLS, without TLS bypass. Build the
prepared non-root image from the repository root using this directory's Dockerfile.
No Docker build or cloud deployment is claimed by local Python tests.

## Hosting boundary (not applied)

The simplest independent host is a **separate** request-billed Cloud Run service:
minimum 0, maximum 1, concurrency bounded, no VPC/NAT/LB or persistent VM, no
application service changes. Use its managed HTTPS hostname, pin Host/Origin to
that hostname, and protect `/mcp` with the OAuth resource-server middleware.
Cloud Run IAM unauthenticated invocation must allow the MCP client to reach that
middleware; this is not permission to execute unauthenticated GCP operations.
Use a new dedicated runtime identity with **only `compute.instances.get` bound to
the existing target instance**. No project-wide Viewer, start/stop, SSH, secret
access, service-account impersonation, deployer identity or application role.

The previous control-host identity is too powerful for this public read-only slice
and must not be reused. Existing approved control-host firewall/network/journal
state remains untouched. No gateway resource/IAM/deployment is created while the
real OAuth prerequisite is absent. No new resources or additional cloud spend
were incurred by this implementation. Scale-to-zero has no always-on VM charge;
future requests, builds, registry/log storage and any external IdP can still cost
money and require a bounded deployment authorization before provisioning.

## Bounded verification and final Agent step

```sh
python -m pytest -c benchmarks/research_campaign/pyproject.toml \
  benchmarks/research_campaign/tests/test_https_gateway.py \
  benchmarks/research_campaign/tests/test_vm_access.py \
  benchmarks/research_campaign/tests/test_backend.py \
  benchmarks/research_campaign/tests/test_ownership.py -q
```

After the real issuer is configured and reviewed hosting is deployed: check TLS,
public `/.well-known/oauth-protected-resource/mcp`, 401 challenge, real OAuth code
exchange, initialize/list/call, and one actual GCP `vm_status`. Then add that exact
verified `/mcp` URL with OAuth to the **existing** JewelAI Research Agent, authorize
its account connection and call `vm_status` in Preview. Do not create a new Agent.
Until that real call succeeds, connection acceptance remains **NOT VERIFIED**.

References: [OpenAI MCP](https://developers.openai.com/plugins/build/mcp-server),
[OAuth requirements](https://developers.openai.com/plugins/build/auth),
[official Python SDK](https://github.com/modelcontextprotocol/python-sdk).
