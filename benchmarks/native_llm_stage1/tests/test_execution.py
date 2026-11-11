import base64
import hashlib
import json
import socket
from dataclasses import replace

import pytest

from native_llm_bench import storage, transport
from native_llm_bench.contracts import InvalidArtifact, execution_plan
from native_llm_bench.runner import execute


def test_real_http_two_and_five_turn_history_unicode_isolation(
    corpus, manifest, endpoint, tmp_path
):
    summary = execute(corpus, endpoint.config, manifest, tmp_path)
    assert summary["status"] == "COMPLETED"
    assert len(endpoint.requests) == 7
    _, results = storage.read_results(summary["run_directory"])
    assert len(results) == 7
    position = 0
    for sid in storage.read_run(summary["run_directory"])["plan"]["session_order"]:
        session = next(s for s in corpus["sessions"] if s["session_id"] == sid)
        history = [{"role": "system", "content": corpus["instructions"]["NEUTRAL"]}]
        for turn in session["turns"]:
            sent = endpoint.requests[position]
            history.append({"role": "user", "content": turn["text"]})
            assert sent["path"] == "/v1/chat/completions"
            assert sent["body"]["messages"] == history
            assert sent["body"]["cache_prompt"] is False
            assert sent["body"]["chat_template_kwargs"] == {"enable_thinking": False}
            record = results[position]
            assert record["session_id"] == sid and record["turn_id"] == turn["turn_id"]
            assert base64.b64decode(record["raw_response_base64"]) == endpoint.raw[position]
            assert record["assistant_message"]["content"].endswith(" \n")  # Never strip raw output.
            assert record["metrics"]["prompt_tokens"] == 10
            assert record["metrics"]["completion_tokens"] == 4
            assert record["metrics"]["ttft_seconds"] is None
            assert record["metrics"]["cpu_percent"] is None
            assert record["metrics"]["ram_bytes"] is None
            assert record["wall_seconds"] > 0
            history.append(record["assistant_message"])
            position += 1
    old_count = len(endpoint.requests)
    again = execute(corpus, endpoint.config, manifest, None, resume=summary["run_directory"])
    assert again["status"] == "COMPLETED" and len(endpoint.requests) == old_count
    rerun = execute(corpus, endpoint.config, manifest, tmp_path, rerun_of=summary["run_directory"])
    assert rerun["run_id"] != summary["run_id"]
    assert (
        storage.read_run(rerun["run_directory"])["plan"]
        == storage.read_run(summary["run_directory"])["plan"]
    )
    assert (tmp_path / rerun["run_id"] / "rerun.json").is_file()


def test_role_only_instruction_and_no_evaluator_payload(corpus, manifest, endpoint, tmp_path):
    corpus["instructions"]["DESIGNER"] = "You assist a designer. Respond in the user's language."
    corpus["sessions"][0]["instruction_id"] = "DESIGNER"
    corpus["sessions"][0]["role"] = "DESIGNER"
    evaluator = {"gold": "GOLD_DO_NOT_SEND", "source": "PRIVATE_REFERENCE", "score": 4}
    execute(corpus, endpoint.config, manifest, tmp_path, selected=["SYN2"])
    for request in endpoint.requests:
        assert request["body"]["messages"][0]["content"] == corpus["instructions"]["DESIGNER"]
        encoded = json.dumps(request)
        assert all(value not in encoded for value in (evaluator["gold"], evaluator["source"]))
        assert set(request["body"]) == {
            "model",
            "messages",
            "stream",
            "temperature",
            "top_p",
            "max_tokens",
            "repeat_penalty",
            "cache_prompt",
            "chat_template_kwargs",
            "seed",
            "top_k",
        }
    corpus["sessions"][0]["turns"][0]["gold"] = evaluator["gold"]
    with pytest.raises(InvalidArtifact):
        execute(corpus, endpoint.config, manifest, tmp_path)
    assert len(endpoint.requests) == 2


