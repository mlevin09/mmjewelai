"""Operator-supplied activation, immutable inputs and sealed experimental choices."""

import copy
import re
from dataclasses import replace
from pathlib import Path

from native_llm_bench import storage
from native_llm_bench.contracts import (
    Config,
    digest,
    execution_plan,
    keys,
    require,
    sha256_file,
    validate_manifest,
    validate_runtime,
)
from native_llm_bench.instructions import BREVITY_PROFILE, BREVITY_SUFFIX, text_hash

VERSION = "1.0.0"
TARGET = {"project": "mmjewellai-preprod", "zone": "europe-west1-b", "vm": "jewelai-llm-lab"}
MODEL = "qwen3-1.7b-q4_k_m"
MODEL_SHA = "d2387ca2dbfee2ffabce7120d3770dadca0b293052bc2f0e138fdc940d9bc7b5"
RUNTIME_SHA = "eaf9c1c664cc0ae1f4dea4b171bb91aac8409fcfea0574c9b6bcc93792ce2400"
RUNTIME_COMMIT = "cd959bae99ff4bed22bef2604f45241c09bbb8c8"
# Independent of mutable corpus flags. Eleven reserved questions, including grouped sessions.
HOLDOUTS = {
    "KG09",
    "KJ08",
    "KJ12",
    *[f"G{i}" for i in range(26, 31)],
    *[f"J{i}" for i in (35, 36, 37, 48, 49, 50)],
}
PROFILES = {
    "NATIVE_CONTROL_V1": {"type": "native_control", "changes": {}},
    "SAMPLING_LOW_TEMP_V1": {"type": "sampling", "changes": {"temperature": 0.2}},
    "BREVITY_POLICY_V1": {"type": "policy_template", "changes": {}},
}
PROFILE_SHA = digest(PROFILES)
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")


def identifier(value):
    require(isinstance(value, str) and bool(SAFE_ID.fullmatch(value)), "invalid_identifier")
    return value


def bounded_text(value, limit=4000):
    require(isinstance(value, str) and 0 < len(value.strip()) <= limit, "invalid_text")
    return value


def source_identity():
    root = Path(__file__).parent
    return digest({p.name: sha256_file(p) for p in sorted(root.glob("*.py"))})


def reserved(session):
    ids = [session["session_id"], *[t["turn_id"] for t in session["turns"]]]
    return session["holdout"] or any(i.split(".")[0] in HOLDOUTS for i in ids)


class Inputs:
    """Only runtime input enters inference. Evaluator bytes are pinned read-only, never loaded."""

    def __init__(self, corpus_path, manifest_path, evaluator_path=None, policy_path=None):
        from native_llm_bench.contracts import load

        self.paths = [Path(corpus_path), Path(manifest_path)]
        if evaluator_path is not None:
            self.paths.append(Path(evaluator_path))
        self.policy = None
        if policy_path is not None:
            from .experiments import validate_policy

            self.paths.append(Path(policy_path))
            self.policy = validate_policy(load(policy_path))
            require(not set(self.policy["profiles"]) & set(PROFILES), "reserved_profile_id")
        self.file_hashes = [sha256_file(p) for p in self.paths]
        self.corpus = validate_runtime(load(corpus_path))
        self.manifest = validate_manifest(load(manifest_path))
        self.runner_sha = storage.identity()["source_sha256"]
        self.controller_sha = source_identity()

    def pins(self):
        return {
            "corpus_sha256": digest(self.corpus),
            "manifest_sha256": digest(self.manifest),
            "file_sha256": self.file_hashes,
            "runner_sha256": self.runner_sha,
            "controller_sha256": self.controller_sha,
            "profiles_sha256": PROFILE_SHA,
            "experiment_policy_sha256": digest(self.policy),
        }

    def verify(self, envelope):
        require(self.pins() == envelope["pins"], "input_pin_mismatch")
        require([sha256_file(p) for p in self.paths] == self.file_hashes, "source_file_changed")
        require(storage.identity()["source_sha256"] == self.runner_sha, "runner_changed")
        require(source_identity() == self.controller_sha, "controller_changed")


