"""Operator-pinned research space. Agent chooses bounded treatments, never executable code."""

import copy
import math

from native_llm_bench.contracts import Config, digest, keys, require
from native_llm_bench.instructions import text_hash

# Absolute controller limits, intersected with the operator's usually narrower bounds.
BOUNDS = {
    "temperature": (0, 2),
    "top_p": (0.00001, 1),
    "top_k": (0, 10000),
    "min_p": (0, 1),
    "presence_penalty": (0, 2),
    "repeat_penalty": (0.01, 3),
    "max_tokens": (1, 1024),
}
KINDS = {
    "sampling",
    "completion_budget",
    "policy_template",
    "locale_context",
    "template_observation",
    "stop_eos_observation",
    "native_control",
}
CONTROLS = {
    "sampling": set(BOUNDS) - {"max_tokens"},
    "completion_budget": {"max_tokens"},
    "stop_eos_observation": {"max_tokens"},
    "policy_template": set(),
    "locale_context": set(),
    "template_observation": set(),
    "native_control": set(),
}


def validate_policy(policy):
    from .contracts import bounded_text, identifier

    keys(policy, ("version", "policy_id", "baseline", "bounds", "instructions", "profiles"))
    require(policy["version"] == "1.0.0", "unsupported_experiment_policy")
    identifier(policy["policy_id"])
    require(
        isinstance(policy["baseline"], dict) and set(policy["baseline"]) <= set(BOUNDS),
        "forbidden_baseline_control",
    )
    require(
        isinstance(policy["bounds"], dict) and set(policy["bounds"]) <= set(BOUNDS),
        "forbidden_experiment_control",
    )
    for control, value in policy["baseline"].items():
        require(
            type(value) in (int, float)
            and math.isfinite(value)
            and BOUNDS[control][0] <= value <= BOUNDS[control][1],
            "invalid_baseline_control",
        )
    for control, interval in policy["bounds"].items():
        keys(interval, ("min", "max"))
        lo, hi = interval["min"], interval["max"]
        require(
            all(type(v) in (int, float) and math.isfinite(v) for v in (lo, hi))
            and BOUNDS[control][0] <= lo <= hi <= BOUNDS[control][1],
            "invalid_control_bound",
        )
        if control in {"top_k", "max_tokens"}:
            require(type(lo) is int and type(hi) is int, "integer_control_required")
    require(isinstance(policy["instructions"], dict), "invalid_instruction_registry")
    for vid, instruction in policy["instructions"].items():
        identifier(vid)
        keys(instruction, ("suffix", "sha256"))
        bounded_text(instruction["suffix"], 8000)
        require(
            instruction["sha256"] == text_hash(instruction["suffix"]), "instruction_hash_mismatch"
        )
    require(isinstance(policy["profiles"], dict) and policy["profiles"], "missing_profiles")
    for pid, profile in policy["profiles"].items():
        identifier(pid)
        keys(profile, ("type", "controls", "instruction_variants", "languages", "turn_counts"))
        require(profile["type"] in KINDS, "unknown_experiment_type")
        for name in ("controls", "instruction_variants", "languages", "turn_counts"):
            values = profile[name]
            require(
                isinstance(values, list)
                and all(type(v) in (str, int) for v in values)
                and len(values) == len(set(values)),
                "invalid_profile_allowlist",
            )
        require(
            set(profile["controls"]) <= CONTROLS[profile["type"]]
            and set(profile["controls"]) <= set(policy["bounds"]),
            "control_not_authorized",
        )
        require(
            set(profile["instruction_variants"]) <= set(policy["instructions"]),
            "instruction_not_authorized",
        )
        require(
            not profile["instruction_variants"] or profile["type"] == "policy_template",
            "instruction_type_mismatch",
        )
        require(
            profile["languages"]
            and set(profile["languages"]) <= {"RU", "EN", "MIXED"}
            and profile["turn_counts"]
            and set(profile["turn_counts"]) <= {2, 3, 4, 5},
            "invalid_sample_bounds",
        )
    # Same existing Config validation also rejects invalid baseline values before inference.
    c = Config(**policy["baseline"])
    c.validate({"model_id": c.model, "context_tokens": c.context_tokens})
    return copy.deepcopy(policy)


def prepare(policy, corpus, profile_id, parameters, sessions):
    """No model text becomes instructions; only exact operator-registered suffix bytes."""
    require(profile_id in policy["profiles"] and isinstance(parameters, dict), "invalid_treatment")
    profile = policy["profiles"][profile_id]
    require(
        set(parameters) <= set(profile["controls"]) | {"instruction_variant"},
        "control_not_authorized",
    )
    numeric = {k: v for k, v in parameters.items() if k != "instruction_variant"}
    require(len(numeric) <= 1, "one_primary_control_required")
    for control, value in numeric.items():
        b = policy["bounds"][control]
        require(
            type(value) in (int, float) and math.isfinite(value) and b["min"] <= value <= b["max"],
            "treatment_out_of_bounds",
        )
        if control in {"top_k", "max_tokens"}:
            require(type(value) is int, "integer_control_required")
    for s in corpus["sessions"]:
        if s["session_id"] in sessions:
            require(
                s["language"] in profile["languages"] and len(s["turns"]) in profile["turn_counts"],
                "sample_condition_not_authorized",
            )
    derived = corpus
    if "instruction_variant" in parameters:
        vid = parameters["instruction_variant"]
        require(
            isinstance(vid, str) and vid in profile["instruction_variants"],
            "instruction_not_authorized",
        )
        suffix = policy["instructions"][vid]["suffix"]
        derived = copy.deepcopy(corpus)
        derived["instructions"] = {
            k: v + "\n\n" + suffix for k, v in corpus["instructions"].items()
        }
        derived["corpus_version"] += ".research." + digest({"policy": policy, "variant": vid})[:16]
    return derived, {**policy["baseline"], **numeric}
