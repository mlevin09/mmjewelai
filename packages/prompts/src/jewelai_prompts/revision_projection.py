"""Pure canonical projection shared with the frozen legacy compiler; no text rendering."""

from jewelai_domain.models import (
    Assumed,
    Derived,
    Explicit,
    ImmutableModel,
    KnownValue,
    NotApplicable,
    Unknown,
)
from jewelai_domain.models_v1_1 import AnyDesignRevision, validate_design_revision
from jewelai_domain.state_paths import iter_prompt_state_fields

from .models import PromptConstraint, PromptDisclosure, PromptSourceReference, SpecificationEntry


class RevisionProjection(ImmutableModel):
    specification_entries: tuple[SpecificationEntry, ...]
    locked_constraints: tuple[PromptConstraint, ...]
    disclosures: tuple[PromptDisclosure, ...]


def _state_entry(path: str, state) -> SpecificationEntry | None:
    if state is None or isinstance(state, Unknown):
        return None
    if isinstance(state, NotApplicable):
        return SpecificationEntry(
            concrete_target=path,
            applicability="not_applicable",
            value=None,
            origin="explicit",
            confirmed=state.confirmed,
            locked=state.locked,
        )
    if not isinstance(state, KnownValue):
        raise TypeError(f"Unsupported canonical state at {path}")
    return SpecificationEntry(
        concrete_target=path,
        applicability="value",
        value=state.model_dump(mode="json")["value"],
        origin=state.origin,
        confirmed=state.confirmed,
        locked=state.locked,
    )


def _entries(revision: AnyDesignRevision | object) -> tuple[SpecificationEntry, ...]:
    revision = validate_design_revision(revision)
    return tuple(
        item
        for path, state in iter_prompt_state_fields(revision)
        if (item := _state_entry(path, state)) is not None
    )


def _source_reference(source) -> PromptSourceReference:
    identifier = source.record_id if source.kind == "knowledge" else source.rule_id
    return PromptSourceReference(kind=source.kind, identifier=identifier, version=source.version)


def _state_disclosure(path: str, state) -> PromptDisclosure | None:
    if isinstance(state, Derived):
        return PromptDisclosure(
            concrete_target=path,
            origin="derived",
            uncertainty=state.uncertainty,
            sources=tuple(_source_reference(item) for item in state.sources),
        )
    if isinstance(state, Assumed):
        return PromptDisclosure(
            concrete_target=path,
            origin="assumed",
            rationale=state.rationale,
            sources=(_source_reference(state.source),),
        )
    if isinstance(state, NotApplicable):
        return PromptDisclosure(concrete_target=path, origin="not_applicable", reason=state.reason)
    if isinstance(state, Explicit | Unknown) or state is None:
        return None
    return None


def _disclosures(revision: AnyDesignRevision | object) -> tuple[PromptDisclosure, ...]:
    revision = validate_design_revision(revision)
    by_path = {item.concrete_target for item in _entries(revision)}
    return tuple(
        disclosure
        for path, state in iter_prompt_state_fields(revision)
        if path in by_path and (disclosure := _state_disclosure(path, state)) is not None
    )


def project_revision(revision: AnyDesignRevision | object) -> RevisionProjection:
    """Project existing values exactly, with fresh JSON values and no policy or compiler calls."""
    revision = validate_design_revision(revision)
    entries = _entries(revision)
    return RevisionProjection(
        specification_entries=entries,
        locked_constraints=tuple(
            PromptConstraint(
                concrete_target=item.concrete_target,
                applicability=item.applicability,
                value=item.value,
            )
            for item in entries
            if item.locked
        ),
        disclosures=_disclosures(revision),
    )