@pytest.mark.parametrize(
    ("action", "status"),
    [
        ({"raw": b"{not-json"}, "INVALID_API_RESPONSE"),
        ({"response": {"id": "x", "choices": []}}, "INVALID_API_RESPONSE"),
        (
            {
                "response": {
                    "id": "x",
                    "choices": [
                        {"message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}
                    ],
                }
            },
            "MISSING_CONTENT",
        ),
        (
            {
                "response": {
                    "id": "x",
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "partial"},
                            "finish_reason": "length",
                        }
                    ],
                }
            },
            "TRUNCATED",
        ),
        (
            {
                "response": {
                    "id": "x",
                    "choices": [
                        {"message": {"role": "user", "content": "bad"}, "finish_reason": "stop"}
                    ],
                }
            },
            "INVALID_API_RESPONSE",
        ),
        (
            {
                "response": {
                    "id": "x",
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "x",
                                "reasoning_content": "unexpected",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
            },
            "PROMPT_TEMPLATE",
        ),
        ({"http": 400, "response": {"error": {"code": "chat_template_error"}}}, "PROMPT_TEMPLATE"),
        ({"http": 302, "response": {}}, "HTTP_ERROR"),
        ({"raw": b'{"partial":', "missing_bytes": 100}, "TRANSPORT"),
    ],
)
def test_failed_partial_outputs_not_appended(action, status, corpus, manifest, endpoint, tmp_path):
    endpoint.actions = [action]
    cfg = replace(endpoint.config, max_attempts=1)
    result = execute(corpus, cfg, manifest, tmp_path, selected=["SYN2"])
    assert result["sessions"]["SYN2"]["status"] == status
    assert result["sessions"]["SYN2"]["completed_turns"] == 0
    assert len(endpoint.requests) == 1
    _, records = storage.read_results(result["run_directory"])
    assert records[0]["status"] == status


def test_timeout_explicit_resume_and_no_blind_retry(corpus, manifest, endpoint, tmp_path):
    endpoint.actions = [{"delay": 0.12}]
    cfg = replace(endpoint.config, timeout_seconds=0.04)
    failed = execute(corpus, cfg, manifest, tmp_path, selected=["SYN2"])
    assert failed["sessions"]["SYN2"]["status"] == "TIMEOUT"
    assert len(endpoint.requests) == 1
    root = failed["run_directory"]
    execute(corpus, cfg, manifest, None, selected=["SYN2"], resume=root)
    assert len(endpoint.requests) == 1
    good = execute(
        corpus, cfg, manifest, None, selected=["SYN2"], resume=root, retry_uncertain=True
    )
    assert good["status"] == "COMPLETED"
    assert len(endpoint.requests) == 3  # Timed-out T1; retried T1; T2 with only valid assistant.
    assert len(endpoint.requests[-1]["body"]["messages"]) == 4
    _, records = storage.read_results(root)
    assert [r["status"] for r in records] == ["TIMEOUT", "COMPLETED", "COMPLETED"]


