"""Knowledge Library Contract 2.0 services (ADR 0048, Architecture v1.2 §6–§8).

``KbAdmin`` is the administrator path: drafts → ``validate`` → ``diff`` → ``publish`` →
``activate``; ``revert`` and ``export_release``/``import_release`` never change published rows.
``KnowledgeApi`` is the read-only runtime path. Every call runs in a READ ONLY transaction on
PostgreSQL, requires an explicit purpose and pinned release, checks the caller and applies the
policy revision pinned by that release.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from jewelai_domain.kb_contract import (
    KB_CONTRACT_VERSION,
    NORMATIVE_SCOPE_KEYS,
    PURPOSES,
    READ_PURPOSES,
    STATUSES,
    USES,
    KnowledgeKbError,
    canonical_json,
    evaluate_profile,
    normalize_scope,
    normalize_term,
    normalize_value,
    sha256_hex,
)
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session, sessionmaker

from .kb_models import (
    KbActiveReleaseRow,
    KbAttributeRow,
    KbCallerRow,
    KbChangeLogRow,
    KbClaimEvidenceRow,
    KbClaimRevisionRow,
    KbClaimRow,
    KbEntityRow,
    KbEvidenceRevisionRow,
    KbPolicyRevisionRow,
    KbReleaseArtifactRow,
    KbReleaseClaimRow,
    KbReleaseRetirementRow,
    KbReleaseRow,
    KbRuleRevisionRow,
    KbTermRelationRevisionRow,
    KbTermRevisionRow,
    KbValidationProfileRevisionRow,
)

ACTIVE_SLOT = "default"

# Artifact kind → (row class, revision id column, stable object id column, content columns)
ARTIFACTS: dict[str, tuple[type, str, str, tuple[str, ...]]] = {
    "validation_profile": (
        KbValidationProfileRevisionRow,
        "profile_revision_id",
        "profile_id",
        ("method", "params"),
    ),
    "policy": (
        KbPolicyRevisionRow,
        "policy_revision_id",
        "permission_code",
        ("allowed_status", "uses", "prompt_conditions", "forbidden", "conditions"),
    ),
    "evidence": (
        KbEvidenceRevisionRow,
        "ev_revision_id",
        "ev_id",
        (
            "org",
            "title",
            "url",
            "edition",
            "retrieved_at",
            "fragment",
            "tier",
            "snapshot_uri",
            "content_hash",
            "limitations",
        ),
    ),
    "term": (
        KbTermRevisionRow,
        "term_revision_id",
        "term_id",
        ("entity_id", "lang", "text", "normalized_form", "kind", "is_preferred", "context"),
    ),
    "term_relation": (
        KbTermRelationRevisionRow,
        "relation_revision_id",
        "relation_id",
        ("term_a", "term_b", "relation", "context", "note"),
    ),
    "rule": (
        KbRuleRevisionRow,
        "rule_revision_id",
        "rule_id",
        (
            "kind",
            "expression",
            "depends_on",
            "status",
            "permission_code",
            "severity",
            "expert_signoff",
        ),
    ),
}


class KbPublishBlocked(Exception):
    """kb_validate found errors; nothing was published."""

    def __init__(self, report: dict[str, Any]) -> None:
        super().__init__(f"kb publication blocked: {len(report['errors'])} error(s)")
        self.report = report


def _artifact_content(kind: str, row: Any) -> dict[str, Any]:
    _, revision_column, object_column, columns = ARTIFACTS[kind]
    return {
        "object_id": getattr(row, object_column),
        "revision_id": getattr(row, revision_column),
        **{column: getattr(row, column) for column in columns},
    }


@dataclass
class Composition:
    """Exact content of a (candidate) release: claim revisions and artifact revisions."""

    base_release_id: str | None
    claims: dict[str, str] = field(default_factory=dict)  # claim_id → revision_id
    artifacts: dict[tuple[str, str], str] = field(default_factory=dict)  # (kind, id) → rev


# ------------------------------------------------------------------------ loading helpers


def _release_row(session: Session, release_id: str) -> KbReleaseRow | None:
    return session.get(KbReleaseRow, release_id)


def _composition_of(session: Session, release_id: str | None) -> Composition:
    composition = Composition(base_release_id=release_id)
    if release_id is None:
        return composition
    for row in session.scalars(
        select(KbReleaseClaimRow).where(KbReleaseClaimRow.release_id == release_id)
    ):
        composition.claims[row.claim_id] = row.revision_id
    for row in session.scalars(
        select(KbReleaseArtifactRow).where(KbReleaseArtifactRow.release_id == release_id)
    ):
        composition.artifacts[(row.object_kind, row.object_id)] = row.object_revision_id
    return composition


def active_release_id(session: Session) -> str | None:
    row = session.get(KbActiveReleaseRow, ACTIVE_SLOT)
    return None if row is None else row.release_id


def _claim_payload(session: Session, revision_id: str) -> dict[str, Any]:
    revision = session.get(KbClaimRevisionRow, revision_id)
    claim = session.get(KbClaimRow, revision.claim_id)
    evidence = session.scalars(
        select(KbClaimEvidenceRow)
        .where(KbClaimEvidenceRow.revision_id == revision_id)
        .order_by(KbClaimEvidenceRow.ev_revision_id, KbClaimEvidenceRow.role)
    ).all()
    return {
        "claim_id": claim.claim_id,
        "entity_id": claim.entity_id,
        "attribute_id": claim.attribute_id,
        "scope_key": claim.scope_key,
        "revision_id": revision.revision_id,
        "value": revision.value,
        "value_kind": revision.value_kind,
        "unit": revision.unit,
        "scope": revision.scope,
        "status": revision.status,
        "permission_code": revision.permission_code,
        "qualification": revision.qualification,
        "evidence": [
            {
                "ev_revision_id": link.ev_revision_id,
                "role": link.role,
                "check_id": link.check_id,
                "source_value": link.source_value,
                "verified_scope": link.verified_scope,
            }
            for link in evidence
        ],
    }


def _artifact_payload(session: Session, kind: str, revision_id: str) -> dict[str, Any]:
    row_class = ARTIFACTS[kind][0]
    return _artifact_content(kind, session.get(row_class, revision_id))


def composition_checksum(session: Session, composition: Composition) -> tuple[str, dict]:
    """Deterministic checksum over the exact content (no timestamps, no actor names)."""
    claims = [
        _claim_payload(session, composition.claims[claim_id])
        for claim_id in sorted(composition.claims)
    ]
    artifacts = []
    for kind, object_id in sorted(composition.artifacts):
        payload = _artifact_payload(session, kind, composition.artifacts[(kind, object_id)])
        artifacts.append(
            {
                "kind": kind,
                "object_id": object_id,
                "revision_id": payload["revision_id"],
                "content_hash": sha256_hex(payload),
            }
        )
    body = {"contract_version": KB_CONTRACT_VERSION, "claims": claims, "artifacts": artifacts}
    return sha256_hex(body), body


# -------------------------------------------------------------------------------- admin


class KbAdmin:
    """Administrator operations. All writes happen in the caller's transaction."""

    def __init__(self, session: Session, actor: str) -> None:
        if not actor:
            raise ValueError("actor is required")
        self.session = session
        self.actor = actor

    # ---- drafts

    def _log(self, kind: str, object_id: str, action: str, reason: str, release_id=None):
        self.session.add(
            KbChangeLogRow(
                object_kind=kind,
                object_id=object_id,
                action=action,
                reason=reason,
                actor=self.actor,
                release_id=release_id,
            )
        )

    def ensure_entity(self, entity_id: str, entity_type: str, **labels: Any) -> None:
        if self.session.get(KbEntityRow, entity_id) is None:
            self.session.add(KbEntityRow(entity_id=entity_id, entity_type=entity_type, **labels))
            self.session.flush()

    def ensure_attribute(
        self,
        attribute_id: str,
        value_type: str,
        validation_profile_id: str,
        unit: str | None = None,
        scale: str | None = None,
    ) -> None:
        if self.session.get(KbAttributeRow, attribute_id) is None:
            self.session.add(
                KbAttributeRow(
                    attribute_id=attribute_id,
                    value_type=value_type,
                    unit=unit,
                    scale=scale,
                    validation_profile_id=validation_profile_id,
                )
            )
            self.session.flush()

    def draft_artifact(
        self, object_kind: str, revision_id: str, reason: str, **content: Any
    ) -> None:
        kind = object_kind
        row_class, revision_column, object_column, columns = ARTIFACTS[kind]
        unexpected = set(content) - {object_column, *columns}
        if unexpected:
            raise ValueError(f"unexpected {kind} fields: {sorted(unexpected)}")
        if kind == "term":
            content["normalized_form"] = normalize_term(content["text"])
        row = row_class(
            **{revision_column: revision_id},
            **content,
            rev_state="draft",
            reason=reason,
            created_by=self.actor,
        )
        self.session.add(row)
        self.session.flush()
        self._log(kind, content[object_column], "draft", reason)

    def draft_claim(
        self,
        *,
        entity_id: str,
        attribute_id: str,
        scope: dict[str, Any] | None,
        revision_id: str,
        value: dict[str, Any],
        value_kind: str,
        status: str,
        permission_code: str,
        qualification: dict[str, Any],
        reason: str,
        evidence: Iterable[dict[str, Any]] = (),
        unit: str | None = None,
    ) -> str:
        attribute = self.session.get(KbAttributeRow, attribute_id)
        if attribute is None or self.session.get(KbEntityRow, entity_id) is None:
            raise KnowledgeKbError("unknown_entity", f"{entity_id}/{attribute_id}")
        normalized_scope, scope_key = normalize_scope(scope)
        claim = self.session.scalar(
            select(KbClaimRow).where(
                KbClaimRow.entity_id == entity_id,
                KbClaimRow.attribute_id == attribute_id,
                KbClaimRow.scope_key == scope_key,
            )
        )
        if claim is None:
            claim = KbClaimRow(
                claim_id=f"clm:{entity_id}:{attribute_id}:{sha256_hex(scope_key)[:12]}",
                entity_id=entity_id,
                attribute_id=attribute_id,
                scope_key=scope_key,
            )
            self.session.add(claim)
            self.session.flush()
        self.session.add(
            KbClaimRevisionRow(
                revision_id=revision_id,
                claim_id=claim.claim_id,
                value=normalize_value(value, attribute.value_type),
                value_kind=value_kind,
                unit=unit if unit is not None else attribute.unit,
                scope=normalized_scope,
                status=status,
                permission_code=permission_code,
                qualification=qualification,
                rev_state="draft",
                reason=reason,
                created_by=self.actor,
            )
        )
        self.session.flush()
        for link in evidence:
            self.session.add(
                KbClaimEvidenceRow(
                    revision_id=revision_id,
                    ev_revision_id=link["ev_revision_id"],
                    role=link.get("role", "supports"),
                    check_id=link.get("check_id"),
                    source_value=link.get("source_value"),
                    verified_scope=link.get("verified_scope", normalized_scope),
                )
            )
        self.session.flush()
        self._log("claim", claim.claim_id, "draft", reason)
        return claim.claim_id

    def map_legacy(self, legacy_k_id, target_kind, target_id, mapping_type, explanation):
        from .kb_models import KbLegacyMapRow

        self.session.add(
            KbLegacyMapRow(
                legacy_k_id=legacy_k_id,
                target_kind=target_kind,
                target_id=target_id,
                mapping_type=mapping_type,
                explanation=explanation,
                source_version="v1.6.2",
            )
        )

    def register_caller(self, caller_id: str, description: str, purposes: list[str]) -> None:
        unknown = sorted(set(purposes) - set(PURPOSES))
        if unknown:
            raise ValueError(f"unknown purposes: {unknown}")
        row = self.session.get(KbCallerRow, caller_id)
        if row is None:
            self.session.add(
                KbCallerRow(caller_id=caller_id, description=description, purposes=purposes)
            )
        else:
            row.description, row.purposes = description, purposes
        self.session.flush()

    # ---- composition

    def _drafts(self) -> tuple[list[KbClaimRevisionRow], dict[str, list]]:
        claims = self.session.scalars(
            select(KbClaimRevisionRow)
            .where(KbClaimRevisionRow.rev_state == "draft")
            .order_by(KbClaimRevisionRow.revision_id)
        ).all()
        artifacts = {}
        for kind, (row_class, revision_column, _, _) in ARTIFACTS.items():
            artifacts[kind] = self.session.scalars(
                select(row_class)
                .where(row_class.rev_state == "draft")
                .order_by(getattr(row_class, revision_column))
            ).all()
        return claims, artifacts

    def candidate(self, base_release_id: str | None = None) -> tuple[Composition, list[str]]:
        """Base release membership overlaid with all drafts. Returns (composition, errors)."""
        composition = _composition_of(self.session, base_release_id)
        composition.base_release_id = base_release_id
        errors: list[str] = []
        claims, artifacts = self._drafts()
        seen: set[str] = set()
        for revision in claims:
            if revision.claim_id in seen:
                errors.append(f"structure: two drafts for claim {revision.claim_id}")
            seen.add(revision.claim_id)
            composition.claims[revision.claim_id] = revision.revision_id
        for kind, rows in artifacts.items():
            _, revision_column, object_column, _ = ARTIFACTS[kind]
            seen_objects: set[str] = set()
            for row in rows:
                object_id = getattr(row, object_column)
                if object_id in seen_objects:
                    errors.append(f"structure: two drafts for {kind} {object_id}")
                seen_objects.add(object_id)
                composition.artifacts[(kind, object_id)] = getattr(row, revision_column)
        return composition, errors

    # ---- kb_validate

    def validate(self, composition: Composition, extra_errors=()) -> dict[str, Any]:
        session = self.session
        errors, warnings = list(extra_errors), []
        policies = {
            object_id: session.get(KbPolicyRevisionRow, revision_id)
            for (kind, object_id), revision_id in composition.artifacts.items()
            if kind == "policy"
        }
        profiles = {
            object_id: session.get(KbValidationProfileRevisionRow, revision_id)
            for (kind, object_id), revision_id in composition.artifacts.items()
            if kind == "validation_profile"
        }
        evidence_in_release = {
            revision_id
            for (kind, _), revision_id in composition.artifacts.items()
            if kind == "evidence"
        }
        for policy in policies.values():
            if "validate_block" in policy.uses:
                errors.append(
                    f"policy: {policy.permission_code} grants validate_block, disabled (v1.2 §5)"
                )
            if policy.allowed_status not in STATUSES:
                errors.append(f"policy: {policy.permission_code} has unknown status")
            if set(policy.uses) - set(USES):
                errors.append(f"policy: {policy.permission_code} has unknown uses")
        today = date.today().isoformat()
        status_counts: dict[str, int] = {}
        for claim_id, revision_id in sorted(composition.claims.items()):
            payload = _claim_payload(session, revision_id)
            attribute = session.get(KbAttributeRow, payload["attribute_id"])
            label = f"{claim_id} ({revision_id})"
            status = payload["status"]
            status_counts[status] = status_counts.get(status, 0) + 1
            try:
                if normalize_value(payload["value"], attribute.value_type) != payload["value"]:
                    errors.append(f"structure: {label} value is not canonical")
            except ValueError as error:
                errors.append(f"structure: {label} {error}")
            if attribute.unit is not None and payload["unit"] != attribute.unit:
                errors.append(f"structure: {label} unit {payload['unit']} ≠ {attribute.unit}")
            policy = policies.get(payload["permission_code"])
            if policy is None:
                errors.append(f"policy: {label} permission {payload['permission_code']} missing")
            elif policy.allowed_status != status:
                errors.append(
                    f"policy: {label} {payload['permission_code']} is not allowed for {status}"
                )
            supports = [link for link in payload["evidence"] if link["role"] == "supports"]
            contradicts = [link for link in payload["evidence"] if link["role"] == "contradicts"]
            for link in payload["evidence"]:
                if link["ev_revision_id"] not in evidence_in_release:
                    errors.append(f"policy: {label} evidence {link['ev_revision_id']} not pinned")
            if payload["permission_code"] == "LEGAL_INFORMATION_ONLY":
                missing = [key for key in NORMATIVE_SCOPE_KEYS if key not in payload["scope"]]
                if missing:
                    errors.append(f"policy: {label} normative scope lacks {missing}")
                effective_to = payload["scope"].get("effective_to")
                if effective_to and effective_to < today:
                    errors.append(f"policy: {label} norm expired on {effective_to}")
            if status != "VERIFIED":
                continue
            if not supports:
                errors.append(f"policy: {label} VERIFIED without supporting evidence")
            if contradicts:
                errors.append(f"evidence: {label} VERIFIED with contradicting evidence")
            profile = profiles.get(attribute.validation_profile_id)
            qualification = payload["qualification"] or {}
            if profile is None:
                errors.append(f"content: {label} profile {attribute.validation_profile_id} missing")
                continue
            if qualification.get("profile_revision_id") != profile.profile_revision_id:
                errors.append(f"content: {label} qualified under another profile revision")
            outcomes = [
                evaluate_profile(
                    profile.method,
                    profile.params,
                    payload["value"],
                    payload["value_kind"],
                    link["source_value"],
                    payload["scope"],
                )[0]
                for link in supports
            ] or ["no_source"]
            if "source_match" not in outcomes or qualification.get("outcome") != "source_match":
                errors.append(f"content: {label} VERIFIED without full source match ({outcomes})")
        # Terms and relations.
        terms = {
            object_id: session.get(KbTermRevisionRow, revision_id)
            for (kind, object_id), revision_id in composition.artifacts.items()
            if kind == "term"
        }
        pairs: dict[frozenset, set[str]] = {}
        for (kind, object_id), revision_id in composition.artifacts.items():
            if kind != "term_relation":
                continue
            relation = session.get(KbTermRelationRevisionRow, revision_id)
            for term_id in (relation.term_a, relation.term_b):
                if term_id not in terms:
                    errors.append(f"structure: relation {object_id} uses unknown term {term_id}")
            pairs.setdefault(frozenset((relation.term_a, relation.term_b)), set()).add(
                relation.relation
            )
        for pair, relations in pairs.items():
            if {"synonym", "false_equivalent"} <= relations:
                errors.append(f"consistency: {sorted(pair)} is both synonym and false_equivalent")
        for (kind, object_id), revision_id in composition.artifacts.items():
            if kind == "rule":
                rule = session.get(KbRuleRevisionRow, revision_id)
                if rule.severity == "block" and not rule.expert_signoff:
                    warnings.append(f"rule: {object_id} severity=block without expert sign-off")
        return {
            "errors": sorted(errors),
            "warnings": sorted(warnings),
            "counts": {
                "claims": len(composition.claims),
                "artifacts": len(composition.artifacts),
                "status": dict(sorted(status_counts.items())),
            },
        }

    # ---- kb_diff

    def diff(self, base_release_id: str | None, composition: Composition) -> dict[str, Any]:
        base = _composition_of(self.session, base_release_id)
        added = sorted(set(composition.claims) - set(base.claims))
        changed, status_changes = [], []
        for claim_id in sorted(set(composition.claims) & set(base.claims)):
            old, new = base.claims[claim_id], composition.claims[claim_id]
            if old == new:
                continue
            changed.append(claim_id)
            before = self.session.get(KbClaimRevisionRow, old)
            after = self.session.get(KbClaimRevisionRow, new)
            if (before.status, before.permission_code) != (after.status, after.permission_code):
                status_changes.append(
                    {
                        "claim_id": claim_id,
                        "from": [before.status, before.permission_code],
                        "to": [after.status, after.permission_code],
                    }
                )
        artifacts_changed = sorted(
            f"{kind}:{object_id}"
            for (kind, object_id), revision_id in composition.artifacts.items()
            if base.artifacts.get((kind, object_id)) != revision_id
        )
        return {
            "base_release_id": base_release_id,
            "claims_added": added,
            "claims_changed": changed,
            "status_or_permission_changes": status_changes,
            "artifacts_added_or_changed": artifacts_changed,
        }

    # ---- kb_publish

    def publish(
        self, release_id: str, changelog: str, base_release_id: str | None = "active"
    ) -> KbReleaseRow:
        if base_release_id == "active":
            base_release_id = active_release_id(self.session)
        existing = _release_row(self.session, release_id)
        drafts, artifact_drafts = self._drafts()
        if existing is not None:
            if drafts or any(artifact_drafts.values()):
                raise KnowledgeKbError(
                    "payload_conflict", f"{release_id} exists; pending drafts differ"
                )
            return existing  # idempotent replay of the same publication
        composition, structural = self.candidate(base_release_id)
        report = self.validate(composition, structural)
        if report["errors"]:
            raise KbPublishBlocked(report)
        diff = self.diff(base_release_id, composition)
        return self._write_release(release_id, changelog, composition, report, diff, "publish")

    def _write_release(self, release_id, changelog, composition, report, diff, kind):
        session = self.session
        drafts, artifact_drafts = self._drafts()
        included_claims = set(composition.claims.values())
        for revision in drafts:
            if revision.revision_id in included_claims:
                revision.rev_state = "published"
        for rows in artifact_drafts.values():
            for row in rows:
                row.rev_state = "published"
        session.flush()
        checksum, body = composition_checksum(session, composition)
        status_counts = report["counts"]["status"]
        manifest = {
            "contract_version": KB_CONTRACT_VERSION,
            "release_id": release_id,
            "base_release_id": composition.base_release_id,
            "claims": len(composition.claims),
            "artifacts": {
                kind: sum(1 for (k, _) in composition.artifacts if k == kind) for kind in ARTIFACTS
            },
            "status": status_counts,
            "checksum": checksum,
        }
        session.add(
            KbReleaseRow(
                release_id=release_id,
                base_release_id=composition.base_release_id,
                kind=kind,
                published_by=self.actor,
                changelog=changelog,
                manifest=manifest,
                checksum=checksum,
                validation_report=report,
                diff_report=diff,
            )
        )
        session.flush()
        for claim_id, revision_id in sorted(composition.claims.items()):
            session.add(
                KbReleaseClaimRow(release_id=release_id, claim_id=claim_id, revision_id=revision_id)
            )
        for item in body["artifacts"]:
            session.add(
                KbReleaseArtifactRow(
                    release_id=release_id,
                    object_kind=item["kind"],
                    object_id=item["object_id"],
                    object_revision_id=item["revision_id"],
                    content_hash=item["content_hash"],
                )
            )
        session.flush()
        self._log("release", release_id, kind, changelog, release_id)
        return session.get(KbReleaseRow, release_id)

    # ---- activation, rollback, retention

    def activate(self, release_id: str, reason: str) -> None:
        if _release_row(self.session, release_id) is None:
            raise KnowledgeKbError("release_not_found", release_id)
        if self.session.get(KbReleaseRetirementRow, release_id) is not None:
            raise KnowledgeKbError("release_unavailable", release_id)
        row = self.session.get(KbActiveReleaseRow, ACTIVE_SLOT)
        if row is None:
            self.session.add(
                KbActiveReleaseRow(
                    slot=ACTIVE_SLOT, release_id=release_id, changed_by=self.actor, reason=reason
                )
            )
        else:
            self.session.execute(
                update(KbActiveReleaseRow)
                .where(KbActiveReleaseRow.slot == ACTIVE_SLOT)
                .values(release_id=release_id, changed_by=self.actor, reason=reason)
                .execution_options(synchronize_session="fetch")
            )
        self.session.flush()
        self._log("active_release", ACTIVE_SLOT, "activate", reason, release_id)

    def revert(self, to_release_id: str, new_release_id: str, reason: str) -> KbReleaseRow:
        """New immutable release with exactly the membership of an earlier release."""
        if _release_row(self.session, to_release_id) is None:
            raise KnowledgeKbError("release_not_found", to_release_id)
        if _release_row(self.session, new_release_id) is not None:
            raise KnowledgeKbError("payload_conflict", f"{new_release_id} already exists")
        drafts, artifact_drafts = self._drafts()
        if drafts or any(artifact_drafts.values()):
            raise KnowledgeKbError("payload_conflict", "pending drafts would be mixed into revert")
        composition = _composition_of(self.session, to_release_id)
        composition.base_release_id = to_release_id
        report = self.validate(composition)
        diff = self.diff(active_release_id(self.session), composition)
        return self._write_release(new_release_id, reason, composition, report, diff, "revert")

    def retire(self, release_id: str, reason: str) -> None:
        if active_release_id(self.session) == release_id:
            raise KnowledgeKbError("payload_conflict", "the active release cannot be retired")
        self.session.add(
            KbReleaseRetirementRow(release_id=release_id, retired_by=self.actor, reason=reason)
        )
        self.session.flush()

    # ---- portable package (ADR 0048 decision 8)

    def export_release(self, release_id: str) -> dict[str, Any]:
        release = _release_row(self.session, release_id)
        if release is None:
            raise KnowledgeKbError("release_not_found", release_id)
        composition = _composition_of(self.session, release_id)
        checksum, body = composition_checksum(self.session, composition)
        if checksum != release.checksum:
            raise KnowledgeKbError("payload_conflict", f"{release_id} checksum mismatch")
        entities, attributes = set(), set()
        for claim in body["claims"]:
            entities.add(claim["entity_id"])
            attributes.add(claim["attribute_id"])
        artifacts = []
        for item in body["artifacts"]:
            payload = _artifact_payload(self.session, item["kind"], item["revision_id"])
            artifacts.append({"kind": item["kind"], "payload": payload})
            if item["kind"] == "term":
                entities.add(payload["entity_id"])
        closure = set()
        for entity_id in sorted(entities):
            while entity_id and entity_id not in closure:
                closure.add(entity_id)
                entity_id = self.session.get(KbEntityRow, entity_id).parent_id
        return {
            "package": "jewelai.knowledge_library.kb.release",
            "contract_version": KB_CONTRACT_VERSION,
            "release_id": release_id,
            "changelog": release.changelog,
            "manifest": release.manifest,
            "checksum": checksum,
            "entities": [
                {
                    column: getattr(self.session.get(KbEntityRow, entity_id), column)
                    for column in (
                        "entity_id",
                        "entity_type",
                        "parent_id",
                        "label_ru",
                        "label_en",
                        "dictionary_domain_id",
                    )
                }
                for entity_id in sorted(closure, key=lambda e: (e.count("."), e))
            ],
            "attributes": [
                {
                    column: getattr(self.session.get(KbAttributeRow, attribute_id), column)
                    for column in (
                        "attribute_id",
                        "value_type",
                        "unit",
                        "scale",
                        "validation_profile_id",
                    )
                }
                for attribute_id in sorted(attributes)
            ],
            "artifacts": artifacts,
            "claims": body["claims"],
        }

    def import_release(self, package: dict[str, Any]) -> KbReleaseRow:
        """Load a portable package into an independent deployment with an identical checksum."""
        release_id = package["release_id"]
        existing = _release_row(self.session, release_id)
        if existing is not None:
            if existing.checksum == package["checksum"]:
                return existing
            raise KnowledgeKbError("payload_conflict", f"{release_id} has a different checksum")
        drafts, artifact_drafts = self._drafts()
        if drafts or any(artifact_drafts.values()):
            raise KnowledgeKbError("payload_conflict", "target has pending drafts")
        for entity in package["entities"]:
            if self.session.get(KbEntityRow, entity["entity_id"]) is None:
                self.session.add(KbEntityRow(**entity))
                self.session.flush()
        for attribute in package["attributes"]:
            if self.session.get(KbAttributeRow, attribute["attribute_id"]) is None:
                self.session.add(KbAttributeRow(**attribute))
        self.session.flush()
        composition = Composition(base_release_id=None)
        for item in package["artifacts"]:
            kind, payload = item["kind"], dict(item["payload"])
            row_class, revision_column, object_column, _ = ARTIFACTS[kind]
            revision_id = payload.pop("revision_id")
            object_id = payload.pop("object_id")
            composition.artifacts[(kind, object_id)] = revision_id
            if self.session.get(row_class, revision_id) is None:
                row = row_class(
                    **{revision_column: revision_id, object_column: object_id},
                    **payload,
                    rev_state="draft",
                    reason=f"imported from {release_id}",
                    created_by=self.actor,
                )
                self.session.add(row)
        self.session.flush()
        for claim in package["claims"]:
            composition.claims[claim["claim_id"]] = claim["revision_id"]
            if self.session.get(KbClaimRow, claim["claim_id"]) is None:
                self.session.add(
                    KbClaimRow(
                        claim_id=claim["claim_id"],
                        entity_id=claim["entity_id"],
                        attribute_id=claim["attribute_id"],
                        scope_key=claim["scope_key"],
                    )
                )
                self.session.flush()
            if self.session.get(KbClaimRevisionRow, claim["revision_id"]) is None:
                self.session.add(
                    KbClaimRevisionRow(
                        revision_id=claim["revision_id"],
                        claim_id=claim["claim_id"],
                        value=claim["value"],
                        value_kind=claim["value_kind"],
                        unit=claim["unit"],
                        scope=claim["scope"],
                        status=claim["status"],
                        permission_code=claim["permission_code"],
                        qualification=claim["qualification"],
                        rev_state="draft",
                        reason=f"imported from {release_id}",
                        created_by=self.actor,
                    )
                )
                self.session.flush()
                for link in claim["evidence"]:
                    self.session.add(KbClaimEvidenceRow(revision_id=claim["revision_id"], **link))
        self.session.flush()
        checksum, _ = composition_checksum(self.session, composition)
        if checksum != package["checksum"]:
            raise KnowledgeKbError("payload_conflict", "package content does not match checksum")
        report = self.validate(composition)
        if report["errors"]:
            raise KbPublishBlocked(report)
        diff = self.diff(None, composition)
        release = self._write_release(
            release_id, package["changelog"], composition, report, diff, "import"
        )
        if release.checksum != package["checksum"]:
            raise KnowledgeKbError("payload_conflict", "imported checksum differs")
        return release


