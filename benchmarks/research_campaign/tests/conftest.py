import hashlib
import http.client
import json
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from jewelai_research.contracts import Inputs
from jewelai_research.controller import Controller
from jewelai_research.lifecycle import SyntheticLab
from jewelai_research.mcp import LocalToken, Principal, server
from jewelai_research.synthetic import SyntheticTransport, envelope
from jewelai_research.worker import Worker

FIXTURES = Path(__file__).parents[2] / "native_llm_stage1" / "fixtures"


@pytest.fixture
def campaign(tmp_path):
    runtime = tmp_path / "runtime.json"
    manifest = tmp_path / "model.json"
    evaluator = tmp_path / "gold.private.json"
    shutil.copyfile(FIXTURES / "synthetic.runtime.json", runtime)
    shutil.copyfile(FIXTURES / "synthetic.model.json", manifest)
    evaluator.write_text('{"gold":"NEVER_IN_MODEL_PAYLOAD","status":"REVIEW_REQUIRED"}')
    inputs = Inputs(runtime, manifest, evaluator)
    clock = [2_000_000_000]
    c = Controller(tmp_path / "private", inputs, clock=lambda: clock[0])
    e = envelope(inputs, clock=lambda: clock[0])
    principal = Principal(e["subject"], frozenset(("campaign.read", "campaign.execute")))
    c.activate(e)
    lab, model = SyntheticLab(), SyntheticTransport()
    return SimpleNamespace(
        c=c,
        inputs=inputs,
        envelope=e,
        principal=principal,
        lab=lab,
        model=model,
        worker=Worker(c, lab, model),
        clock=clock,
    )


def hypothesis(*evidence):
    return {
        "statement": "Completion may improve under a controlled treatment.",
        "alternatives": ["Truncation rather than instruction wording is causal."],
        "primary_variable": "sealed profile",
        "falsification": "No additional completed turns",
        "rationale": "Synthetic evidence only; no professional score.",
        "evidence_experiments": list(evidence),
    }


def register(f, eid="E1", profile="NATIVE_CONTROL_V1", sessions=None, evidence=()):
    return f.c.call(
        f.principal,
        "propose_and_register_experiment",
        {
            "campaign_id": f.envelope["campaign_id"],
            "idempotency_key": "register-" + eid,
            "experiment_id": eid,
            "profile": profile,
            "sessions": sessions or ["SYN2"],
            "hypothesis": hypothesis(*evidence),
        },
    )


def queue(f, eid="E1"):
    return f.c.call(
        f.principal,
        "execute_registered_experiment",
        {
            "campaign_id": f.envelope["campaign_id"],
            "idempotency_key": "execute-" + eid,
            "experiment_id": eid,
        },
    )


@pytest.fixture
def wire(campaign):
    token = "synthetic-test-token-not-a-live-credential"
    auth = LocalToken(hashlib.sha256(token.encode()).hexdigest(), campaign.principal.subject)
    s = server(campaign.c, auth)
    thread = threading.Thread(target=s.serve_forever, daemon=True)
    thread.start()
    counter = [0]

    def rpc(method, params=None, *, bearer=token, headers=None, message=None):
        counter[0] += 1
        body = message or {
            "jsonrpc": "2.0",
            "id": counter[0],
            "method": method,
            "params": params or {},
        }
        conn = http.client.HTTPConnection("127.0.0.1", s.server_port, timeout=10)
        h = {
            "Authorization": "Bearer " + bearer,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }
        h.update(headers or {})
        conn.request("POST", "/mcp", json.dumps(body), h)
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        return r.status, json.loads(raw) if raw else None

    yield SimpleNamespace(rpc=rpc, port=s.server_port)
    s.shutdown()
    thread.join(timeout=5)
    s.server_close()
