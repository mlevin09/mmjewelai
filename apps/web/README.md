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

Center-stone measurements are submitted as explicitly owned `length x width x depth mm`
text through the current Parser, not as independently labelled values it cannot apply.
The existing Dimensions contract requires all three positive measurements; incomplete
or invalid input stays in the draft with a clear error. Skip/Unknown save only that
explicit decision, without silently submitting any draft measurements or preferences.

The result panel separates canonical values, missing/Unknown/unresolved information,
KEEP, LOCK and confirmed flags. Description and full copyable IFP are server output;
blocked/unavailable output shows the actual error. Advanced source/evidence details
are optional. New messages are bounded to 2,000 characters, within the existing
continuation request capacity. No client key, model credential, generation or catalog
activation is added. The API must already have its verified enrichment runtime
configured; the UI never enables it or substitutes a provider fallback. See
[ADR 0039](../../docs/adr/0039-prompt-enrichment-conversation-workspace.md).

## ST-01 opt-in text pilot (coordinator UI)

A new session pinned to questions/rules `2.0.0` offers **Open text-only first-turn
pilot**. This is a separate explicit choice, not a rerouting of guided fields.
The pilot sends the exact textarea text to its opt-in `first-turn/messages`
endpoint (schema `1.0.0`, current revision and content), which preserves it without
trimming in the existing Message store. The separate DTO rejects whitespace-only
text and limits the complete original input to 2,000 characters, matching the
current Parser and UI. Tenant/session, retained F profile and fresh initial state
are checked before the locked Message insert; stale revisions or initialized
sessions cannot append through this route. The pilot then calls the versioned
`first-turn` route with that Message ID and the current revision. Legacy `/messages`
keeps its original trimming and 4,000-character contract. The pilot never adds
creation wording, center-stone placement or structured choices to the text.
The existing guided/legacy command paths remain unchanged.

A saved first-turn receipt reopens the pilot automatically. The server's immutable
reply is displayed verbatim with a **fallback mode** label; it is not a model reply.
The source Message is displayed separately, and a non-current receipt is labelled
historical rather than substituted for current State. Reload reads the receipt and
conversation again, without generating an answer. An absent route/receipt is
compatible with legacy sessions; authorization or verification errors are not
silently treated as absence.

The saved-source panel displays only the referenced Message returned by the
conversation read. If readback fails after a successful POST, the source is marked
unavailable; any retained local input is shown separately as an **unverified local
draft**. A POST receipt is never used to relabel the textarea as verified source.
**View current state and history** reloads the existing workspace and opens its
saved history, including corrections made after the receipt. An explicit return
button reopens the retained first-turn reply with its historical label. Viewing
either side does not submit a command or change the saved receipt. Subsequent
workspace refreshes respect the current-view choice until the session is remounted.

Submission is guarded against repeated clicks. After an uncertain attempt the
same mounted pilot does not blindly create another Message; the retained input
and an explicit read-only reload remain available. There is no durable client
retry/recovery protocol in this change. No clarification, continuation, final
confirmation or provider call is exposed within this pilot. Dropdown/mixed-input,
voice and natural-model acceptance are not established by these UI tests.

Targeted UI contract tests use MSW and jsdom in `FirstTurnPilot.test.tsx`, plus the
existing workspace and App suites. They are not live-browser/backend acceptance.
The final combined PR HEAD still needs independent review, exact-head CI and a
real isolated browser/API lifecycle check before functional acceptance.
