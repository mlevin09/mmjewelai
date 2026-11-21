"""Knowledge Library Contract 2.0 tables (ADR 0048).

Architecture v1.2 names the logical schema ``kb``. The tables live in the application schema
with a ``kb_`` prefix so that they follow the existing per-schema Alembic check and the
disposable-PostgreSQL test isolation (search_path per test). Immutability of published rows
is enforced by PostgreSQL triggers installed in migration 0024.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base

KbJson = JSON().with_variant(JSONB(), "postgresql")
_STATE = "rev_state IN ('draft','published')"


def _audit():
    return (
        mapped_column(String(32), nullable=False),  # rev_state
        mapped_column(Text, nullable=False),  # reason
        mapped_column(String(128), nullable=False),  # created_by
        mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )


class KbEntityRow(Base):
    __tablename__ = "kb_entity"
    entity_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    parent_id: Mapped[str | None] = mapped_column(
        String(160), ForeignKey("kb_entity.entity_id", ondelete="RESTRICT"), nullable=True
    )
    label_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    label_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    dictionary_domain_id: Mapped[str | None] = mapped_column(String(80), nullable=True)


class KbAttributeRow(Base):
    __tablename__ = "kb_attribute"
    __table_args__ = (
        CheckConstraint(
            "value_type IN ('number','range','enum','text')", name="ck_kb_attribute_type"
        ),
    )
    attribute_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    value_type: Mapped[str] = mapped_column(String(16))
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scale: Mapped[str | None] = mapped_column(String(64), nullable=True)
    validation_profile_id: Mapped[str] = mapped_column(String(80))


class KbValidationProfileRevisionRow(Base):
    __tablename__ = "kb_validation_profile_revision"
    __table_args__ = (CheckConstraint(_STATE, name="ck_kb_profile_state"),)
    profile_revision_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(80), index=True)
    method: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict] = mapped_column(KbJson)
    rev_state, reason, created_by, created_at = _audit()


class KbPolicyRevisionRow(Base):
    __tablename__ = "kb_policy_revision"
    __table_args__ = (CheckConstraint(_STATE, name="ck_kb_policy_state"),)
    policy_revision_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    permission_code: Mapped[str] = mapped_column(String(64), index=True)
    allowed_status: Mapped[str] = mapped_column(String(32))
    uses: Mapped[list] = mapped_column(KbJson)
    prompt_conditions: Mapped[str] = mapped_column(Text)
    forbidden: Mapped[str] = mapped_column(Text)
    conditions: Mapped[str] = mapped_column(Text)
    rev_state, reason, created_by, created_at = _audit()


class KbEvidenceRevisionRow(Base):
    __tablename__ = "kb_evidence_revision"
    __table_args__ = (
        CheckConstraint(_STATE, name="ck_kb_evidence_state"),
        CheckConstraint("tier IN ('Q1','Q2','Q3','Q4')", name="ck_kb_evidence_tier"),
    )
    ev_revision_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    ev_id: Mapped[str] = mapped_column(String(80), index=True)
    org: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    edition: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fragment: Mapped[str] = mapped_column(Text)
    tier: Mapped[str] = mapped_column(String(4))
    snapshot_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    limitations: Mapped[str | None] = mapped_column(Text, nullable=True)
    rev_state, reason, created_by, created_at = _audit()


class KbClaimRow(Base):
    __tablename__ = "kb_claim"
    __table_args__ = (
        UniqueConstraint("entity_id", "attribute_id", "scope_key", name="uq_kb_claim_identity"),
    )
    claim_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    entity_id: Mapped[str] = mapped_column(
        String(160), ForeignKey("kb_entity.entity_id", ondelete="RESTRICT")
    )
    attribute_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("kb_attribute.attribute_id", ondelete="RESTRICT")
    )
    scope_key: Mapped[str] = mapped_column(Text)


class KbClaimRevisionRow(Base):
    __tablename__ = "kb_claim_revision"
    __table_args__ = (
        CheckConstraint(_STATE, name="ck_kb_claim_revision_state"),
        CheckConstraint(
            "status IN ('VERIFIED','REFERENCE ONLY','REJECTED')", name="ck_kb_claim_status"
        ),
        CheckConstraint(
            "value_kind IN ('exact','source_range','approximate','derived','text')",
            name="ck_kb_claim_value_kind",
        ),
        UniqueConstraint("revision_id", "claim_id", name="uq_kb_claim_revision_claim"),
    )
    revision_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        String(200), ForeignKey("kb_claim.claim_id", ondelete="RESTRICT"), index=True
    )
    value: Mapped[dict] = mapped_column(KbJson)
    value_kind: Mapped[str] = mapped_column(String(16))
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scope: Mapped[dict] = mapped_column(KbJson)
    status: Mapped[str] = mapped_column(String(32))
    permission_code: Mapped[str] = mapped_column(String(64))
    qualification: Mapped[dict] = mapped_column(KbJson)
    rev_state, reason, created_by, created_at = _audit()


class KbClaimEvidenceRow(Base):
    __tablename__ = "kb_claim_evidence"
    __table_args__ = (
        CheckConstraint("role IN ('supports','contradicts')", name="ck_kb_claim_evidence_role"),
    )
    revision_id: Mapped[str] = mapped_column(
        String(200),
        ForeignKey("kb_claim_revision.revision_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    ev_revision_id: Mapped[str] = mapped_column(
        String(120),
        ForeignKey("kb_evidence_revision.ev_revision_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(16), primary_key=True)
    check_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_value: Mapped[dict | None] = mapped_column(KbJson, nullable=True)
    verified_scope: Mapped[dict] = mapped_column(KbJson)


class KbTermRevisionRow(Base):
    __tablename__ = "kb_term_revision"
    __table_args__ = (
        CheckConstraint(_STATE, name="ck_kb_term_state"),
        CheckConstraint("lang IN ('ru','en')", name="ck_kb_term_lang"),
        CheckConstraint(
            "kind IN ('name','synonym','jargon','translation')", name="ck_kb_term_kind"
        ),
        CheckConstraint(
            "review_status IN ('curated','source_match','unreviewed')", name="ck_kb_term_review"
        ),
    )
    term_revision_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    term_id: Mapped[str] = mapped_column(String(120), index=True)
    entity_id: Mapped[str] = mapped_column(
        String(160), ForeignKey("kb_entity.entity_id", ondelete="RESTRICT")
    )
    lang: Mapped[str] = mapped_column(String(2))
    text: Mapped[str] = mapped_column(Text)
    normalized_form: Mapped[str] = mapped_column(Text, index=True)
    kind: Mapped[str] = mapped_column(String(16))
    is_preferred: Mapped[bool] = mapped_column(Boolean)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(16))
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    rev_state, reason, created_by, created_at = _audit()


class KbTermRelationRevisionRow(Base):
    __tablename__ = "kb_term_relation_revision"
    __table_args__ = (
        CheckConstraint(_STATE, name="ck_kb_term_relation_state"),
        CheckConstraint(
            "relation IN ('synonym','false_equivalent','ambiguous','broader','narrower')",
            name="ck_kb_term_relation_kind",
        ),
    )
    relation_revision_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    relation_id: Mapped[str] = mapped_column(String(160), index=True)
    term_a: Mapped[str] = mapped_column(String(120))
    term_b: Mapped[str] = mapped_column(String(120))
    relation: Mapped[str] = mapped_column(String(24))
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    rev_state, reason, created_by, created_at = _audit()


class KbRuleRevisionRow(Base):
    __tablename__ = "kb_rule_revision"
    __table_args__ = (
        CheckConstraint(_STATE, name="ck_kb_rule_state"),
        CheckConstraint("severity IN ('info','warn','block')", name="ck_kb_rule_severity"),
        CheckConstraint(
            "status IN ('VERIFIED','REFERENCE ONLY','REJECTED')", name="ck_kb_rule_status"
        ),
    )
    rule_revision_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(120), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    expression: Mapped[dict] = mapped_column(KbJson)
    depends_on: Mapped[list] = mapped_column(KbJson)
    status: Mapped[str] = mapped_column(String(32))
    permission_code: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(8))
    expert_signoff: Mapped[dict | None] = mapped_column(KbJson, nullable=True)
    rev_state, reason, created_by, created_at = _audit()


class KbReleaseRow(Base):
    __tablename__ = "kb_release"
    release_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    base_release_id: Mapped[str | None] = mapped_column(
        String(80), ForeignKey("kb_release.release_id", ondelete="RESTRICT"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_by: Mapped[str] = mapped_column(String(128))
    changelog: Mapped[str] = mapped_column(Text)
    manifest: Mapped[dict] = mapped_column(KbJson)
    checksum: Mapped[str] = mapped_column(String(64))
    validation_report: Mapped[dict] = mapped_column(KbJson)
    diff_report: Mapped[dict] = mapped_column(KbJson)


class KbReleaseClaimRow(Base):
    __tablename__ = "kb_release_claim"
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "claim_id"],
            ["kb_claim_revision.revision_id", "kb_claim_revision.claim_id"],
            name="fk_kb_release_claim_revision",
            ondelete="RESTRICT",
        ),
    )
    release_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("kb_release.release_id", ondelete="RESTRICT"), primary_key=True
    )
    claim_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    revision_id: Mapped[str] = mapped_column(String(200))


class KbReleaseArtifactRow(Base):
    __tablename__ = "kb_release_artifact"
    __table_args__ = (
        CheckConstraint(
            "object_kind IN ('term','term_relation','rule','policy','evidence',"
            "'validation_profile')",
            name="ck_kb_release_artifact_kind",
        ),
    )
    release_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("kb_release.release_id", ondelete="RESTRICT"), primary_key=True
    )
    object_kind: Mapped[str] = mapped_column(String(24), primary_key=True)
    object_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    object_revision_id: Mapped[str] = mapped_column(String(200))
    content_hash: Mapped[str] = mapped_column(String(64))


class KbReleaseRetirementRow(Base):
    __tablename__ = "kb_release_retirement"
    release_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("kb_release.release_id", ondelete="RESTRICT"), primary_key=True
    )
    retired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    retired_by: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)


class KbActiveReleaseRow(Base):
    __tablename__ = "kb_active_release"
    slot: Mapped[str] = mapped_column(String(32), primary_key=True)
    release_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("kb_release.release_id", ondelete="RESTRICT")
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    changed_by: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)


class KbActiveReleaseLogRow(Base):
    __tablename__ = "kb_active_release_log"
    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    slot: Mapped[str] = mapped_column(String(32))
    release_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("kb_release.release_id", ondelete="RESTRICT")
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    changed_by: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)


class KbLegacyMapRow(Base):
    __tablename__ = "kb_legacy_map"
    __table_args__ = (
        CheckConstraint(
            "target_kind IN ('claim','term','rule','excluded')", name="ck_kb_legacy_target"
        ),
        CheckConstraint(
            "mapping_type IN ('one_to_one','split','merged','to_term','excluded')",
            name="ck_kb_legacy_mapping",
        ),
    )
    legacy_k_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    target_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    mapping_type: Mapped[str] = mapped_column(String(16))
    explanation: Mapped[str] = mapped_column(Text)
    source_version: Mapped[str] = mapped_column(String(16))


class KbChangeLogRow(Base):
    __tablename__ = "kb_change_log"
    change_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    object_kind: Mapped[str] = mapped_column(String(32))
    object_id: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(128))
    release_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class KbCallerRow(Base):
    __tablename__ = "kb_caller"
    caller_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    description: Mapped[str] = mapped_column(Text)
    purposes: Mapped[list] = mapped_column(KbJson)
