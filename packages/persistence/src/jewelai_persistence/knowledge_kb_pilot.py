"""Load the Knowledge Library 2.0 pilot seed as drafts with re-qualification (ADR 0048 §9).

A record proposed as VERIFIED by v1.6.2 becomes VERIFIED only when its validation profile
returns ``source_match`` against the linked source value; otherwise it is drafted as
REFERENCE ONLY with code RESEARCH_WITH_CAVEAT and the profile reason. Nothing is published
here; the administrator still runs validate → diff → publish → activate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jewelai_domain.kb_contract import (
    POLICY_REVISION_1,
    evaluate_profile,
    normalize_scope,
    normalize_value,
    sha256_hex,
)
from sqlalchemy.orm import Session

from .knowledge_kb import KbAdmin

SEED_PATH = Path(__file__).resolve().parents[4] / "data/knowledge-kb/pilot-v1.6.2.json"
DEMOTED_CODE = "RESEARCH_WITH_CAVEAT"


def read_seed(path: Path = SEED_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def claim_identity(entity_id: str, attribute_id: str, scope: dict[str, Any]) -> str:
    _, scope_key = normalize_scope(scope)
    return f"clm:{entity_id}:{attribute_id}:{sha256_hex(scope_key)[:12]}"


def requalify(claim: dict[str, Any], attribute: dict, profile: dict) -> dict[str, Any]:
    """Return status, permission and qualification for one proposed record."""
    value = normalize_value(claim["value"], attribute["value_type"])
    scope, _ = normalize_scope(claim["scope"])
    proposed, code = claim["proposed_status"], claim["permission_code"]
    outcomes = []
    for link in claim["evidence"]:
        source = link.get("source_value")
        source = None if source is None else normalize_value(source, attribute["value_type"])
        outcomes.append(
            evaluate_profile(
                profile["method"], profile["params"], value, claim["value_kind"], source, scope
            )
        )
    outcome, reason = next(
        (o for o in outcomes if o[0] == "source_match"),
        outcomes[0] if outcomes else ("no_source", "no evidence linked"),
    )
    qualification = {
        "method": profile["method"],
        "profile_revision_id": f"{profile['profile_id']}@1",
        "outcome": outcome,
        "reason": reason,
        "proposed_status": proposed,
        "proposed_permission_code": code,
    }
    if proposed == "VERIFIED" and outcome != "source_match":
        return {
            "status": "REFERENCE ONLY",
            "permission_code": DEMOTED_CODE,
            "qualification": {**qualification, "demoted": True},
        }
    return {"status": proposed, "permission_code": code, "qualification": qualification}


def load_seed(session: Session, seed: dict[str, Any], actor: str) -> dict[str, Any]:
    admin = KbAdmin(session, actor)
    for entity in seed["entities"]:
        admin.ensure_entity(
            entity["entity_id"],
            entity["entity_type"],
            parent_id=entity["parent_id"],
            label_ru=entity["label_ru"],
            label_en=entity["label_en"],
        )
    attributes = {a["attribute_id"]: a for a in seed["attributes"]}
    for attribute in seed["attributes"]:
        admin.ensure_attribute(
            attribute["attribute_id"],
            attribute["value_type"],
            attribute["validation_profile_id"],
            unit=attribute["unit"],
            scale=attribute["scale"],
        )
    profiles = {p["profile_id"]: p for p in seed["validation_profiles"]}
    reason = f"pilot import from {seed['source']['library']}"
    for profile in seed["validation_profiles"]:
        admin.draft_artifact(
            "validation_profile",
            f"{profile['profile_id']}@1",
            reason,
            profile_id=profile["profile_id"],
            method=profile["method"],
            params=profile["params"],
        )
    for policy in POLICY_REVISION_1:
        admin.draft_artifact(
            "policy",
            f"policy-r1:{policy.permission_code}",
            "policy revision 1 = Knowledge Library v1.6.2 permission matrix",
            permission_code=policy.permission_code,
            allowed_status=policy.allowed_status,
            uses=list(policy.uses),
            prompt_conditions=policy.prompt_conditions,
            forbidden=policy.forbidden,
            conditions=policy.conditions,
        )
    for evidence in seed["evidence"]:
        admin.draft_artifact(
            "evidence",
            f"{evidence['ev_id']}@1",
            reason,
            ev_id=evidence["ev_id"],
            org=evidence["org"],
            title=evidence["title"],
            url=evidence["url"],
            retrieved_at=evidence["retrieved_at"],
            fragment=evidence["fragment"],
            tier=evidence["tier"],
            limitations=evidence["limitations"],
        )
    for term in seed["terms"]:
        admin.draft_artifact(
            "term",
            f"{term['term_id']}@1",
            reason,
            term_id=term["term_id"],
            entity_id=term["entity_id"],
            lang=term["lang"],
            text=term["text"],
            kind=term["kind"],
            is_preferred=term["is_preferred"],
        )
    for relation in seed["term_relations"]:
        admin.draft_artifact(
            "term_relation",
            f"{relation['relation_id']}@1",
            reason,
            relation_id=relation["relation_id"],
            term_a=relation["term_a"],
            term_b=relation["term_b"],
            relation=relation["relation"],
            note=relation["note"],
        )
    for caller in seed["callers"]:
        admin.register_caller(caller["caller_id"], caller["description"], caller["purposes"])
    report = {"verified": 0, "reference_only": 0, "rejected": 0, "demoted": []}
    for claim in seed["claims"]:
        attribute = attributes[claim["attribute_id"]]
        decision = requalify(claim, attribute, profiles[attribute["validation_profile_id"]])
        claim_id = claim_identity(claim["entity_id"], claim["attribute_id"], claim["scope"])
        admin.draft_claim(
            entity_id=claim["entity_id"],
            attribute_id=claim["attribute_id"],
            scope=claim["scope"],
            revision_id=f"{claim_id}@1",
            value=claim["value"],
            value_kind=claim["value_kind"],
            status=decision["status"],
            permission_code=decision["permission_code"],
            qualification=decision["qualification"],
            reason=claim["reason"],
            evidence=[
                {
                    "ev_revision_id": f"{link['ev_id']}@1",
                    "role": "supports",
                    "check_id": decision["qualification"]["method"],
                    "source_value": link.get("source_value")
                    and normalize_value(link["source_value"], attribute["value_type"]),
                }
                for link in claim["evidence"]
            ],
        )
        for k_id, mapping_type, explanation in claim["legacy"]:
            target_kind = "excluded" if mapping_type == "excluded" else "claim"
            admin.map_legacy(k_id, target_kind, claim_id, mapping_type, explanation)
        key = {"VERIFIED": "verified", "REFERENCE ONLY": "reference_only", "REJECTED": "rejected"}
        report[key[decision["status"]]] += 1
        if decision["qualification"].get("demoted"):
            report["demoted"].append(
                {
                    "claim_id": claim_id,
                    "legacy": [k for k, _, _ in claim["legacy"]],
                    "reason": decision["qualification"]["reason"],
                }
            )
    session.flush()
    return report
