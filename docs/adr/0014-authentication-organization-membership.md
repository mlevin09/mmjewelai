# ADR 0014: Authentication and organization membership

Status: Accepted for Authentication + Organization Membership v1. Date: 2026-09-25.

## Context

`X-Organization-ID` was introduced only as ownership plumbing and was never identity proof. The
internet-facing API now needs a verified identity and an authorization boundary at the existing
organization tenant. Conversational Role Profiles describe jewelry interactions, not permissions.
Signed Asset HTTP access was deliberately deferred until this boundary existed.

Authenticated signed Asset capability issuance is implemented separately by
[ADR 0015](0015-authenticated-signed-asset-http-access.md).

## Decision

JewelAI is an OAuth/OIDC resource server. It accepts externally issued bearer JWTs through a
provider-neutral `TokenVerifier` contract and ships a generic OIDC/JWKS adapter. Production
verification requires an explicitly configured issuer, audience, and HTTPS JWKS URL; allows only
configured asymmetric RS256/ES256 algorithms; and bounds token size, network timeout, cache TTL,
key refresh, and clock leeway. Token `jku` and `x5u` values are ignored.

The stable external identity is exactly `(issuer, subject)`. A JewelAI UUID principal persists that
pair plus optional verified email and display-name metadata. Email is never an identity or
authorization key. Tokens, raw claims, role/group/organization claims, and signatures are neither
persisted nor used for access decisions.

External `issuer` and `subject` identifiers are never canonicalized. Leading or trailing whitespace
is rejected rather than trimmed; accepted identifiers are persisted exactly.

Persist organization memberships with separate `owner`, `admin`, and `member` roles. All three may
use normal product functionality. Owners manage every membership role; admins may list memberships
and add/remove members only; members cannot manage memberships. Owner deletion/demotion locks the
organization row before checking other owners, so concurrent mutations cannot remove the final
owner.

All product routes require authentication; `/health` remains public. Organization creation and its
creator OWNER membership commit atomically. On routes without an organization path,
`X-Organization-ID` remains only the authenticated tenant selector. Membership is read from the
database on each request before existing scoped repository checks. Existing membership-less
organizations receive no automatic owner.

## Alternatives rejected

- Trusting `X-Organization-ID`, email, or JWT role/group/tenant claims.
- Local passwords, token persistence, refresh sessions, or an auth-disabled fallback.
- Embedding one identity provider in the API or accepting token-controlled key URLs.
- Project/session ACLs, invitations, ownership claims for old organizations, and user search.
- Bundling frontend OAuth, signed Asset access, or worker/service authentication into this change.

## Consequences

The API requires a valid external token and current database membership. Membership revocation is
effective on the next request. Old organizations require an explicit trusted administrative
backfill if retained. Frontend login, invitations, worker identity, and signed Asset HTTP access
remain separate work. Conversational roles remain independent from authorization roles.

## Validation

Auth policy, local cryptographic JWT/JWKS, persistence, API, PostgreSQL concurrency, migration,
regression, lint, format, and schema-drift suites run in Runtime API CI without contacting an
identity provider.
