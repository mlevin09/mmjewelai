"""SDK OAuth/PKCE provider using the existing Identity Platform, on the control host.

No Google OAuth client, user, password store, external IdP or research controller.
Only hashed bearer credentials are stored. Browser passwords go directly to Google.
"""

import contextlib
import hashlib
import html
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlencode

import anyio
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from mcp.server.auth.provider import AccessToken, AuthorizationCode, RefreshToken, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.responses import HTMLResponse, JSONResponse

from .native_jobs import EXECUTE_SCOPE, READ_SCOPE

CLIENT = "jewelai-research-agent"
CALLBACK = "https://chatgpt.com/connector_platform_oauth_redirect"
SCOPES = [READ_SCOPE, EXECUTE_SCOPE]


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


class WorkspaceAuth:
    def __init__(self, root, origin, project, owner_uid, browser_key, *, verify=None):
        self.origin, self.resource = origin, origin + "/mcp"
        self.project, self.owner_uid, self.browser_key = project, owner_uid, browser_key
        self.verify = verify or self._firebase
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if root.stat().st_mode & 0o077 or root.is_symlink():
            raise ValueError("private_auth_state_required")
        self.path = root / "oauth.sqlite3"
        if not self.path.exists():
            os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        if self.path.is_symlink() or self.path.stat().st_mode & 0o077:
            raise ValueError("private_auth_state_required")
        with self.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS credentials "
                "(key TEXT PRIMARY KEY, kind TEXT, body TEXT)"
            )

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _put(self, db, raw, kind, body):
        db.execute("INSERT INTO credentials VALUES (?,?,?)", (hashed(raw), kind, json.dumps(body)))

    def _get(self, db, raw, kind):
        if not isinstance(raw, str) or len(raw) > 4096:
            return None
        row = db.execute(
            "SELECT body FROM credentials WHERE key=? AND kind=?", (hashed(raw), kind)
        ).fetchone()
        value = json.loads(row[0]) if row else None
        return value if value and value["expires_at"] > time.time() else None

    def _firebase(self, raw):
        claims = id_token.verify_firebase_token(raw, GoogleRequest(), audience=self.project)
        if (
            claims.get("sub") != self.owner_uid
            or claims.get("iss") != "https://securetoken.google.com/" + self.project
        ):
            raise ValueError("research_identity_not_allowed")
        if time.time() - claims.get("auth_time", 0) > 300:
            raise ValueError("fresh_sign_in_required")
        return claims["sub"]

    async def get_client(self, client_id):
        if client_id == CLIENT:
            return OAuthClientInformationFull(
                client_id=CLIENT,
                client_name="JewelAI — AI Research Agent",
                redirect_uris=[CALLBACK],
                token_endpoint_auth_method="none",
                scope=" ".join(SCOPES),
                grant_types=["authorization_code", "refresh_token"],
            )
        return None

    async def register_client(self, client_info):
        raise ValueError("registration_disabled")

    async def authorize(self, client, params):
        if (
            params.resource != self.resource
            or not params.scopes
            or not set(params.scopes) <= set(SCOPES)
        ):
            from mcp.server.auth.provider import AuthorizeError

            raise AuthorizeError(
                error="invalid_scope", error_description="Research resource/scopes required"
            )
        ticket = secrets.token_urlsafe(32)
        body = {
            **params.model_dump(mode="json"),
            "client_id": client.client_id,
            "expires_at": time.time() + 300,
        }
        with self.db() as db:
            db.execute(
                "DELETE FROM credentials WHERE json_extract(body,'$.expires_at') <= ?",
                (time.time(),),
            )
            if (
                db.execute("SELECT count(*) FROM credentials WHERE kind='pending'").fetchone()[0]
                >= 128
            ):
                raise ValueError("authorization_busy")
            self._put(db, ticket, "pending", body)
        # Fragment stays in the browser: no authorization ticket in platform URL logs.
        return self.origin + "/consent#" + ticket

    async def consent(self, request):
        csrf = secrets.token_urlsafe(32)
        # No SDK/CDN dependency or browser storage. Firebase receives the password,
        # this host receives only a short-lived ID token after explicit consent.
        page = """<!doctype html><html><head><meta name="referrer" content="no-referrer"><title>JewelAI Research Access</title></head>
<body><h1>Authorize JewelAI Research Agent</h1><p>Sign in with your existing JewelAI Studio account.</p>
<p>Allows bounded Native Runner jobs on the research VM. Does not authorize paid starts or change the run budget.</p>
<form id="f"><label>Email <input id="email" type="email" autocomplete="username" required></label>
<label>Password <input id="password" type="password" autocomplete="current-password" required></label>
<button>Sign in and authorize Runner</button></form><p id="msg"></p>
<script nonce="NONCE">const cfg=CONFIG;cfg.ticket=location.hash.slice(1);history.replaceState(null,'','/consent');
document.getElementById('f').onsubmit=async(e)=>{e.preventDefault();
document.getElementById('msg').textContent='Authorizing…';try{
const r=await fetch('https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key='+encodeURIComponent(cfg.key),{
method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:document.getElementById('email').value,password:document.getElementById('password').value,returnSecureToken:true})});
document.getElementById('password').value='';if(!r.ok)throw Error();const v=await r.json();
const a=await fetch('/consent',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket:cfg.ticket,csrf:cfg.csrf,id_token:v.idToken})});
if(!a.ok)throw Error();location.replace((await a.json()).redirect);
}catch{document.getElementById('msg').textContent='Authorization failed. Check account or restart the connection.';}};</script></body></html>"""  # noqa: E501
        nonce = secrets.token_urlsafe(24)
        config = json.dumps({"key": self.browser_key, "csrf": csrf}).replace("<", "\\u003c")
        page = page.replace("CONFIG", config).replace("NONCE", html.escape(nonce))
        response = HTMLResponse(
            page,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; script-src 'nonce-"
                + nonce
                + "'; connect-src 'self' https://identitytoolkit.googleapis.com; "
                "form-action 'none'; frame-ancestors 'none'; base-uri 'none'",
            },
        )
        response.set_cookie(
            "research-consent",
            csrf,
            max_age=300,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/consent",
        )
        return response

    async def confirm(self, request):
        if request.headers.get("origin") != self.origin:
            return JSONResponse({"error": "authorization_rejected"}, status_code=403)
        try:
            data = await request.json()
            ticket, csrf = data["ticket"], data["csrf"]
            if not isinstance(csrf, str) or not secrets.compare_digest(
                csrf, request.cookies.get("research-consent", "")
            ):
                raise ValueError("csrf")
            with self.db() as db:
                pending = self._get(db, ticket, "pending")
                if not pending:
                    raise ValueError("csrf")
            uid = await anyio.to_thread.run_sync(self.verify, data["id_token"])
            if uid != self.owner_uid:
                raise ValueError("identity")
            code = secrets.token_urlsafe(32)
            body = {k: v for k, v in pending.items() if k not in {"csrf", "state"}}
            body.update(subject=uid, expires_at=time.time() + 60)
            with self.db() as db:
                if (
                    db.execute(
                        "DELETE FROM credentials WHERE key=? AND kind='pending'", (hashed(ticket),)
                    ).rowcount
                    != 1
                ):
                    raise ValueError("authorization_already_used")
                self._put(db, code, "code", body)
            query = {"code": code, "iss": self.origin + "/"}
            if pending["state"] is not None:
                query["state"] = pending["state"]
            response = JSONResponse(
                {"redirect": str(pending["redirect_uri"]) + "?" + urlencode(query)}
            )
            response.delete_cookie("research-consent", path="/consent")
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception:
            return JSONResponse({"error": "authorization_rejected"}, status_code=403)

    async def load_authorization_code(self, client, authorization_code):
        with self.db() as db:
            body = self._get(db, authorization_code, "code")
        return (
            AuthorizationCode(code=authorization_code, **body)
            if body and body["client_id"] == client.client_id
            else None
        )

    def _issue(self, db, body, scopes):
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        common = {k: body[k] for k in ("client_id", "subject", "resource")}
        common.update(scopes=scopes, family=body.get("family", secrets.token_urlsafe(32)))
        self._put(db, access, "access", {**common, "expires_at": int(time.time()) + 600})
        self._put(db, refresh, "refresh", {**common, "expires_at": int(time.time()) + 86400 * 7})
        return OAuthToken(
            access_token=access, refresh_token=refresh, expires_in=600, scope=" ".join(scopes)
        )

    async def exchange_authorization_code(self, client, authorization_code):
        with self.db() as db:
            body = self._get(db, authorization_code.code, "code")
            if (
                not body
                or body["client_id"] != client.client_id
                or body["resource"] != self.resource
            ):
                raise TokenError(error="invalid_grant")
            db.execute("DELETE FROM credentials WHERE key=?", (hashed(authorization_code.code),))
            return self._issue(db, body, body["scopes"])

    async def load_refresh_token(self, client, refresh_token):
        with self.db() as db:
            body = self._get(db, refresh_token, "refresh")
        return (
            RefreshToken(token=refresh_token, **body)
            if body and body["client_id"] == client.client_id
            else None
        )

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        with self.db() as db:
            body = self._get(db, refresh_token.token, "refresh")
            if (
                not body
                or body["client_id"] != client.client_id
                or not set(scopes) <= set(body["scopes"])
            ):
                raise TokenError(error="invalid_grant")
            db.execute(
                "DELETE FROM credentials WHERE json_extract(body,'$.family')=?", (body["family"],)
            )
            return self._issue(db, body, scopes)

    async def load_access_token(self, token):
        with self.db() as db:
            body = self._get(db, token, "access")
        if body and body["resource"] == self.resource and body["subject"] == self.owner_uid:
            return AccessToken(token=token, **body)
        return None

    async def revoke_token(self, token):
        with self.db() as db:
            for kind in ("access", "refresh"):
                body = self._get(db, token.token, kind)
                if body:
                    db.execute(
                        "DELETE FROM credentials WHERE json_extract(body,'$.family')=?",
                        (body["family"],),
                    )

    async def metadata(self, request):
        return JSONResponse(
            {
                "issuer": self.origin + "/",
                "authorization_endpoint": self.origin + "/authorize",
                "token_endpoint": self.origin + "/token",
                "revocation_endpoint": self.origin + "/revoke",
                "scopes_supported": SCOPES,
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
                "authorization_response_iss_parameter_supported": True,
            }
        )

    async def revocation(self, request):
        # SDK 2.3's RevocationRequest incorrectly requires client_secret even for
        # public PKCE clients. Keep RFC7009 public-client revocation without one.
        form = await request.form()
        if form.get("client_id") != CLIENT or form.get("client_secret"):
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        raw = form.get("token", "")
        client = await self.get_client(CLIENT)
        token = await self.load_access_token(raw) or await self.load_refresh_token(client, raw)
        if token:
            await self.revoke_token(token)
        return JSONResponse({}, headers={"Cache-Control": "no-store"})
