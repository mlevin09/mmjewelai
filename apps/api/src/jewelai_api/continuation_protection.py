"""Carry independent source roots without native semantic-slot cancellation."""

from jewelai_domain.preservation import contract_hash, initial_protection_projection

from .constraint_evidence import merge_constraint_evidence
from .continuation_evaluation import ParsedEvaluationV3


def correction_constraints(previous, evaluation, source, revision, cycle_id, repo):
    scope = previous.context.scope
    constraints = merge_constraint_evidence(
        evaluation,
        session_id=scope.session_id,
        organization_id=scope.organization_id,
        source=source,
        authoritative_revision=revision,
        enrichment_cycle_id=cycle_id,
        previous=previous.constraint_evidence,
        load_source_revision=lambda rid: repo.get_revision(
            scope.session_id, rid, scope.organization_id
        ),
        _enrichment_reader=ParsedEvaluationV3,
    )
    protected = {r.root_ref.evidence_id for r in previous.protection_projection.roots}
    originals = {
        e.evidence_id: e for e in previous.constraint_evidence if e.evidence_id in protected
    }
    return tuple(
        sorted((originals.get(e.evidence_id, e) for e in constraints), key=lambda e: e.evidence_id)
    )


def extend_protection(protection, revision, constraints, cycle_id, *, source_text):
    from jewelai_domain.preservation import build_preservation_root

    from .continuation_history import preservation_field

    old_ids = {r.root_ref.evidence_id for r in protection.roots}
    roots = []
    for e in constraints:
        if (
            e.status != "active"
            or e.kind != "preservation"
            or e.semantic_subject != "component.center_stone"
            or e.evidence_id in old_ids
        ):
            continue
        if e.source_revision_id != revision.revision_id or e.source_enrichment_cycle_id != cycle_id:
            raise ValueError("New root does not belong to the actual correction cycle")
        roots.append(
            build_preservation_root(
                evidence_id=e.evidence_id,
                evidence_hash=e.content_hash,
                source_revision=revision,
                source_cycle_id=cycle_id,
                field=preservation_field(
                    e.original_wording,
                    source_text=source_text,
                    span_start=e.source_span_start,
                    span_end=e.source_span_end,
                ),
            )
        )
    if not roots:
        return protection
    added = initial_protection_projection(revision, protection.scope, roots)
    p = protection.model_dump(mode="python", exclude={"content_hash"})
    p.update(
        roots=tuple(
            sorted((*protection.roots, *added.roots), key=lambda r: r.root_ref.evidence_id)
        ),
        anchors=tuple(
            sorted(
                (*protection.anchors, *added.anchors),
                key=lambda a: (a.root_evidence_id, a.target.concrete_target),
            )
        ),
    )
    return type(protection)(
        **p, content_hash=contract_hash("jewelai.ProtectionProjection/1.0.0", p)
    )
