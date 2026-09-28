# JewelAI Identity Platform adapter

`jewelai-auth-identity-platform` verifies Google Cloud Identity Platform / Firebase ID tokens with
Google's supported `verify_firebase_token` implementation. It additionally requires the exact
`https://securetoken.google.com/{project_id}` issuer, project-ID audience, bounded lifetime and
authentication timestamps, and an exact non-empty subject before producing provider-neutral
`VerifiedIdentity`.

The adapter does not use email, hosted domain, or custom claims for JewelAI authorization.
PostgreSQL organization membership remains authoritative. Verification requires no service-account
JSON key.

```bash
python -m pytest -c packages/auth_identity_platform/pyproject.toml packages/auth_identity_platform/tests -q
```
