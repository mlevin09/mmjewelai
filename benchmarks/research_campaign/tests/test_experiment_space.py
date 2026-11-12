from pathlib import Path

import pytest
from conftest import http_wire, hypothesis
from native_llm_bench.contracts import InvalidArtifact, digest, load, sha256_file

from jewelai_research.contracts import Inputs, experiment_plan, validate_envelope
from jewelai_research.controller import Controller
from jewelai_research.experiments import validate_policy
from jewelai_research.synthetic import envelope
from jewelai_research.worker import Worker

POLICY = Path(__file__).parents[1] / "fixtures" / "synthetic.experiment-policy.json"


@pytest.fixture
def research(campaign, tmp_path):
    f = campaign
    policy = tmp_path / "operator-policy.json"
    policy.write_bytes(POLICY.read_bytes())
    f.inputs = Inputs(*f.inputs.paths, policy_path=policy)
    f.c = Controller(tmp_path / "research-private", f.inputs, clock=lambda: f.clock[0])
    f.envelope = envelope(f.inputs, clock=lambda: f.clock[0])
    f.envelope.update(max_experiments=6, max_turns=20, max_attempts=20)
    f.envelope["budget"].update(hard_ceiling=23, soft_limit=20)
    f.c.activate(f.envelope)
    f.worker = Worker(f.c, f.lab, f.model)
    return f


def test_adaptive_operator_space_through_mcp_persistence_and_immutable_pins(research):
    f, cid = research, research.envelope["campaign_id"]
    original = [sha256_file(p) for p in f.inputs.paths]
    with http_wire(f) as wire:

        def tool(name, **kwargs):
            response = wire.rpc(
                "tools/call", {"name": name, "arguments": {"campaign_id": cid, **kwargs}}
            )[1]
            assert "error" not in response, response
            return response["result"]["structuredContent"]

        schema = wire.rpc("tools/list")[1]["result"]["tools"][1]["inputSchema"]
        assert "RESEARCH_SAMPLING" in schema["properties"]["profile"]["enum"]
        assert schema["properties"]["parameters"]["additionalProperties"] is False
        status = tool("campaign_status")
        assert status["experiment_policy"]["policy_id"] == "SYNTHETIC_RESEARCH_SPACE_V1"
        evidence, choices = [], []

        def study(profile, parameters, sample):
            eid = "E" + str(len(choices) + 1)
            registered = tool(
                "propose_and_register_experiment",
                experiment_id=eid,
                profile=profile,
                parameters=parameters,
                sessions=sample,
                hypothesis=hypothesis(*evidence),
                idempotency_key="register-" + eid,
            )
            tool(
                "execute_registered_experiment", experiment_id=eid, idempotency_key="execute-" + eid
            )
            f.worker.once(cid)
            result = tool("get_experiment_results", experiment_id=eid)
            choices.append(profile)
            evidence.append(eid)
            assert result["parameters"] == parameters
            assert result["operator_policy_sha256"] == digest(f.inputs.policy)
            return registered, result

        # Result-driven choice: truncation investigates completion budget rather than blindly
        # walking the old three-profile list. New values are chosen within pinned bounds.
        _, first = study("NATIVE_CONTROL_V1", {}, ["SYN2"])
        assert first["measurements"]["truncated"] == 1
        next_type = "TOKEN_BUDGET" if first["measurements"]["truncated"] else "EN_LONG_CONTEXT"
        _, second = study(next_type, {"max_tokens": 320}, ["SYN2"])
        assert second["receipt"]["runner"]["run"]["plan"]["configuration"]["max_tokens"] == 320
        # Sampling value is not a named profile/grid entry and differs from temp=0.2.
        _, third = study("RESEARCH_SAMPLING", {"temperature": 0.37}, ["SYN2"])
        assert third["measurements"]["completed"] == 2
        sample_type = (
            "EN_LONG_CONTEXT" if third["measurements"]["completed"] == 2 else "TEMPLATE_CHECK"
        )
        _, fourth = study(sample_type, {}, ["SYN5"])
        assert fourth["receipt"]["runner"]["run"]["plan"]["session_order"] == ["SYN5"]
        registered, fifth = study(
            "PROMPT_VARIANT", {"instruction_variant": "LANGUAGE_CLARITY_V1"}, ["SYN2"]
        )
        assert registered["effective_runtime_sha256"] != registered["base_runtime_sha256"]
        payload = fifth["receipt"]["runner"]["requests"][0]["payload"]
        prefix = f.inputs.corpus["instructions"]["NEUTRAL"]
        assert payload["messages"][0]["content"].startswith(prefix + "\n\n")
        assert "SYNTHETIC RESEARCH CONDITION" in payload["messages"][0]["content"]
        assert len(set(choices)) == 5
        # The same single campaign survives reconstructing the controller/read side.
        restored = Controller(f.c.ledger.root, f.inputs, clock=lambda: f.clock[0])
        assert restored.call(f.principal, "campaign_status", {"campaign_id": cid})["experiments"][
            -1
        ]["status"] in {"COMPLETED", "INCOMPLETE"}
        tool("stop_campaign", idempotency_key="stop", reason="synthetic assignment complete")
        f.worker.once(cid)
        final = tool(
            "finalize_campaign",
            idempotency_key="final",
            conclusion="Synthetic adaptive research only.",
        )
        assert len(final["report"]["verified_receipts"]) == 5
        assert final["report"]["cleanup"]["verified_stopped"]
    assert [sha256_file(p) for p in f.inputs.paths] == original


