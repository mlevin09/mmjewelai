# JewelAI Web v1

React/TypeScript browser application for the authenticated JewelAI core workflow. It is an OAuth
2.0/OIDC public client using Authorization Code + PKCE. Access tokens are held by `oidc-client-ts`
in `sessionStorage`; ID tokens are never sent to the API and no client secret belongs in browser
configuration.

## Configuration

Copy `.env.example` to `.env.local` and set the public values. The OIDC application must register
the exact callback and post-logout URIs. The API must include the browser origin in
`WEB_ALLOWED_ORIGINS`.

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

The UI implements organization/project/session creation, deterministic question answering, prompt
creation, queued generation polling/retry, reference upload, and short-lived READY Asset access.
It does not contain provider credentials, authorization policy, business rules, or offline storage.
