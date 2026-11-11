"""Optional sampler controls must not rewrite historical records or wire payloads."""

from dataclasses import replace

import pytest
from conftest import FIXTURES

from native_llm_bench.contracts import Config, InvalidArtifact, digest, execution_plan, load
from native_llm_bench.transport import request


def test_legacy_configuration_payload_and_plan_hashes_are_unchanged():
    # Captured with accepted runner 1915b436 before adding either optional field.
    record = load(FIXTURES / "synthetic.config.json")
    config = Config(**record)
    messages = [{"role": "user", "content": "Synthetic compatibility check."}]
    manifest = load(FIXTURES / "synthetic.model.json")
    config.validate(manifest)
    assert config.record() == record
    assert (
        digest(config.record())
        == "2933e59f1aa373b5bd44dfae2984705ad7db8746f2835be46d6844c59b590a5b"
    )
    assert (
        digest(config.payload(messages))
        == "aa1c833272fd99848d8610d336f912781459de71c1deac18d30da983a129aec7"
    )
    plan = execution_plan(load(FIXTURES / "synthetic.runtime.json"), config, manifest)
    assert digest(plan) == "16578ccd1394e94fcdae0c5ba2e22742784664e43762b44879049b85780922f7"


@pytest.mark.parametrize("field", ["min_p", "presence_penalty"])
def test_optional_null_is_omitted_without_changing_other_legacy_nulls(field):
    config = Config(**{field: None}, seed=None, top_k=None)
    assert field not in config.record()
    assert field not in config.payload([])
    assert config.record()["seed"] is None and config.record()["top_k"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("min_p", 0),
        ("min_p", 0.25),
        ("min_p", 1),
        ("presence_penalty", 0),
        ("presence_penalty", 1.5),
        ("presence_penalty", 2),
    ],
)
def test_optional_sampler_valid_values_survive_record_and_payload(field, value, manifest):
    config = replace(Config(), model=manifest["model_id"], **{field: value})
    config.validate(manifest)
    assert config.record()[field] == value
    assert config.payload([])[field] == value
    assert Config(**config.record()).record() == config.record()


@pytest.mark.parametrize("field", ["min_p", "presence_penalty"])
@pytest.mark.parametrize(
    "value", [True, False, "0.5", [], {}, float("nan"), float("inf"), float("-inf"), -0.01]
)
def test_optional_sampler_rejects_invalid_values(field, value, manifest):
    config = replace(Config(), model=manifest["model_id"], **{field: value})
    with pytest.raises(InvalidArtifact, match=field):
        config.validate(manifest)


@pytest.mark.parametrize("field,value", [("min_p", 1.01), ("presence_penalty", 2.01)])
def test_optional_sampler_rejects_values_above_supported_range(field, value, manifest):
    with pytest.raises(InvalidArtifact, match=field):
        replace(Config(), model=manifest["model_id"], **{field: value}).validate(manifest)


def test_sampler_values_are_sent_over_http_and_default_omission_is_preserved(endpoint, manifest):
    messages = [{"role": "user", "content": "Synthetic wire validation."}]
    default = endpoint.config.validate(manifest)
    extended = replace(
        default, temperature=0.7, top_p=0.8, top_k=20, min_p=0.0, presence_penalty=1.5
    ).validate(manifest)
    for config in (default, extended):
        result = request(config, config.payload(messages))
        assert result["status"] == "COMPLETED"
    before, after = [r["body"] for r in endpoint.requests]
    assert "min_p" not in before and "presence_penalty" not in before
    assert after["min_p"] == 0.0 and after["presence_penalty"] == 1.5
    assert after["temperature"] == 0.7 and after["top_p"] == 0.8 and after["top_k"] == 20
    assert after["messages"] == before["messages"] == messages
    assert after["seed"] == before["seed"] == 20261111
    assert after["chat_template_kwargs"] == {"enable_thinking": False}
    assert after["cache_prompt"] is False
