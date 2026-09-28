# JewelAI authentication contracts

`jewelai-auth` defines the provider-neutral verified identity, JewelAI principal context,
organization membership roles, safe errors, and pure membership-management policy.

Identity is `(issuer, subject)`. Email and display name are metadata only. Organization access
roles (`owner`, `admin`, `member`) are unrelated to conversational Role Profiles.
Provider adapters may establish this identity from Auth0/OIDC access tokens or Google Identity
Platform ID tokens. In both cases PostgreSQL membership, not provider claims, authorizes tenants.

```bash
python -m pytest -c packages/auth/pyproject.toml packages/auth/tests -q
```
