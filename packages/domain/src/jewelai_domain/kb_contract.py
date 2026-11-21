"""Knowledge Library Contract 2.0.0 (ADR 0048): deterministic, storage-independent rules.

This module holds the parts of the PostgreSQL ``kb`` contract that must behave identically
everywhere: vocabularies, the permission policy revision taken from Knowledge Library v1.6.2,
scope normalization, canonical hashing and the source-specific validation profiles of
Architecture v1.2 (ARCH-KB-03). It performs no I/O and never calls a model or provider.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

KB_CONTRACT_VERSION = "2.0.0"

STATUSES = ("VERIFIED", "REFERENCE ONLY", "REJECTED")
REVISION_STATES = ("draft", "published")
EVIDENCE_ROLES = ("supports", "contradicts")
EVIDENCE_TIERS = ("Q1", "Q2", "Q3", "Q4")
VALUE_TYPES = ("number", "range", "enum", "text")
# How a stored value relates to its source (v1.2 §13 item 14).
VALUE_KINDS = ("exact", "source_range", "approximate", "derived", "text")

# Concrete actions a permission code can allow (v1.2 §5).
USES = (
    "display",
    "display_caveat",
    "explain",
    "prompt",
    "calc_reference",
    "legal_info",
    "validate_warn",
    "validate_block",
)
# Read-only purposes (v1.2 §8). They never grant an action permission.
READ_PURPOSES = ("resolve", "verify_evidence", "search", "release_metadata")
PURPOSES = READ_PURPOSES + USES

ERROR_CODES = (
    "unknown_entity",
    "ambiguous_term",
    "no_data",
    "release_not_found",
    "release_unavailable",
    "purpose_not_allowed",
    "scope_conflict",
    "evidence_conflict",
    "payload_conflict",
)

EVALUATION_RESULTS = ("supported", "contradicted", "unknown", "review_required")

# Outcomes of a validation profile. Only source_match can carry VERIFIED (ARCH-KB-03).
PROFILE_OUTCOMES = (
    "source_match",
    "within_range",
    "derived_estimate",
    "conflict",
    "mismatch",
    "no_source",
)

PROFILE_METHODS = (
    "exact_number",
    "source_range",
    "ordinal_scale",
    "approximate_point",
    "typical_range",
    "formula",
    "enum_match",
    "manual_source_review",
)

FORMULAS = (
    "ring_us_from_diameter",
    "ring_eu_from_diameter",
    "ring_uk_from_diameter",
)

ROUNDING = ("nearest_half", "nearest_int", "floor")

# Closed scope vocabulary. Unknown keys are rejected so that "same claim" is decidable.
SCOPE_KEYS = (
    "origin",
    "treatment",
    "shape",
    "reference",
    "from_system",
    "from_value",
    "to_system",
    "carat_weight",
    "alloy_grade",
    "jurisdiction",
    "document",
    "clause",
    "effective_from",
    "effective_to",
    "legacy_parameter",
    "legacy_k_id",
)
NORMATIVE_SCOPE_KEYS = ("jurisdiction", "document", "clause", "effective_from")

RELEASE_ARTIFACT_KINDS = (
    "term",
    "term_relation",
    "rule",
    "policy",
    "evidence",
    "validation_profile",
)

TERM_RELATIONS = ("synonym", "false_equivalent", "ambiguous", "broader", "narrower")
RULE_SEVERITIES = ("info", "warn", "block")


class KnowledgeKbError(Exception):
    """Typed contract error. ``code`` is always one of ERROR_CODES."""

    def __init__(self, code: str, detail: str = "") -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown knowledge error code: {code}")
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class PolicyDefinition:
    permission_code: str
    allowed_status: str
    uses: tuple[str, ...]
    prompt_conditions: str
    forbidden: str
    conditions: str


# Policy revision 1: the permission matrix of Knowledge Library v1.6.2 (v1.2 §5).
# validate_warn and validate_block are granted to no code in this revision.
POLICY_REVISION_1: tuple[PolicyDefinition, ...] = (
    PolicyDefinition(
        "FACT_DISPLAY_RENDER_HINT",
        "VERIFIED",
        ("display", "explain", "prompt"),
        "Gem constant with mineral, parameter and source; never a property of a specific stone",
        "Silently changing Product State; claiming quality of a specific specimen",
        "Exact match of material, property and source",
    ),
    PolicyDefinition(
        "APPROX_SIZE_REFERENCE",
        "VERIFIED",
        ("display", "explain", "prompt"),
        "Only with ≈; one relevant weight/diameter pair; never a production tolerance",
        "Exact seat or production tolerances, certification",
        "A specific stone needs a measurement",
    ),
    PolicyDefinition(
        "NONBINDING_UNIT_CONVERSION",
        "VERIFIED",
        ("display", "explain", "calc_reference", "prompt"),
        "State the source system and rounding; not an ISO or legal certification",
        "Treating different national systems as legally identical",
        "Record the source system and rounding step",
    ),
    PolicyDefinition(
        "NONBINDING_PURITY_CONVERSION",
        "VERIFIED",
        ("display", "explain", "prompt"),
        "Descriptive metal fraction only; 585 corresponds to 14K commercially, not literally",
        "Hallmarking and compliance",
        "The formula does not replace a statutory assay check",
    ),
    PolicyDefinition(
        "FACT_PARTIAL_DISPLAY_ONLY",
        "VERIFIED",
        ("display",),
        "",
        "Using unverified companion parts automatically",
        "Only the confirmed atomic fragment may be shown until atomized",
    ),
    PolicyDefinition(
        "CARE_GUIDANCE_CONDITIONAL",
        "VERIFIED",
        ("display", "explain"),
        "",
        "Assigning cleaning automatically for an unknown item",
        "Needs fracture, treatment, coating and setting data",
    ),
    PolicyDefinition(
        "VENDOR_MATERIAL_REFERENCE",
        "VERIFIED",
        ("display", "explain", "calc_reference"),
        "",
        "Production tolerance, acceptance and regulatory control",
        "Pure metals from an external reference",
    ),
    PolicyDefinition(
        "GOST_ALLOY_DENSITY_REFERENCE",
        "VERIFIED",
        ("display", "explain", "calc_reference"),
        "",
        "Design tolerance, legal compliance, mandatory mass calculation, prompt or render",
        "The alloy must match the grade exactly; values are calculated reference densities",
    ),
    PolicyDefinition(
        "LEGAL_INFORMATION_ONLY",
        "VERIFIED",
        ("legal_info",),
        "",
        "Legal PASS/FAIL; obligation without product-category analysis",
        "Atomic norm with clause, edition, jurisdiction and date",
    ),
    PolicyDefinition(
        "FACT_DISPLAY_ONLY",
        "VERIFIED",
        ("display", "explain"),
        "",
        "Automatic decisions beyond the proven content",
        "Source-bound, not a universal guarantee",
    ),
    PolicyDefinition(
        "RESEARCH_WITH_CAVEAT",
        "REFERENCE ONLY",
        ("display_caveat", "explain"),
        "",
        "Automatic decisions, regulatory checks, production calculation, prompt",
        "State the incomplete verification and the source",
    ),
    PolicyDefinition(
        "EXCLUDE",
        "REJECTED",
        (),
        "",
        "Showing as a fact, retrieval, automation",
        "Kept only as a historical trace",
    ),
)

POLICY_CODES = tuple(policy.permission_code for policy in POLICY_REVISION_1)


def canonical_json(value: Any) -> str:
    """Repository canonical form: sorted compact JSON over exact UTF-8 (ADR 0035)."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def sha256_hex(value: Any) -> str:
    payload = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_term(text: str) -> str:
    """Same bounded normalization as the Domain Dictionary: NFKC, casefold, whitespace."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def canonical_number(value: Any) -> str:
    """Exact decimal string without exponent or trailing zeros; rejects NaN/inf/bool."""
    if isinstance(value, bool) or value is None:
        raise ValueError("number required")
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f"not a number: {value!r}") from error
    if not number.is_finite():
        raise ValueError("finite number required")
    text = format(number.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def normalize_scope(scope: dict[str, Any] | None) -> tuple[dict[str, str], str]:
    """Return the normalized scope and its scope_key. Keys must belong to SCOPE_KEYS."""
    scope = scope or {}
    unknown = sorted(set(scope) - set(SCOPE_KEYS))
    if unknown:
        raise ValueError(f"unknown scope keys: {unknown}")
    normalized: dict[str, str] = {}
    for key in sorted(scope):
        raw = scope[key]
        if raw is None:
            continue
        if isinstance(raw, bool):
            raise ValueError(f"scope {key} must not be boolean")
        if isinstance(raw, int | float | Decimal):
            normalized[key] = canonical_number(raw)
        elif isinstance(raw, str) and raw.strip():
            normalized[key] = " ".join(unicodedata.normalize("NFKC", raw).split())
        else:
            raise ValueError(f"scope {key} must be a non-empty string or number")
    return normalized, canonical_json(normalized)


def normalize_value(value: dict[str, Any], value_type: str) -> dict[str, str]:
    """Typed value as canonical strings: number→num, range→min/max, enum, text→text_ru/en."""
    if value_type not in VALUE_TYPES:
        raise ValueError(f"unknown value type: {value_type}")
    allowed = {
        "number": {"num"},
        "range": {"min", "max"},
        "enum": {"enum"},
        "text": {"text_ru", "text_en"},
    }[value_type]
    extra = sorted(set(value) - allowed)
    if extra:
        raise ValueError(f"{value_type} value has unexpected fields: {extra}")
    result: dict[str, str] = {}
    if value_type == "number":
        result["num"] = canonical_number(value["num"])
    elif value_type == "range":
        low, high = Decimal(canonical_number(value["min"])), Decimal(canonical_number(value["max"]))
        if low > high:
            raise ValueError("range min must not exceed max")
        result["min"], result["max"] = canonical_number(low), canonical_number(high)
    elif value_type == "enum":
        enum = str(value["enum"]).strip()
        if not enum or not enum.replace("_", "").replace(".", "").isalnum():
            raise ValueError("enum must be a machine identifier")
        result["enum"] = enum
    else:
        for key in ("text_ru", "text_en"):
            if value.get(key):
                result[key] = str(value[key]).strip()
        if not result:
            raise ValueError("text value needs text_ru or text_en")
    for text in result.values():
        if text.startswith("="):
            raise ValueError("values must not start with '=' (spreadsheet formula risk)")
    return result


def policy_by_code(policies: tuple[PolicyDefinition, ...] = POLICY_REVISION_1):
    return {policy.permission_code: policy for policy in policies}


def allowed_uses(permission_code: str, status: str, policies=POLICY_REVISION_1) -> tuple[str, ...]:
    """Uses granted by the policy revision; empty when the status is incompatible."""
    policy = policy_by_code(policies).get(permission_code)
    if policy is None or policy.allowed_status != status or status == "REJECTED":
        return ()
    return tuple(use for use in policy.uses if use != "validate_block")


# ---------------------------------------------------------------- validation profiles


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _quantize(value: Decimal, precision: int | None) -> Decimal:
    if precision is None:
        return value
    return value.quantize(Decimal(1).scaleb(-precision))


def _round(value: float, rounding: str) -> Decimal:
    if rounding == "nearest_half":
        return Decimal(math.floor(value * 2 + 0.5)) / 2
    if rounding == "nearest_int":
        return Decimal(math.floor(value + 0.5))
    if rounding == "floor":
        return Decimal(math.floor(value))
    raise ValueError(f"unknown rounding: {rounding}")


UK_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def apply_formula(formula: str, rounding: str, from_value: str) -> str:
    """Ring-size conversions from an inner diameter in mm (EV-RING: ISO 8653 and US/UK rules).

    US: d = 11.63 + 0.8128 × size. EU: ISO size = inner circumference in mm. UK: letter C is
    a 40 mm circumference with 1.25 mm per letter. Rounding is part of the published profile.
    """
    diameter = float(Decimal(from_value))
    if formula == "ring_us_from_diameter":
        return canonical_number(_round((diameter - 11.63) / 0.8128, rounding))
    if formula == "ring_eu_from_diameter":
        return canonical_number(_round(math.pi * diameter, rounding))
    if formula == "ring_uk_from_diameter":
        steps = int(_round((math.pi * diameter - 40.0) / 1.25, rounding))
        index = UK_LETTERS.index("C") + steps
        if not 0 <= index < len(UK_LETTERS):
            raise ValueError("UK ring size outside A–Z")
        return UK_LETTERS[index]
    raise ValueError(f"unknown formula: {formula}")


def evaluate_profile(
    method: str,
    params: dict[str, Any],
    claim_value: dict[str, str],
    value_kind: str,
    source_value: dict[str, str] | None,
    scope: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Return (outcome, reason). Deterministic; never widens a source by a generic tolerance."""
    if method not in PROFILE_METHODS:
        raise ValueError(f"unknown profile method: {method}")
    if method == "manual_source_review":
        return "no_source", "no automatic source comparison exists for this attribute"
    if method == "formula":
        scope = scope or {}
        if "from_value" not in scope:
            return "no_source", "conversion scope has no from_value"
        expected = apply_formula(params["formula"], params["rounding"], scope["from_value"])
        actual = claim_value.get("num") or claim_value.get("enum")
        if actual == expected:
            return "source_match", f"{params['formula']} with {params['rounding']} gives {expected}"
        return "mismatch", f"{params['formula']} with {params['rounding']} gives {expected}"
    if source_value is None:
        return "no_source", "no verified source value is linked"
    precision = params.get("precision")
    if method == "enum_match":
        if claim_value.get("enum") == source_value.get("enum"):
            return "source_match", "enum equals the source statement"
        return "mismatch", "enum differs from the source statement"
    if method == "exact_number":
        claim, source = _dec(claim_value.get("num")), _dec(source_value.get("num"))
        if claim is None or source is None:
            return "mismatch", "exact_number needs single numbers"
        if _quantize(claim, precision) == _quantize(source, precision):
            return "source_match", "equal at the source precision"
        return "mismatch", f"{claim} differs from source {source}"
    if method in ("source_range", "ordinal_scale", "typical_range"):
        low, high = _dec(source_value.get("min")), _dec(source_value.get("max"))
        if low is None:
            low = high = _dec(source_value.get("num"))
        if low is None:
            return "mismatch", "source has no number or range"
        if "num" in claim_value:
            value = _quantize(Decimal(claim_value["num"]), precision)
            if low == high and value == _quantize(low, precision):
                return "source_match", "equal to the source value"
            if low <= value <= high:
                return "within_range", "inside the source range but narrower than the source"
            return "mismatch", f"{value} outside source {low}–{high}"
        claim_low, claim_high = _dec(claim_value.get("min")), _dec(claim_value.get("max"))
        if claim_low is None or claim_high is None:
            return "mismatch", "claim has no number or range"
        if (_quantize(claim_low, precision), _quantize(claim_high, precision)) == (
            _quantize(low, precision),
            _quantize(high, precision),
        ):
            return "source_match", "range equals the source range"
        if low <= claim_low and claim_high <= high:
            return "within_range", "narrower than the source range"
        return "mismatch", f"{claim_low}–{claim_high} differs from source {low}–{high}"
    if method == "approximate_point":
        if value_kind == "derived":
            return "derived_estimate", "interpolated or derived point, not a published point"
        if value_kind != "approximate":
            return "mismatch", "a published approximate point must be stored as approximate"
        if "num" not in claim_value:
            return "mismatch", "a reference point must be one number, not a mixed range"
        source = _dec(source_value.get("num"))
        if source is not None and _quantize(Decimal(claim_value["num"]), precision) == (
            _quantize(source, precision)
        ):
            return "source_match", "equal to the published reference point"
        return "mismatch", "differs from the published reference point"
    raise AssertionError(method)