# ------------------------------------------------------------------------- Knowledge API


@dataclass(frozen=True)
class ClaimView:
    claim_id: str
    revision_id: str
    entity_id: str
    attribute: str
    value: dict[str, str]
    value_kind: str
    unit: str | None
    scope: dict[str, str]
    status: str
    permission_code: str
    policy_revision_id: str
    allowed_uses: tuple[str, ...]
    evidence_revision_ids: tuple[str, ...]
    release_id: str
    qualification_method: str | None
    caveat: str | None
    approximate: bool
    legacy_k_ids: tuple[str, ...]


@dataclass(frozen=True)
class Denial:
    claim_id: str
    reason: str


@dataclass(frozen=True)
class ClaimsResult:
    release_id: str
    purpose: str
    claims: tuple[ClaimView, ...]
    denials: tuple[Denial, ...]


@dataclass(frozen=True)
class TermCandidate:
    entity_id: str
    term_id: str
    term_revision_id: str
    text: str
    lang: str


@dataclass(frozen=True)
class ResolveResult:
    release_id: str
    candidates: tuple[TermCandidate, ...]
    ambiguous: bool
    false_equivalent_warnings: tuple[str, ...]


@dataclass(frozen=True)
class EvaluationResult:
    release_id: str
    result: str
    claim_id: str | None
    revision_id: str | None
    status: str | None
    stored_value: dict[str, str] | None
    scope: dict[str, str] | None
    evidence_revision_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class RuleView:
    rule_id: str
    rule_revision_id: str
    severity: str
    reason: str
    enforced: bool


