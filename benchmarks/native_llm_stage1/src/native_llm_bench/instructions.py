"""Explicit experiment registry; no arbitrary or scenario-specific prompt overrides."""

import hashlib

from .contracts import VERSION, digest, keys, require

BREVITY_PROFILE = "NB09D_BREVITY_SYSTEM_PROMPT_V1"
BREVITY_SUFFIX = (
    "Answer the user's actual question directly and concisely, in the language of the latest "
    "user message. Avoid repetition, unnecessary introductions, and unsolicited tangents. "
    "Preserve every essential requirement, quantity, negation, and correction. Do not invent "
    "facts, measurements, standards, or materials. If essential information is missing or "
    "ambiguous, say so briefly and ask only the necessary clarification. Keep the answer as "
    "short as possible without sacrificing correctness or completeness."
)
PROVENANCE_FIELDS = (
    "instruction_profile_id",
    "instruction_override_sha256",
    "effective_system_sha256",
)


def text_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def instruction_variation(corpus, sessions, manifest):
    keys(
        manifest, ("schema_version", "profile_id", "base_runtime_sha256", "suffix", "suffix_sha256")
    )
    require(manifest["schema_version"] == VERSION, "unsupported instruction override schema")
    require(manifest["profile_id"] == BREVITY_PROFILE, "untracked instruction profile")
    require(
        manifest["base_runtime_sha256"] == digest(corpus), "instruction override corpus mismatch"
    )
    require(manifest["suffix"] == BREVITY_SUFFIX, "unapproved instruction suffix")
    require(
        manifest["suffix_sha256"] == text_hash(BREVITY_SUFFIX), "instruction suffix hash mismatch"
    )
    effective = {}
    for instruction_id in sorted({s["instruction_id"] for s in sessions}):
        original = corpus["instructions"][instruction_id]
        content = original + "\n\n" + BREVITY_SUFFIX
        effective[instruction_id] = {
            "content": content,
            "original_sha256": text_hash(original),
            "effective_sha256": text_hash(content),
        }
    return {
        "manifest": dict(manifest),
        "manifest_sha256": digest(manifest),
        "effective_instructions": effective,
        "session_instruction_ids": {s["session_id"]: s["instruction_id"] for s in sessions},
    }


def system_instruction(corpus, session, plan):
    variation = plan.get("instruction_override")
    if variation is None:
        return corpus["instructions"][session["instruction_id"]], {}
    effective = variation["effective_instructions"][session["instruction_id"]]
    return effective["content"], {
        "instruction_profile_id": variation["manifest"]["profile_id"],
        "instruction_override_sha256": variation["manifest_sha256"],
        "effective_system_sha256": effective["effective_sha256"],
    }


def validate_request_instruction(plan, request):
    """Inspect/export must also reject mismatched or untracked override provenance."""
    variation = plan.get("instruction_override")
    expected = {}
    if variation is not None:
        instruction_id = variation["session_instruction_ids"][request["session_id"]]
        effective = variation["effective_instructions"][instruction_id]
        expected = {
            "instruction_profile_id": variation["manifest"]["profile_id"],
            "instruction_override_sha256": variation["manifest_sha256"],
            "effective_system_sha256": effective["effective_sha256"],
        }
        systems = [m for m in request["payload"]["messages"] if m["role"] == "system"]
        require(
            systems == [{"role": "system", "content": effective["content"]}]
            and request["payload"]["messages"][0] == systems[0],
            "request instruction content mismatch",
        )
    require(
        {k: request[k] for k in PROVENANCE_FIELDS if k in request} == expected,
        "request instruction provenance mismatch",
    )