def test_connection_refused_retry_budget(corpus, manifest, tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    cfg = replace(transport_config(), endpoint=f"http://127.0.0.1:{port}")
    result = execute(corpus, cfg, manifest, tmp_path, selected=["SYN2"])
    _, records = storage.read_results(result["run_directory"])
    assert [r["status"] for r in records] == ["ENDPOINT_UNAVAILABLE"] * 2
    assert all(not r["provider_may_have_executed"] for r in records)


def transport_config():
    from native_llm_bench.contracts import Config

    return replace(Config(), model="synthetic-local-model", max_attempts=2)


def test_server_error_retry_preserves_attempts(corpus, manifest, endpoint, tmp_path):
    endpoint.actions = [{"http": 503}]
    result = execute(corpus, endpoint.config, manifest, tmp_path, selected=["SYN2"])
    assert result["status"] == "COMPLETED"
    _, records = storage.read_results(result["run_directory"])
    assert [r["status"] for r in records] == ["SERVER_ERROR", "COMPLETED", "COMPLETED"]
    assert endpoint.requests[0]["body"] == endpoint.requests[1]["body"]
    assert len(endpoint.requests[2]["body"]["messages"]) == 4


def test_interrupt_recovery_completed_bytes_unchanged(corpus, manifest, endpoint, tmp_path):
    calls = 0

    def interrupted(cfg, payload):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return transport.request(cfg, payload)

    with pytest.raises(KeyboardInterrupt):
        execute(
            corpus, endpoint.config, manifest, tmp_path, selected=["SYN2"], transport=interrupted
        )
    directory = next(tmp_path.iterdir())
    first = directory / "results/SYN2/SYN2.T1/0001.json"
    original = first.read_bytes()
    assert not (directory / "results/SYN2/SYN2.T2/0001.json").exists()
    blocked = execute(corpus, endpoint.config, manifest, None, selected=["SYN2"], resume=directory)
    assert blocked["sessions"]["SYN2"]["status"] == "INTERRUPTED_UNKNOWN"
    assert len(endpoint.requests) == 1
    good = execute(
        corpus,
        endpoint.config,
        manifest,
        None,
        selected=["SYN2"],
        resume=directory,
        retry_uncertain=True,
    )
    assert good["status"] == "COMPLETED"
    assert first.read_bytes() == original
    assert len(endpoint.requests) == 2
    assert endpoint.requests[-1]["body"]["messages"][2]["content"].endswith(" \n")


@pytest.mark.parametrize("change", ["corpus", "config", "manifest"])
def test_resume_mismatch_before_any_request(change, corpus, manifest, endpoint, tmp_path):
    result = execute(corpus, endpoint.config, manifest, tmp_path, selected=["SYN2"])
    cfg = endpoint.config
    if change == "corpus":
        corpus["sessions"][0]["turns"][0]["text"] += " changed"
    elif change == "config":
        cfg = replace(cfg, max_tokens=64)
    else:
        manifest["model_sha256"] = "f" * 64
    with pytest.raises(InvalidArtifact, match="mismatch"):
        execute(corpus, cfg, manifest, None, selected=["SYN2"], resume=result["run_directory"])
    assert len(endpoint.requests) == 2


def test_reused_response_id_suspected_leakage(corpus, manifest, endpoint, tmp_path):
    # Two completed first-session turns followed by a duplicate server response ID in the next.
    plan = execution_plan(corpus, endpoint.config, manifest)
    first_length = len(
        next(s for s in corpus["sessions"] if s["session_id"] == plan["session_order"][0])["turns"]
    )
    endpoint.response_ids = (
        ["reused"] + [f"normal-{i}" for i in range(first_length - 1)] + ["reused"]
    )
    result = execute(corpus, endpoint.config, manifest, tmp_path)
    second = plan["session_order"][1]
    assert result["sessions"][second]["status"] == "SUSPECTED_CONTEXT_LEAKAGE"
    assert result["sessions"][second]["completed_turns"] == 0


def test_tampered_current_request_history_fails_closed(corpus, manifest, endpoint, tmp_path):
    r = execute(corpus, endpoint.config, manifest, tmp_path, selected=["SYN2"])
    p = tmp_path / r["run_id"] / "requests/SYN2/SYN2.T2/0001.json"
    altered = json.loads(p.read_text())
    altered["payload"]["messages"][2]["content"] = "forged assistant"
    from native_llm_bench.contracts import digest

    altered["request_sha256"] = digest(altered["payload"])
    p.write_text(json.dumps(altered))
    with pytest.raises(InvalidArtifact, match="integrity"):
        execute(corpus, endpoint.config, manifest, None, selected=["SYN2"], resume=p.parents[3])
    assert len(endpoint.requests) == 2


def test_append_only_atomic_private_storage(tmp_path):
    p = tmp_path / "new/private.json"
    storage.write(p, {"first": True})
    original = hashlib.sha256(p.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        storage.write(p, {"first": False})
    assert hashlib.sha256(p.read_bytes()).hexdigest() == original
    assert p.stat().st_mode & 0o777 == 0o600
    assert p.parent.stat().st_mode & 0o777 == 0o700
    with (
        storage.lock(p.parent),
        pytest.raises(InvalidArtifact, match="executor"),
        storage.lock(p.parent),
    ):
        pass


def test_unreported_token_metrics_stay_null(corpus, manifest, endpoint, tmp_path):
    endpoint.actions = [
        {
            "response": {
                "id": "no-usage",
                "choices": [
                    {"message": {"role": "assistant", "content": "text"}, "finish_reason": "stop"}
                ],
            }
        }
    ]
    result = execute(corpus, endpoint.config, manifest, tmp_path, selected=["SYN2"])
    assert result["status"] == "COMPLETED"
    _, rows = storage.read_results(result["run_directory"])
    assert rows[0]["metrics"]["completion_tokens"] is None
    assert rows[0]["metrics"]["completion_tokens_per_wall_second"] is None
    assert rows[0]["metrics"]["server_decode_tokens_per_second"] is None


def test_transport_itself_forbids_external_destination(endpoint):
    with pytest.raises(InvalidArtifact, match="loopback"):
        transport.request(replace(endpoint.config, endpoint="https://api.openai.com:443"), {})
    assert not endpoint.requests


def test_export_checks_request_integrity(corpus, manifest, endpoint, tmp_path):
    r = execute(corpus, endpoint.config, manifest, tmp_path, selected=["SYN2"])
    p = tmp_path / r["run_id"] / "requests/SYN2/SYN2.T1/0001.json"
    data = json.loads(p.read_text())
    data["payload"]["messages"][1]["content"] = "tampered"
    p.write_text(json.dumps(data))
    with pytest.raises(InvalidArtifact, match="integrity"):
        storage.export(tmp_path / r["run_id"])


def test_unexecuted_turns_explicitly_blocked(corpus, manifest, endpoint, tmp_path):
    endpoint.actions = [{"raw": b"not JSON"}]
    r = execute(corpus, endpoint.config, manifest, tmp_path, selected=["SYN5"])
    statuses = r["sessions"]["SYN5"]["turn_statuses"]
    assert statuses["SYN5.T1"] == "INVALID_API_RESPONSE"
    assert all(statuses[f"SYN5.T{i}"] == "BLOCKED_BY_PRIOR_TURN" for i in range(2, 6))
