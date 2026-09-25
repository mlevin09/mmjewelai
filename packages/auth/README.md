# JewelAI authentication contracts

`jewelai-auth` defines the provider-neutral verified identity, JewelAI principal context,
organization membership roles, safe errors, and pure membership-management policy.

Identity is `(issuer, subject)`. Email and display name are metadata only. Organization access
roles (`owner`, `admin`, `member`) are unrelated to conversational Role Profiles.

```bash
python -m pytest -c packages/auth/pyproject.toml packages/auth/tests -q
```