def validate_envelope(e, inputs):
    keys(
        e,
        (
            "version",
            "campaign_id",
            "mode",
            "assignment",
            "subject",
            "target",
            "pins",
            "allowed_sessions",
            "allowed_profiles",
            "scheduling_seed",
            "inference_seed",
            "period_start",
            "period_end",
            "max_wall_seconds",
            "max_experiments",
            "max_turns",
            "max_attempts",
            "budget",
        ),
    )
    require(e["version"] == VERSION and e["mode"] in ("SYNTHETIC", "LIVE"), "invalid_version_mode")
    identifier(e["campaign_id"])
    bounded_text(e["assignment"])
    bounded_text(e["subject"], 200)
    require(e["target"] == TARGET, "wrong_vm")
    inputs.verify(e)
    for name in ("scheduling_seed", "inference_seed"):
        require(type(e[name]) is int and 0 <= e[name] < 2**32, "invalid_seed")
    for name in (
        "period_start",
        "period_end",
        "max_wall_seconds",
        "max_experiments",
        "max_turns",
        "max_attempts",
    ):
        require(type(e[name]) is int and e[name] > 0, "invalid_limit")
    require(e["period_end"] > e["period_start"], "invalid_period")
    require(e["max_wall_seconds"] <= e["period_end"] - e["period_start"], "invalid_wall_limit")
    for name, allowed in (
        ("allowed_profiles", {**PROFILES, **(inputs.policy["profiles"] if inputs.policy else {})}),
        (
            "allowed_sessions",
            {s["session_id"] for s in inputs.corpus["sessions"] if not reserved(s)},
        ),
    ):
        values = e[name]
        require(
            isinstance(values, list) and values and len(values) == len(set(values)),
            "invalid_allowlist",
        )
        require(set(values) <= set(allowed), "forbidden_profile_or_holdout")
    b = e["budget"]
    keys(
        b,
        (
            "unit",
            "hard_ceiling",
            "soft_limit",
            "attempt_cost",
            "lifecycle_reserve",
            "disk_reserve",
            "agent_reserve",
            "billing_guarantee",
        ),
    )
    require(b["unit"] == "proxy_microunits", "unsupported_budget_unit")
    for name in (
        "hard_ceiling",
        "soft_limit",
        "attempt_cost",
        "lifecycle_reserve",
        "disk_reserve",
        "agent_reserve",
    ):
        require(type(b[name]) is int and b[name] >= 0, "invalid_budget")
    reserve = b["lifecycle_reserve"] + b["disk_reserve"] + b["agent_reserve"]
    require(b["attempt_cost"] > 0 and reserve < b["hard_ceiling"], "insufficient_reserve")
    require(reserve <= b["soft_limit"] <= b["hard_ceiling"], "invalid_soft_limit")
    if e["mode"] == "SYNTHETIC":
        require(inputs.manifest["verification_status"] == "SYNTHETIC", "not_synthetic")
        require(all(s["kind"] == "synthetic" for s in inputs.corpus["sessions"]), "not_synthetic")
        require(b["billing_guarantee"] == "NO_PAID_CALLS", "invalid_synthetic_gate")
    else:
        m = inputs.manifest
        require(
            m["model_id"] == MODEL
            and m["model_sha256"] == MODEL_SHA
            and m["runtime_sha256"] == RUNTIME_SHA
            and m["runtime_commit"] == RUNTIME_COMMIT,
            "wrong_model_runtime",
        )
        # No exact billed-dollar limiter for GCP + Workspace credits is configured.
        # A proxy reservation is NOT such a guarantee, regardless of input prose.
        require(False, "live_activation_blocked_budget_and_workspace_authorization")
    return copy.deepcopy(e)


def experiment_runtime(inputs, profile, parameters, sessions):
    if profile in PROFILES:
        require(not parameters, "legacy_profile_has_no_parameters")
        return inputs.corpus, PROFILES[profile]["changes"]
    from .experiments import prepare

    require(inputs.policy is not None, "operator_policy_required")
    return prepare(inputs.policy, inputs.corpus, profile, parameters, sessions)


def experiment_plan(e, inputs, profile, sessions, parameters=None):
    require(profile in e["allowed_profiles"], "profile_not_authorized")
    require(
        isinstance(sessions, list)
        and sessions
        and len(sessions) == len(set(sessions))
        and set(sessions) <= set(e["allowed_sessions"]),
        "sample_not_authorized",
    )
    config = Config(model=inputs.manifest["model_id"], seed=e["inference_seed"], max_attempts=1)
    corpus, changes = experiment_runtime(
        inputs, profile, {} if parameters is None else parameters, sessions
    )
    config = replace(config, **changes)
    override = None
    if profile == "BREVITY_POLICY_V1":
        override = {
            "schema_version": "1.0.0",
            "profile_id": BREVITY_PROFILE,
            "base_runtime_sha256": digest(inputs.corpus),
            "suffix": BREVITY_SUFFIX,
            "suffix_sha256": text_hash(BREVITY_SUFFIX),
        }
    plan = execution_plan(
        corpus,
        config,
        inputs.manifest,
        e["scheduling_seed"],
        sessions,
        True,
        instruction_override=override,
    )
    return config, override, plan
