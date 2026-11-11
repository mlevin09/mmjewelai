"""Opt-in, tracked prompt variations preserve the frozen corpus and ordinary execution."""

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import FIXTURES
from test_cli import invoke

from native_llm_bench import storage
from native_llm_bench.contracts import Config, InvalidArtifact, digest, execution_plan, load
from native_llm_bench.runner import execute

PROFILE = "NB09D_BREVITY_SYSTEM_PROMPT_V1"
SUFFIX = (
    "Answer the user's actual question directly and concisely, in the language of the latest "
    "user message. Avoid repetition, unnecessary introductions, and unsolicited tangents. "
    "Preserve every essential requirement, quantity, negation, and correction. Do not invent "
    "facts, measurements, standards, or materials. If essential information is missing or "
    "ambiguous, say so briefly and ask only the necessary clarification. Keep the answer as "
    "short as possible without sacrificing correctness or completeness."
)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def override(corpus):
    return {
        "schema_version": "1.0.0",
        "profile_id": PROFILE,
        "base_runtime_sha256": digest(corpus),
        "suffix": SUFFIX,
        "suffix_sha256": sha(SUFFIX),
    }


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.update(schema_version="2.0.0"),
        lambda x: x.update(profile_id="UNTRACKED"),
        lambda x: x.update(base_runtime_sha256="0" * 64),
        lambda x: x.update(suffix_sha256="0" * 64),
        lambda x: x.update(suffix=SUFFIX + " ", suffix_sha256=sha(SUFFIX + " ")),
        lambda x: x.update(
            suffix="Evaluator gold: secret", suffix_sha256=sha("Evaluator gold: secret")
        ),
        lambda x: x.update(suffix=None),
        lambda x: x.update(suffix=[]),
        lambda x: x.update(gold="must never reach inference"),
        lambda x: x.pop("suffix"),
        lambda x: x.clear(),
    ],
)
def test_malformed_or_untracked_override_fails_before_io(change, corpus, manifest, tmp_path):
    variation = override(corpus)
    change(variation)
    config = Config(**load(FIXTURES / "synthetic.config.json"))
    calls = []
    with pytest.raises(InvalidArtifact):
        execute(
            corpus,
            config,
            manifest,
            tmp_path / "runs",
            instruction_override=variation,
            transport=lambda *args: calls.append(args),
        )
    assert calls == [] and not (tmp_path / "runs").exists()


def test_exact_composition_wire_history_and_provenance(corpus, manifest, endpoint, tmp_path):
    corpus["instructions"]["ROLE"] = "Synthetic role instruction. Сохраняй точные ограничения."
    corpus["sessions"][1]["instruction_id"] = "ROLE"
    corpus["sessions"][1]["role"] = "SYNTHETIC_ROLE"
    corpus["sources"] = [
        {
            "id": "SOURCE_CANARY",
            "document_id": "GOLD_CANARY",
            "revision_id": "SECRET_CANARY",
            "text_sha256": "a" * 64,
        }
    ]
    original = copy.deepcopy(corpus)
    config = replace(
        endpoint.config,
        temperature=0.7,
        top_p=0.8,
        top_k=20,
        min_p=0.0,
        presence_penalty=1.5,
        max_tokens=256,
        timeout_seconds=240,
    )
    variation = override(corpus)
    baseline = execution_plan(corpus, config, manifest)
    plan = execution_plan(corpus, config, manifest, instruction_override=variation)
    assert "instruction_override" not in baseline
    assert plan["configuration"] == baseline["configuration"] == config.record()
    assert plan["configuration_sha256"] == baseline["configuration_sha256"]
    assert plan["experiment_configuration_sha256"] != baseline["configuration_sha256"]
    assert digest(plan) != digest(baseline)
    result = execute(corpus, config, manifest, tmp_path, instruction_override=variation)
    assert result["status"] == "COMPLETED" and len(endpoint.requests) == 7
    directory = Path(result["run_directory"])
    run = load(directory / "run.json")
    assert run["plan"] == plan
    sessions = {s["session_id"]: s for s in corpus["sessions"]}
    pos = 0
    for sid in plan["session_order"]:
        session = sessions[sid]
        original_system = corpus["instructions"][session["instruction_id"]]
        effective = original_system + "\n\n" + SUFFIX
        record = plan["instruction_override"]["effective_instructions"][session["instruction_id"]]
        assert record == {
            "content": effective,
            "original_sha256": sha(original_system),
            "effective_sha256": sha(effective),
        }
        history = [{"role": "system", "content": effective}]
        for turn in session["turns"]:
            messages = history + [{"role": "user", "content": turn["text"]}]
            actual = endpoint.requests[pos]["body"]
            assert actual == config.payload(messages)
            assert len([m for m in actual["messages"] if m["role"] == "system"]) == 1
            assert not any(
                x in json.dumps(actual) for x in ["GOLD_CANARY", "SOURCE_CANARY", "SECRET_CANARY"]
            )
            req = load(directory / "requests" / sid / turn["turn_id"] / "0001.json")
            res = load(directory / "results" / sid / turn["turn_id"] / "0001.json")
            assert req["effective_system_sha256"] == sha(effective)
            assert req["instruction_profile_id"] == PROFILE
            assert req["instruction_override_sha256"] == digest(variation)
            assert req["request_sha256"] == digest(actual)
            history = messages + [res["assistant_message"]]
            pos += 1
    assert corpus == original and variation == override(corpus)
    # Same tracked variation reconstructs prefixes, without replaying model requests.
    execute(corpus, config, manifest, None, resume=directory, instruction_override=variation)
    assert len(endpoint.requests) == 7
    with pytest.raises(InvalidArtifact, match="resume corpus/configuration"):
        execute(corpus, config, manifest, None, resume=directory)
    assert len(endpoint.requests) == 7