def contract_document() -> dict[str, Any]:
    """Machine-readable contract published in specs/knowledge-library-kb."""
    return {
        "contract_id": "jewelai.knowledge_library.kb",
        "contract_version": KB_CONTRACT_VERSION,
        "architecture": "Knowledge Library Architecture v1.2 (Owner-approved 2026-11-20)",
        "adr": "docs/adr/0048-knowledge-library-kb-postgresql-contract-2.md",
        "statuses": list(STATUSES),
        "revision_states": list(REVISION_STATES),
        "evidence_roles": list(EVIDENCE_ROLES),
        "evidence_tiers": list(EVIDENCE_TIERS),
        "value_types": list(VALUE_TYPES),
        "value_kinds": list(VALUE_KINDS),
        "uses": list(USES),
        "read_purposes": list(READ_PURPOSES),
        "error_codes": list(ERROR_CODES),
        "evaluation_results": list(EVALUATION_RESULTS),
        "profile_methods": list(PROFILE_METHODS),
        "profile_outcomes": list(PROFILE_OUTCOMES),
        "formulas": list(FORMULAS),
        "rounding": list(ROUNDING),
        "scope_keys": list(SCOPE_KEYS),
        "normative_scope_keys": list(NORMATIVE_SCOPE_KEYS),
        "release_artifact_kinds": list(RELEASE_ARTIFACT_KINDS),
        "term_relations": list(TERM_RELATIONS),
        "rule_severities": list(RULE_SEVERITIES),
        "policy_revision_1": [
            {
                "permission_code": policy.permission_code,
                "allowed_status": policy.allowed_status,
                "uses": list(policy.uses),
                "prompt_conditions": policy.prompt_conditions,
                "forbidden": policy.forbidden,
                "conditions": policy.conditions,
            }
            for policy in POLICY_REVISION_1
        ],
        "invariants": [
            "Published revisions and release membership are never updated or deleted.",
            "Only profile outcome source_match may be published as VERIFIED.",
            "Read-only purposes never grant an action permission.",
            "validate_block is disabled in policy revision 1.",
            "Knowledge API reads never write Product State.",
        ],
    }