CAVEAT = "Справочно: проверка неполная / Reference only: verification incomplete"


class KnowledgeApi:
    """Read-only Knowledge API (v1.2 §8). Never writes; every call is READ ONLY."""

    def __init__(self, session_factory: sessionmaker[Session], caller_id: str) -> None:
        self.session_factory = session_factory
        self.caller_id = caller_id

    # ---- plumbing

    def _read(self, function, *args, **kwargs):
        with self.session_factory() as session:
            with session.begin():
                if session.bind.dialect.name == "postgresql":
                    session.execute(text("SET TRANSACTION READ ONLY"))
                return function(session, *args, **kwargs)

    def _authorize(self, session: Session, purpose: str) -> None:
        if purpose not in PURPOSES:
            raise KnowledgeKbError("purpose_not_allowed", f"unknown purpose {purpose}")
        caller = session.get(KbCallerRow, self.caller_id)
        if caller is None or purpose not in caller.purposes:
            raise KnowledgeKbError("purpose_not_allowed", f"{self.caller_id} may not {purpose}")
        if purpose == "validate_block":
            raise KnowledgeKbError("purpose_not_allowed", "validate_block is disabled (pilot)")

    def _release(self, session: Session, release_id: str) -> KbReleaseRow:
        if not release_id or release_id == "active":
            raise KnowledgeKbError("release_not_found", "a pinned release_id is required")
        release = _release_row(session, release_id)
        if release is None:
            raise KnowledgeKbError("release_not_found", release_id)
        if session.get(KbReleaseRetirementRow, release_id) is not None:
            raise KnowledgeKbError("release_unavailable", release_id)
        return release

    @staticmethod
    def _policies(session: Session, release_id: str) -> dict[str, KbPolicyRevisionRow]:
        rows = session.scalars(
            select(KbReleaseArtifactRow).where(
                KbReleaseArtifactRow.release_id == release_id,
                KbReleaseArtifactRow.object_kind == "policy",
            )
        )
        return {
            row.object_id: session.get(KbPolicyRevisionRow, row.object_revision_id) for row in rows
        }

    @staticmethod
    def _legacy(session: Session, claim_id: str) -> tuple[str, ...]:
        from .kb_models import KbLegacyMapRow

        return tuple(
            sorted(
                session.scalars(
                    select(KbLegacyMapRow.legacy_k_id).where(
                        KbLegacyMapRow.target_kind == "claim", KbLegacyMapRow.target_id == claim_id
                    )
                )
            )
        )

    def _view(self, session, release_id, payload, policy, uses) -> ClaimView:
        return ClaimView(
            claim_id=payload["claim_id"],
            revision_id=payload["revision_id"],
            entity_id=payload["entity_id"],
            attribute=payload["attribute_id"],
            value=payload["value"],
            value_kind=payload["value_kind"],
            unit=payload["unit"],
            scope=payload["scope"],
            status=payload["status"],
            permission_code=payload["permission_code"],
            policy_revision_id=policy.policy_revision_id,
            allowed_uses=tuple(uses),
            evidence_revision_ids=tuple(
                link["ev_revision_id"] for link in payload["evidence"] if link["role"] == "supports"
            ),
            release_id=release_id,
            qualification_method=(payload["qualification"] or {}).get("method"),
            caveat=CAVEAT if payload["status"] == "REFERENCE ONLY" else None,
            approximate=payload["value_kind"] in ("approximate", "derived"),
            legacy_k_ids=self._legacy(session, payload["claim_id"]),
        )

    # ---- operations

    def get_release(self, release_id: str, purpose: str = "release_metadata") -> dict[str, Any]:
        def run(session: Session) -> dict[str, Any]:
            self._authorize(session, purpose)
            if purpose != "release_metadata":
                raise KnowledgeKbError("purpose_not_allowed", "get_release is release_metadata")
            target = active_release_id(session) if release_id == "active" else release_id
            if target is None:
                raise KnowledgeKbError("release_not_found", "no active release")
            release = self._release(session, target)
            policies = self._policies(session, target)
            profiles = session.scalars(
                select(KbReleaseArtifactRow).where(
                    KbReleaseArtifactRow.release_id == target,
                    KbReleaseArtifactRow.object_kind == "validation_profile",
                )
            ).all()
            return {
                "release_id": release.release_id,
                "contract_version": release.manifest["contract_version"],
                "published_at": release.published_at.isoformat(),
                "manifest": release.manifest,
                "checksum": release.checksum,
                "policy_revision_ids": sorted(p.policy_revision_id for p in policies.values()),
                "validation_profile_revision_ids": sorted(p.object_revision_id for p in profiles),
                "supported_uses": sorted({use for p in policies.values() for use in p.uses}),
                "available": True,
            }

        return self._read(run)

    def resolve_terms(
        self, text_value: str, release_id: str, lang: str | None = None, purpose: str = "resolve"
    ) -> ResolveResult:
        def run(session: Session) -> ResolveResult:
            self._authorize(session, purpose)
            if purpose != "resolve":
                raise KnowledgeKbError("purpose_not_allowed", "resolve_terms is purpose=resolve")
            self._release(session, release_id)
            normalized = normalize_term(text_value)
            artifacts = session.scalars(
                select(KbReleaseArtifactRow).where(
                    KbReleaseArtifactRow.release_id == release_id,
                    KbReleaseArtifactRow.object_kind.in_(("term", "term_relation")),
                )
            ).all()
            terms = {
                row.object_id: session.get(KbTermRevisionRow, row.object_revision_id)
                for row in artifacts
                if row.object_kind == "term"
            }
            matches = [
                term
                for term in terms.values()
                if term.normalized_form == normalized and (lang is None or term.lang == lang)
            ]
            if not matches:
                raise KnowledgeKbError("unknown_entity", text_value)
            matched_ids = {term.term_id for term in matches}
            warnings, ambiguous_relation = [], False
            for row in artifacts:
                if row.object_kind != "term_relation":
                    continue
                relation = session.get(KbTermRelationRevisionRow, row.object_revision_id)
                pair = {relation.term_a, relation.term_b}
                if not pair & matched_ids:
                    continue
                if relation.relation == "false_equivalent":
                    other = (pair - matched_ids) or pair
                    for term_id in sorted(other):
                        if term_id in terms:
                            warnings.append(
                                f"{text_value} ≠ {terms[term_id].text}"
                                + (f": {relation.note}" if relation.note else "")
                            )
                if relation.relation == "ambiguous":
                    ambiguous_relation = True
            candidates = tuple(
                TermCandidate(t.entity_id, t.term_id, t.term_revision_id, t.text, t.lang)
                for t in sorted(matches, key=lambda t: (t.entity_id, t.term_id))
            )
            entities = {candidate.entity_id for candidate in candidates}
            return ResolveResult(
                release_id=release_id,
                candidates=candidates,
                ambiguous=len(entities) > 1 or ambiguous_relation,
                false_equivalent_warnings=tuple(sorted(set(warnings))),
            )

        return self._read(run)

    def get_claims(
        self,
        entity_id: str,
        purpose: str,
        release_id: str,
        attributes: Iterable[str] | None = None,
        scope: dict[str, Any] | None = None,
    ) -> ClaimsResult:
        wanted = None if attributes is None else set(attributes)

        def run(session: Session) -> ClaimsResult:
            self._authorize(session, purpose)
            if purpose in READ_PURPOSES or purpose in ("validate_warn", "validate_block"):
                raise KnowledgeKbError("purpose_not_allowed", f"get_claims cannot serve {purpose}")
            self._release(session, release_id)
            if session.get(KbEntityRow, entity_id) is None:
                raise KnowledgeKbError("unknown_entity", entity_id)
            requested, _ = normalize_scope(scope)
            policies = self._policies(session, release_id)
            members = session.execute(
                select(KbReleaseClaimRow.claim_id, KbReleaseClaimRow.revision_id)
                .join(KbClaimRow, KbClaimRow.claim_id == KbReleaseClaimRow.claim_id)
                .where(
                    KbReleaseClaimRow.release_id == release_id, KbClaimRow.entity_id == entity_id
                )
                .order_by(KbReleaseClaimRow.claim_id)
            ).all()
            views, denials = [], []
            for claim_id, revision_id in members:
                payload = _claim_payload(session, revision_id)
                if wanted is not None and payload["attribute_id"] not in wanted:
                    continue
                if any(payload["scope"].get(k) != v for k, v in requested.items()):
                    continue
                if payload["status"] == "REJECTED":
                    continue  # never shown, not even as a denial with a value
                policy = policies.get(payload["permission_code"])
                uses = () if policy is None else tuple(policy.uses)
                if policy is None or policy.allowed_status != payload["status"]:
                    uses = ()
                if purpose in uses:
                    views.append(self._view(session, release_id, payload, policy, uses))
                else:
                    denials.append(Denial(claim_id, "purpose_not_allowed"))
            if not views and not denials:
                raise KnowledgeKbError("no_data", f"{entity_id} {sorted(wanted or [])}")
            return ClaimsResult(release_id, purpose, tuple(views), tuple(denials))

        return self._read(run)

    def evaluate_claim(
        self,
        entity_id: str,
        attribute_id: str,
        value: dict[str, Any],
        release_id: str,
        scope: dict[str, Any] | None = None,
        value_kind: str = "exact",
        purpose: str = "verify_evidence",
    ) -> EvaluationResult:
        def run(session: Session) -> EvaluationResult:
            self._authorize(session, purpose)
            if purpose != "verify_evidence":
                raise KnowledgeKbError("purpose_not_allowed", "evaluate_claim is verify_evidence")
            self._release(session, release_id)
            attribute = session.get(KbAttributeRow, attribute_id)
            if session.get(KbEntityRow, entity_id) is None or attribute is None:
                raise KnowledgeKbError("unknown_entity", f"{entity_id}/{attribute_id}")
            normalized_scope, scope_key = normalize_scope(scope)
            claim = session.scalar(
                select(KbClaimRow).where(
                    KbClaimRow.entity_id == entity_id,
                    KbClaimRow.attribute_id == attribute_id,
                    KbClaimRow.scope_key == scope_key,
                )
            )
            member = (
                None
                if claim is None
                else session.get(KbReleaseClaimRow, (release_id, claim.claim_id))
            )
            if member is None:
                return EvaluationResult(
                    release_id, "unknown", None, None, None, None, normalized_scope, (), "no claim"
                )
            payload = _claim_payload(session, member.revision_id)
            evidence = tuple(link["ev_revision_id"] for link in payload["evidence"])
            base = (release_id,)
            tail = (payload["claim_id"], payload["revision_id"], payload["status"])
            if payload["status"] == "REJECTED":
                return EvaluationResult(
                    *base, "unknown", *tail, None, payload["scope"], (), "rejected claim"
                )
            if any(link["role"] == "contradicts" for link in payload["evidence"]):
                return EvaluationResult(
                    *base,
                    "review_required",
                    *tail,
                    payload["value"],
                    payload["scope"],
                    evidence,
                    "sources conflict; no winner is chosen",
                )
            profile_row = session.scalar(
                select(KbReleaseArtifactRow).where(
                    KbReleaseArtifactRow.release_id == release_id,
                    KbReleaseArtifactRow.object_kind == "validation_profile",
                    KbReleaseArtifactRow.object_id == attribute.validation_profile_id,
                )
            )
            profile = session.get(KbValidationProfileRevisionRow, profile_row.object_revision_id)
            candidate = normalize_value(value, attribute.value_type)
            method = profile.method
            if method in ("approximate_point", "manual_source_review"):
                method = "exact_number" if attribute.value_type == "number" else "source_range"
            if method == "formula":
                method = "enum_match" if attribute.value_type == "enum" else "exact_number"
            outcome, reason = evaluate_profile(
                method, profile.params, candidate, value_kind, payload["value"], payload["scope"]
            )
            if payload["status"] != "VERIFIED":
                result = "contradicted" if outcome == "mismatch" else "review_required"
                reason = f"reference only: {reason}"
            elif outcome == "source_match":
                result = "supported"
            elif outcome == "mismatch":
                result = "contradicted"
            else:
                result = "review_required"
            return EvaluationResult(
                *base, result, *tail, payload["value"], payload["scope"], evidence, reason
            )

        return self._read(run)

    def evaluate_rules(
        self,
        spec: dict[str, Any],
        release_id: str,
        purpose: str = "validate_warn",
        preview: bool = True,
    ) -> tuple[RuleView, ...]:
        def run(session: Session) -> tuple[RuleView, ...]:
            if purpose not in ("validate_warn", "validate_block"):
                raise KnowledgeKbError("purpose_not_allowed", "evaluate_rules needs validate_*")
            self._authorize(session, purpose)
            self._release(session, release_id)
            policies = self._policies(session, release_id)
            entities = set(spec.get("entities", ()))
            views = []
            for row in session.scalars(
                select(KbReleaseArtifactRow)
                .where(
                    KbReleaseArtifactRow.release_id == release_id,
                    KbReleaseArtifactRow.object_kind == "rule",
                )
                .order_by(KbReleaseArtifactRow.object_id)
            ):
                rule = session.get(KbRuleRevisionRow, row.object_revision_id)
                if rule.status == "REJECTED":
                    continue
                if not entities & set(rule.expression.get("entities_any", ())):
                    continue
                policy = policies.get(rule.permission_code)
                enforceable = (
                    not preview
                    and policy is not None
                    and purpose in policy.uses
                    and rule.status == "VERIFIED"
                )
                views.append(
                    RuleView(
                        rule.rule_id,
                        rule.rule_revision_id,
                        rule.severity,
                        rule.expression.get("reason", ""),
                        enforceable,
                    )
                )
            return tuple(views)

        return self._read(run)

    def search_knowledge(self, query: str, release_id: str, purpose: str = "search"):
        def run(session: Session):
            if purpose not in ("search", "explain"):
                raise KnowledgeKbError("purpose_not_allowed", "search_knowledge is search/explain")
            self._authorize(session, purpose)
            self._release(session, release_id)
            needle = normalize_term(query)
            results = []
            for claim_id, revision_id in session.execute(
                select(KbReleaseClaimRow.claim_id, KbReleaseClaimRow.revision_id)
                .where(KbReleaseClaimRow.release_id == release_id)
                .order_by(KbReleaseClaimRow.claim_id)
            ):
                payload = _claim_payload(session, revision_id)
                if payload["status"] == "REJECTED":
                    continue
                entity = session.get(KbEntityRow, payload["entity_id"])
                haystack = normalize_term(
                    " ".join(
                        filter(
                            None,
                            [
                                entity.label_ru,
                                entity.label_en,
                                payload["value"].get("text_ru"),
                                payload["value"].get("text_en"),
                            ],
                        )
                    )
                )
                if needle and needle in haystack:
                    results.append(
                        {
                            "claim_id": claim_id,
                            "revision_id": revision_id,
                            "status": payload["status"],
                            "caveat": CAVEAT if payload["status"] == "REFERENCE ONLY" else None,
                            "release_id": release_id,
                            "prompt_permission": False,  # search never grants prompt
                        }
                    )
            return tuple(results)

        return self._read(run)


__all__ = [
    "ACTIVE_SLOT",
    "CAVEAT",
    "ClaimView",
    "ClaimsResult",
    "Composition",
    "Denial",
    "EvaluationResult",
    "KbAdmin",
    "KbPublishBlocked",
    "KnowledgeApi",
    "ResolveResult",
    "RuleView",
    "TermCandidate",
    "active_release_id",
    "canonical_json",
    "composition_checksum",
]
