"""Offline composition only. Serving requires explicit private state and authentication."""

import argparse
import hashlib
import os
import signal
import threading

from native_llm_bench.contracts import InvalidArtifact, canonical, load, require

from .contracts import Inputs
from .controller import Controller
from .lifecycle import SyntheticLab
from .mcp import LocalToken, OAuthIntrospection, server
from .synthetic import SyntheticTransport, envelope
from .worker import Worker


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("init-synthetic", "activate", "serve", "worker", "report"))
    p.add_argument("--store", required=True, help="Private directory outside Git")
    p.add_argument("--corpus", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--evaluator", help="Optional read-only byte hash pin, never sent to model")
    p.add_argument("--campaign", default="SYNTHETIC_CAMPAIGN")
    p.add_argument("--subject", default="synthetic-researcher")
    p.add_argument("--envelope", help="Trusted local operator file; never an MCP tool argument")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--auth", choices=("local-synthetic", "oauth"), default="local-synthetic")
    p.add_argument("--resource", help="Reviewed external HTTPS resource URL ending /mcp")
    p.add_argument("--issuer")
    p.add_argument("--introspection-endpoint")
    args = p.parse_args()
    try:
        inputs = Inputs(args.corpus, args.manifest, args.evaluator)
        c = Controller(args.store, inputs)
        if args.command in ("init-synthetic", "activate"):
            e = (
                load(args.envelope)
                if args.command == "activate"
                else envelope(inputs, campaign_id=args.campaign, subject=args.subject)
            )
            print(canonical(c.activate(e)).decode())
        elif args.command == "serve":
            if args.auth == "local-synthetic":
                token = os.environ.get("JEWELAI_RESEARCH_LOCAL_TOKEN", "")
                require(len(token) >= 32, "private_random_token_required")
                verifier = LocalToken(hashlib.sha256(token.encode()).hexdigest(), args.subject)
            else:
                require(args.resource and args.resource.endswith("/mcp"), "resource_required")
                client_id = os.environ.get("JEWELAI_RESEARCH_OAUTH_CLIENT_ID", "")
                secret = os.environ.get("JEWELAI_RESEARCH_OAUTH_CLIENT_SECRET", "")
                require(
                    client_id and secret and args.issuer and args.introspection_endpoint,
                    "oauth_configuration_required",
                )
                verifier = OAuthIntrospection(
                    args.introspection_endpoint, args.issuer, args.resource, client_id, secret
                )
            s = server(c, verifier, port=args.port, resource=args.resource, issuer=args.issuer)
            try:
                s.serve_forever()
            finally:
                s.server_close()
        elif args.command == "worker":
            with c.ledger.connect() as db:
                require(
                    c.state(db, args.campaign)["envelope"]["mode"] == "SYNTHETIC",
                    "live_worker_not_authorized",
                )
            stop = threading.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: stop.set())
            Worker(c, SyntheticLab(), SyntheticTransport()).serve(args.campaign, stop=stop)
        else:
            print(c.verify_report(args.campaign).decode())
    except InvalidArtifact:
        p.exit(2, "Campaign configuration/request rejected; no credentials or raw error emitted.\n")


if __name__ == "__main__":
    main()
