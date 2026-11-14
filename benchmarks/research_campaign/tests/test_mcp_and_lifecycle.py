import copy
import http.client
import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from conftest import hypothesis
from native_llm_bench.contracts import InvalidArtifact

from jewelai_research.leases import LeaseJournal
from jewelai_research.lifecycle import ATTEST, GcpLab, PrivateTunnel
from jewelai_research.mcp import OAuthIntrospection, Principal, dispatch


def test_wire_auth_origin_host_protocol_and_missing_id_fail_without_mutation(campaign, wire):
    assert wire.rpc("tools/list", bearer="wrong")[0] == 401
    assert wire.rpc("tools/list", headers={"Origin": "https://attacker.invalid"})[0] == 403
    assert wire.rpc("tools/list", headers={"Host": "attacker.invalid"})[0] == 403
    assert wire.rpc("tools/list", headers={"MCP-Protocol-Version": "wrong"})[0] == 400
    assert wire.rpc("tools/list", headers={"Accept": "text/plain"})[0] == 406
    _, response = wire.rpc(
        "tools/call",
        message={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "propose_and_register_experiment",
                "arguments": {
                    "campaign_id": campaign.envelope["campaign_id"],
                    "idempotency_key": "k",
                    "experiment_id": "E1",
                    "profile": "NATIVE_CONTROL_V1",
                    "sessions": ["SYN2"],
                    "hypothesis": hypothesis(),
                },
            },
        },
    )
    assert "error" in response
    with campaign.c.ledger.connect() as db:
        assert not campaign.c.state(db, campaign.envelope["campaign_id"])["experiments"]
    assert wire.rpc("notifications/initialized")[0] == 202
    connection = http.client.HTTPConnection("127.0.0.1", wire.port)
    connection.request("GET", "/mcp")
    assert connection.getresponse().status == 405
    connection.close()


def test_read_only_principal_cannot_discover_mutating_tools(campaign):
    result = dispatch(
        campaign.c,
        Principal(campaign.principal.subject, frozenset(["campaign.read"])),
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert {x["name"] for x in result["tools"]} == {
        "campaign_status",
        "get_experiment_results",
        "list_ledger",
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.update(active=False),
        lambda c: c.update(aud="other"),
        lambda c: c.update(iss="https://attacker.invalid"),
        lambda c: c.update(exp=1),
        lambda c: c.update(sub=""),
        lambda c: c.update(scope=None),
    ],
)
def test_oauth_claim_binding_fails_closed(mutate):
    v = OAuthIntrospection(
        "https://auth.invalid/introspect",
        "https://auth.invalid",
        "https://research.invalid/mcp",
        "id",
        "not-a-live-secret",
        clock=lambda: 10,
    )
    claims = {
        "active": True,
        "iss": "https://auth.invalid",
        "aud": "https://research.invalid/mcp",
        "exp": 20,
        "sub": "researcher",
        "scope": "campaign.read campaign.execute",
    }
    assert v.claims(claims).subject == "researcher"
    mutate(claims)
    with pytest.raises(InvalidArtifact, match="unauthorized"):
        v.claims(claims)


def test_oauth_introspection_network_failure_and_redirect_do_not_authenticate(monkeypatch):
    v = OAuthIntrospection(
        "https://auth.invalid/introspect",
        "https://auth.invalid",
        "https://research.invalid/mcp",
        "id",
        "not-a-live-secret",
    )

    class FakeHTTPS:
        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            raise OSError("sensitive upstream detail must not escape")

        def close(self):
            pass

    monkeypatch.setattr(http.client, "HTTPSConnection", FakeHTTPS)
    with pytest.raises(InvalidArtifact, match="^unauthorized$"):
        v.verify("synthetic-token")
    with pytest.raises(InvalidArtifact):
        OAuthIntrospection(
            "http://auth.invalid",
            "https://auth.invalid",
            "https://research.invalid/mcp",
            "id",
            "secret",
        )


def test_lifecycle_default_permission_gate_and_wrong_vm_never_calls_gcp(campaign):
    def forbidden(*a, **k):
        pytest.fail("must not call cloud")

    lab = GcpLab("gcloud", run=forbidden)
    with pytest.raises(InvalidArtifact, match="not_authorized"):
        lab.status()
    with pytest.raises(InvalidArtifact, match="durable_lease_required"):
        lab.stop()
    e = copy.deepcopy(campaign.envelope)
    e["mode"] = "LIVE"
    e["target"]["vm"] = "wrong"
    with pytest.raises(InvalidArtifact, match="wrong_live_target"):
        lab.start(e, LeaseJournal(campaign.c, campaign.envelope["campaign_id"]))


@pytest.mark.parametrize(
    "extra",
    [
        {"serviceAccounts": [{"email": "x"}]},
        {"guestAccelerators": [{"type": "gpu"}]},
        {"networkInterfaces": [{"accessConfigs": [{}]}]},
        {"machineType": "zones/b/e2-standard-8"},
    ],
)
def test_unsafe_vm_configuration_blocks_start(campaign, extra):
    commands = []

    def run(argv, **kwargs):
        commands.append(argv)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "name": "jewelai-llm-lab",
                    "status": "TERMINATED",
                    "machineType": "zones/b/e2-medium",
                    "networkInterfaces": [{}],
                    **extra,
                }
            ).encode(),
        )

    e = copy.deepcopy(campaign.envelope)
    lab = GcpLab("gcloud", activation_permit=True, run=run, exclusive_use=nullcontext)
    lab.check_envelope = lambda _: None  # fake-only composition, real ownership logic
    with pytest.raises(InvalidArtifact, match="vm_configuration_mismatch"):
        lab.start(e, LeaseJournal(campaign.c, campaign.envelope["campaign_id"]))
    assert len(commands) == 1 and commands[0][3] == "describe"


def test_runtime_attestation_mismatch_before_forwarding(tmp_path):
    key, hosts = tmp_path / "key", tmp_path / "known_hosts"
    key.write_text("synthetic")
    hosts.write_text("synthetic")
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        assert argv[-1] == ATTEST and "StrictHostKeyChecking=yes" in argv
        assert "start-iap-tunnel" in argv[argv.index("-o") + 1] or any(
            "start-iap-tunnel" in a for a in argv
        )
        return SimpleNamespace(returncode=0, stdout=b"{}")

    def no_forward(*a, **k):
        pytest.fail("must attest before private forwarding")

    tunnel = PrivateTunnel("gcloud", key, hosts, activation_permit=True, run=run, popen=no_forward)
    with pytest.raises(InvalidArtifact, match="runtime_attestation_mismatch"):
        tunnel.open()
    assert len(calls) == 1
