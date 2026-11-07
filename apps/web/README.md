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

## Prompt Enrichment workspace (UI-PE-001)

After selecting an existing project, choose a conversation role and EN/RU language.
Starting a session now opens the conversation directly; session cards reopen it.
The main session route uses `/v1/sessions/{id}/prompt-enrichment/` with the existing
L/F and continuation command versions. It does not call legacy text-understanding,
evaluate, prompt-revision or generation endpoints. The existing visualization UI is
unchanged at `/organizations/{org}/sessions/{id}/visualization`, linked from the new
workspace. It is not required to use Prompt Enrichment.

The Owner-approved read-only `conversation` response contains existing persisted
messages/questions/decisions, canonical revision and state3 in one scoped snapshot.
Stored messages are not presented as accepted design facts. Reopening reads the
server again; there is no browser transcript store. Native F and admitted commands
carry the exact server-provided frame/hash/option IDs. Rejected requests retain the
draft, reload current state and require explicit retry rather than automatic replay.
Offered questions, Unknown/Skip, explicit continuation admission, protected-change
consent and supported dormant clarification resume use existing server contracts.

Update/Finish keep one in-flight command. After an acknowledged write, a failed
refresh offers a read-only retry and retains drafts while blocking duplicate writes.
Completion responses are reused only against the same authoritative conversation
frame; editing invalidates the previous Final Prompt without an unnecessary completion
read. Reload still fetches the saved completion from the server. Both Current Version
and the separate exact/copyable Final Prompt pane remain available.

Dormant questions are grouped under Previous clarifications with EN/RU names. Each
button still resumes its own server cause ID. Full parameter provenance remains
expandable; assumption values are not repeated in the policy-rationale list.

The result panel separates canonical values, missing/Unknown/unresolved information,
KEEP, LOCK and confirmed flags. Description and full copyable IFP are server output;
blocked/unavailable output shows the actual error. Advanced source/evidence details
are optional. New messages are bounded to 2,000 characters, within the existing
continuation request capacity. No client key, model credential, generation or catalog
activation is added. The API must already have its verified enrichment runtime
configured; the UI never enables it or substitutes a provider fallback. See
[ADR 0039](../../docs/adr/0039-prompt-enrichment-conversation-workspace.md).
