import copy
import hashlib
import json
from dataclasses import replace

import pytest

from native_llm_bench.contracts import (
    InvalidArtifact,
    XorShift32,
    decode,
    digest,
    execution_plan,
    validate_runtime,
)
from native_llm_bench.corpus import (
    DIFFICULT_LENGTHS,
    KNOWLEDGE_GROUPS,
    NEUTRAL,
    ROLES,
    import_sources,
    validate_evaluator,
    validate_stage1,
)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_session",
        "duplicate_turn",
        "short",
        "long",
        "missing_id",
        "gold_session",
        "gold_turn",
        "gold_root",
    ],
)
def test_invalid_fixture_rejected(mutation, corpus):
    s = corpus["sessions"][0]
    if mutation == "duplicate_session":
        corpus["sessions"].append(copy.deepcopy(s))
    elif mutation == "duplicate_turn":
        s["turns"][1]["turn_id"] = s["turns"][0]["turn_id"]
    elif mutation == "short":
        s["turns"] = s["turns"][:1]
    elif mutation == "long":
        s["turns"] *= 3
    elif mutation == "missing_id":
        del s["turns"][0]["turn_id"]
    elif mutation == "gold_session":
        s["gold"] = "DO_NOT_SEND"
    elif mutation == "gold_turn":
        s["turns"][0]["expected_behavior"] = "DO_NOT_SEND"
    else:
        corpus["reference_facts"] = "DO_NOT_SEND"
    with pytest.raises(InvalidArtifact):
        validate_runtime(corpus)


def test_duplicate_json_fields_rejected():
    with pytest.raises(InvalidArtifact):
        decode('{"session_id":"S1","session_id":"S2"}')


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com:443",
        "http://localhost:8080",
        "http://192.168.1.2:8080",
        "http://127.0.0.1:8080/path",
        "http://user:password@127.0.0.1:8080",
        "http://127.0.0.1:8080?key=x",
        "http://127.0.0.1:8080#fragment",
    ],
)
def test_external_redirect_proxy_credentials_targets_forbidden(url, endpoint, manifest):
    with pytest.raises(InvalidArtifact):
        replace(endpoint.config, endpoint=url).validate(manifest)


def test_optional_supported_sampling_parameters_omitted(endpoint, manifest):
    c = replace(endpoint.config, seed=None, top_k=None)
    c.validate(manifest)
    payload = c.payload([{"role": "user", "content": "synthetic"}])
    assert "seed" not in payload and "top_k" not in payload
    with pytest.raises(InvalidArtifact):
        replace(c, context_tokens=4096).validate(manifest)


def test_seeded_golden_prng_and_plan(corpus, endpoint, manifest):
    rng = XorShift32(1)
    assert [rng.next() for _ in range(5)] == [270369, 67634689, 2647435461, 307599695, 2398689233]
    plan = execution_plan(corpus, endpoint.config, manifest)
    assert plan == execution_plan(copy.deepcopy(corpus), endpoint.config, manifest)
    assert plan["scheduling_seed"] == 20261111
    assert set(plan["session_order"]) == {"SYN2", "SYN5"}
    assert plan["turn_order"]["SYN5"] == [f"SYN5.T{i}" for i in range(1, 6)]
    assert plan["output_reproducibility"].startswith("NOT_ESTABLISHED")


def test_holdout_selection_no_pilot_execution(corpus, endpoint, manifest):
    for sid in ("KG09", "KJ08", "KJ12"):
        session = copy.deepcopy(corpus["sessions"][0])
        session["session_id"], session["holdout"] = sid, True
        for i, turn in enumerate(session["turns"]):
            turn["turn_id"] = f"{sid}.SYNTHETIC{i}"
        corpus["sessions"].append(session)
    full = execution_plan(corpus, endpoint.config, manifest)
    assert full["holdout_sessions_selected"] == ["KG09", "KJ08", "KJ12"]
    excluded = execution_plan(corpus, endpoint.config, manifest, exclude_holdouts=True)
    assert set(excluded["session_order"]) == {"SYN2", "SYN5"}
    with pytest.raises(InvalidArtifact):
        execution_plan(corpus, endpoint.config, manifest, selected=["KG09"], exclude_holdouts=True)
    with pytest.raises(InvalidArtifact):
        execution_plan(corpus, endpoint.config, manifest, selected=["MISSING"])


