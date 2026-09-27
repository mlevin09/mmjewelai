# ADR 0020: Web OIDC and core workflow boundary

Status: Accepted for Frontend Application + OIDC Login + Core Workflow UI v1. Date: 2026-09-27.

## Context

The deterministic contracts and authenticated runtime API now support the first complete user
workflow, but no browser application exists. The browser must use the external identity boundary in
ADR 0014 without learning provider, storage, or authorization internals. It also needs safe,
bounded translation from Question Catalog answer contracts into explicit revision edits.

## Decision

Use a React/TypeScript/Vite single-page public client. `oidc-client-ts` performs Authorization Code
+ PKCE against explicitly configured OIDC endpoints. Tokens use `sessionStorage`; only the access
token is sent as a bearer token. The browser stores no client secret, provider credential, signed
Asset URL, or domain state in durable local storage. A 401 clears the local OIDC user and returns to
login; 403 and 404 remain ordinary scoped application errors.

The API publishes non-secret roles/locales and generation-profile summaries from its configured
runtime registry. Project/session list and dictionary-option endpoints remain membership and tenant
scoped. Exact-origin CORS is configured by `WEB_ALLOWED_ORIGINS`; wildcard, credentialed CORS, and
insecure production origins are rejected.

Question answers use one explicit allowlist for the five v1 targets. The UI creates a source
message, constructs an `Explicit` state with that provenance, then submits the complete proposed
Design through the existing EDIT/CAS path. It does not interpret arbitrary paths, evaluate rules,
apply DERIVE/ASSUME proposals, or retry stale writes. Generation uses only prompt revision and
configured profile IDs. Signed READY Asset URLs are requested on demand for five minutes and held
only in component memory.

## Alternatives considered

- Server-side web sessions or a backend-for-frontend: deferred; the accepted API is already an OIDC
  resource server and a PKCE public client is sufficient for v1.
- Persisting access tokens in `localStorage`: rejected because it unnecessarily lengthens browser
  credential lifetime.
- Mirroring dictionary, role, rules, or generation configuration in frontend constants: rejected
  because pinned server artifacts and configuration remain authoritative.
- Generic JSON-path question mutation: rejected because it would create a second unbounded domain
  transition language in the browser.

## Consequences

OIDC redirect URIs and exact API CORS origins require deployment configuration. Organization cache
keys are tenant-scoped and cleared on switching away. Browser refresh loses ephemeral signed URLs,
as intended. The v1 UI has no invitation/membership administration, background notification,
offline mode, provider configuration, or client-side authorization policy.

## Validation

Web CI installs from the npm lockfile and runs strict TypeScript, ESLint, Prettier, Vitest, and a
production build. Runtime CI independently verifies API authentication, ownership, CORS, artifact
catalog responses, PostgreSQL behavior, migrations, and all deterministic package regressions.