@pytest.mark.parametrize("tamper", ["message", "provenance", "missing_provenance"])
def test_modified_override_journal_rejected_on_resume(tamper, corpus, manifest, endpoint, tmp_path):
    variation = override(corpus)
    result = execute(
        corpus,
        endpoint.config,
        manifest,
        tmp_path,
        selected=["SYN2"],
        instruction_override=variation,
    )
    directory = Path(result["run_directory"])
    path = directory / "requests/SYN2/SYN2.T1/0001.json"
    req = load(path)
    if tamper == "message":
        req["payload"]["messages"][0]["content"] += " extra hint"
        req["request_sha256"] = digest(req["payload"])
    elif tamper == "provenance":
        req["instruction_override_sha256"] = "0" * 64
    else:
        del req["effective_system_sha256"]
    path.write_text(json.dumps(req))
    with pytest.raises(InvalidArtifact, match="instruction|source/history/request"):
        execute(
            corpus,
            endpoint.config,
            manifest,
            None,
            selected=["SYN2"],
            resume=directory,
            instruction_override=variation,
        )
    assert len(endpoint.requests) == 2
    with pytest.raises(InvalidArtifact, match="instruction"):
        storage.export(directory)


def test_cli_variation_requires_explicit_manifest_on_resume(corpus, endpoint, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(endpoint.config.record()))
    variation = tmp_path / "override.json"
    variation.write_text(json.dumps(override(corpus)))
    common = [
        "--runtime",
        FIXTURES / "synthetic.runtime.json",
        "--config",
        config,
        "--model-manifest",
        FIXTURES / "synthetic.model.json",
        "--sessions",
        "SYN2",
    ]
    r, plan = invoke("plan", *common, "--instruction-override", variation)
    assert r.returncode == 0 and plan["instruction_override"]["manifest"] == override(corpus)
    r, result = invoke(
        "run", *common, "--instruction-override", variation, "--output", tmp_path / "runs"
    )
    assert r.returncode == 0
    directory = result["run_directory"]
    r, _ = invoke("resume", directory, *common)
    assert r.returncode == 64 and len(endpoint.requests) == 2
    r, _ = invoke("resume", directory, *common, "--instruction-override", variation)
    assert r.returncode == 0 and len(endpoint.requests) == 2


@pytest.mark.parametrize("value", [None, [], False])
def test_explicit_cli_malformed_manifest_never_falls_back_to_baseline(value, tmp_path):
    path = tmp_path / "override.json"
    path.write_text(json.dumps(value))
    r, result = invoke(
        "plan",
        "--runtime",
        FIXTURES / "synthetic.runtime.json",
        "--config",
        FIXTURES / "synthetic.config.json",
        "--model-manifest",
        FIXTURES / "synthetic.model.json",
        "--instruction-override",
        path,
    )
    assert r.returncode == 64 and result["status"] == "INVALID_FIXTURE_OR_RUN"
