# JewelAI OIDC adapter

`jewelai-auth-oidc` verifies externally issued asymmetric JWTs against one explicitly configured
HTTPS JWKS endpoint. It validates issuer, audience, subject, expiration and signature, applies
bounded leeway, and returns only a provider-neutral `VerifiedIdentity`.

Defaults: RS256, 5-second HTTP timeout, 300-second in-memory JWKS TTL, 30-second leeway, and a
16-KiB token limit. Token-controlled `jku`/`x5u` URLs are ignored. No token or raw claims are
persisted.

Production uses Terraform-managed resources inside an existing Auth0 tenant: an RS256 Resource
Server whose identifier exactly equals `OIDC_AUDIENCE`, an OIDC-conformant SPA with exact HTTPS
callback/logout/origin values, and a controlled database connection. The browser uses Authorization
Code + PKCE without a secret. Auth0 identity does not grant JewelAI owner/admin/member authority;
database membership remains authoritative.

```bash
python -m pytest -c packages/auth_oidc/pyproject.toml packages/auth_oidc/tests -q
```
