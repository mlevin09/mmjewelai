# JewelAI Web v1

React/TypeScript browser application for the authenticated JewelAI core workflow. Production keeps
its OAuth 2.0/OIDC Authorization Code + PKCE client. Preproduction uses the official Firebase Auth
SDK for Google Cloud Identity Platform, session-only persistence, and email/password sign-in. The
Firebase ID token is sent to the API as a bearer token. No client or service-account secret belongs
in browser configuration.

## Configuration

Copy `.env.example` to `.env.local` and set one provider's public values. OIDC registers exact
callback/logout URIs. Identity Platform requires its public API key, auth domain, project ID, and
app ID. The API must include the browser origin in `WEB_ALLOWED_ORIGINS`.

Production loads `/runtime-config.js` before the application bundle. The non-root nginx entrypoint
writes it from `JEWELAI_WEB_CONFIG_JSON`, so the API URL and public identity values can change
without rebuilding. Runtime values win over Vite development values and are strictly validated:
production URLs are HTTPS, scope contains `openid`, audience/client ID are non-empty, and unknown
fields (including secret fields) fail startup. The authorization request includes the API audience.

## Commands

```bash
npm ci
npm run dev
npm run typecheck
npm run lint
npm run format:check
npm test
npm run build
```

The production image serves `/health` directly, provides SPA fallback, does not cache runtime
config, caches hashed assets immutably, and emits CSP, HSTS, frame, referrer, and content-type
headers. It does not run Vite or contain a browser client secret.

The UI implements organization/project/session creation, deterministic question answering, prompt
creation, queued generation polling/retry, reference upload, and short-lived READY Asset access.
It does not contain provider credentials, authorization policy, business rules, or offline storage.