@pytest.fixture
def synthetic_sources(tmp_path):
    """Format/parser fixture ONLY. Not the approved 90-question corpus, never benchmarked."""
    documents = {
        "NB-01": "SYNTHETIC FORMAT FIXTURE v1.0\n",
        "NB-04": "SYNTHETIC v1.0\n",
        "NB-05": "SYNTHETIC FORMAT FIXTURE v1.0\n",
        "NB-06": "SYNTHETIC FORMAT FIXTURE v1.0\n" + f'"{NEUTRAL}"\n',
    }
    for role in ROLES:
        documents["NB-06"] += f'{role}: "Synthetic role-only instruction for {role}."\n'
    for sid, (prefix, start, stop) in KNOWLEDGE_GROUPS.items():
        documents["NB-01"] += f"{sid} {prefix}{start:02}–{prefix}{stop:02} ({stop - start + 1}); "
    for prefix, count in (("G", 30), ("J", 60)):
        for i in range(1, count + 1):
            qid = f"{prefix}{i:02}"
            documents["NB-05"] += (
                f"\n{qid} [EN; D2; S,K] Synthetic user turn {qid}.\n"
                f"    GOLD (evaluator only): NEVER_TRANSMIT_GOLD_{qid}\n"
                "    SOURCE: SYNTHETIC_EVALUATOR_REFERENCE\n"
            )
    for n in range(1, 37):
        if n <= 21:
            sid, count, role = f"R{n:02}", (n - 1) % 3 + 2, ROLES[(n - 1) // 3]
        else:
            sid, count, role = f"D{n - 21:02}", DIFFICULT_LENGTHS[n - 22], "NEUTRAL"
        documents["NB-06"] += f"\n{sid} · {role} · EN · {count} turns · rubric S,T,K\n"
        for i in range(1, count + 1):
            documents["NB-06"] += (
                f" T{i} USER: Synthetic dialogue turn {sid} {i}.\n"
                f" T{i} GOLD (evaluator-only): NEVER_TRANSMIT_GOLD_{sid}_{i}\n"
            )
        documents["NB-06"] += " SOURCE: SYNTHETIC_ONLY\n"
    sources = []
    for name, text in documents.items():
        (tmp_path / (name + ".txt")).write_text(text)
        sources.append(
            {
                "id": name,
                "document_id": "SYNTHETIC_FORMAT_NOT_AUTHORITATIVE",
                "revision_id": "SYNTHETIC",
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
        )
    return tmp_path, sources


def test_import_separation_exact_text_counts_and_na(synthetic_sources):
    directory, sources = synthetic_sources
    runtime, evaluator = import_sources(directory, sources)
    assert validate_stage1(runtime) == {
        "sessions": 61,
        "user_turns": 209,
        "knowledge_questions": 90,
        "role_scenarios": 21,
        "difficult_scenarios": 15,
        "holdout_questions": 11,
    }
    assert len(evaluator["items"]) == 209
    assert "NEVER_TRANSMIT_GOLD" not in json.dumps(runtime)
    assert "SYNTHETIC_EVALUATOR_REFERENCE" not in json.dumps(runtime)
    assert runtime["sessions"][0]["turns"][0]["text"] == "Synthetic user turn G01."
    assert evaluator["items"][0]["dimensions"]["T"]["score"] == "N/A"
    assert evaluator["items"][0]["dimensions"]["K"]["score"] is None
    assert evaluator["items"][0]["ground_truth_status"] == "REVIEW_REQUIRED"
    evaluator["items"][0]["dimensions"]["T"]["score"] = 0
    with pytest.raises(InvalidArtifact, match="N/A"):
        validate_evaluator(evaluator, runtime)


def test_import_incomplete_source_or_changed_hash_fails(synthetic_sources):
    directory, sources = synthetic_sources
    (directory / "NB-05.txt").write_text("tampered")
    with pytest.raises(InvalidArtifact, match="hash"):
        import_sources(directory, sources)


def test_stage1_parent_mapping_cannot_be_silently_rearranged(synthetic_sources):
    runtime, _ = import_sources(*synthetic_sources)
    runtime["sessions"][0]["turns"].reverse()
    with pytest.raises(InvalidArtifact, match="parent/order"):
        validate_stage1(runtime)


def test_unresolved_gold_cannot_be_scored(synthetic_sources):
    runtime, evaluation = import_sources(*synthetic_sources)
    evaluation["items"][0]["dimensions"]["S"]["score"] = 4
    with pytest.raises(InvalidArtifact, match="unresolved gold"):
        validate_evaluator(evaluation, runtime)
    evaluation["items"][0]["ground_truth_status"] = "VERIFIED"
    validate_evaluator(evaluation, runtime)
    assert evaluation["runtime_artifact_sha256"] == digest(runtime)