@pytest.mark.parametrize(
    "profile,parameters,sample",
    [
        ("RESEARCH_SAMPLING", {"temperature": 0.81}, ["SYN2"]),
        ("RESEARCH_SAMPLING", {"temperature": True}, ["SYN2"]),
        ("RESEARCH_SAMPLING", {"temperature": 0.3, "top_p": 0.8}, ["SYN2"]),
        ("RESEARCH_SAMPLING", {"command": "shell"}, ["SYN2"]),
        ("RESEARCH_SAMPLING", {"endpoint": "https://external.invalid"}, ["SYN2"]),
        ("RESEARCH_SAMPLING", {"system_prompt": "free text"}, ["SYN2"]),
        ("TOKEN_BUDGET", {"max_tokens": 500}, ["SYN2"]),
        ("EN_LONG_CONTEXT", {}, ["SYN2"]),
        ("PROMPT_VARIANT", {"instruction_variant": "UNKNOWN"}, ["SYN2"]),
        ("STOP_EOS_CHECK", {"stop": "arbitrary stop strings"}, ["SYN2"]),
        ("RESEARCH_SAMPLING", {}, ["KG09"]),
    ],
)
def test_unapproved_treatments_fail_closed(research, profile, parameters, sample):
    with pytest.raises(InvalidArtifact):
        experiment_plan(research.envelope, research.inputs, profile, sample, parameters)
    assert research.lab.starts == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["instructions"]["LANGUAGE_CLARITY_V1"].update(suffix="tamper"),
        lambda p: p["bounds"].update(endpoint={"min": 0, "max": 1}),
        lambda p: p["baseline"].update(max_tokens=1500),
        lambda p: p["profiles"]["RESEARCH_SAMPLING"].update(command="shell"),
        lambda p: p.update(version="unknown"),
    ],
)
def test_operator_policy_is_schema_validated_not_an_execution_escape(mutate):
    p = load(POLICY)
    mutate(p)
    with pytest.raises(InvalidArtifact):
        validate_policy(p)


def test_policy_file_changed_after_registration_blocks_execution(research):
    f, cid = research, research.envelope["campaign_id"]
    args = {
        "campaign_id": cid,
        "idempotency_key": "r",
        "experiment_id": "E1",
        "profile": "RESEARCH_SAMPLING",
        "parameters": {"temperature": 0.37},
        "sessions": ["SYN2"],
        "hypothesis": hypothesis(),
    }
    f.c.call(f.principal, "propose_and_register_experiment", args)
    f.c.call(
        f.principal,
        "execute_registered_experiment",
        {"campaign_id": cid, "experiment_id": "E1", "idempotency_key": "q"},
    )
    f.inputs.paths[-1].write_text("{}")
    assert f.worker.once(cid) == "UNKNOWN"
    assert f.lab.starts == 0 and f.lab.stops == 0
    with pytest.raises(InvalidArtifact, match="source_file_changed"):
        validate_envelope(f.envelope, f.inputs)
