"""Canonical Design traversal, rendering, hashing, and fail-closed validation."""

import hashlib
import json

from jewelai_domain.models import (
    Assumed,
    Derived,
    Explicit,
    KnownValue,
    NotApplicable,
    Unknown,
)
from jewelai_domain.models_v1_1 import AnyDesignRevision, validate_design_revision
from jewelai_domain.state_paths import iter_prompt_state_fields

from .models import (
    PROMPT_COMPILER_VERSION,
    CompiledPrompt,
    PromptConstraint,
    PromptDisclosure,
    PromptSourceReference,
    PromptTemplate,
    PromptTemplateBundle,
    SpecificationEntry,
)


class PromptValidationError(ValueError):
    pass


def compile_prompt(
    revision: AnyDesignRevision | object,
    templates: PromptTemplateBundle,
    *,
    template_id: str = "jewelry_visualization",
) -> CompiledPrompt:
    revision = validate_design_revision(revision)
    templates = PromptTemplateBundle.model_validate(templates)
    template = _template(templates, template_id)
    entries = _entries(revision)
    constraints = tuple(
        PromptConstraint(
            concrete_target=item.concrete_target,
            applicability=item.applicability,
            value=item.value,
        )
        for item in entries
        if item.locked
    )
    disclosures = _disclosures(revision)
    prompt_text = _render(template, entries, constraints, disclosures)
    return CompiledPrompt(
        compiler_version=PROMPT_COMPILER_VERSION,
        template_id=template.template_id,
        template_version=template.template_version,
        template_artifact_version=templates.artifact_version,
        specification_revision_id=revision.revision_id,
        design_id=revision.design_id,
        design_schema_version=revision.schema_version,
        prompt_text=prompt_text,
        specification_entries=entries,
        locked_constraints=constraints,
        disclosures=disclosures,
        content_hash=hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
    )


def validate_compiled_prompt(
    compiled: CompiledPrompt,
    revision: AnyDesignRevision | object,
    templates: PromptTemplateBundle,
) -> CompiledPrompt:
    compiled = CompiledPrompt.model_validate(compiled)
    expected = compile_prompt(revision, templates, template_id=compiled.template_id)
    if compiled != expected:
        raise PromptValidationError(
            "Compiled prompt does not match its canonical revision and template rendering"
        )
    return compiled


def _template(bundle: PromptTemplateBundle, template_id: str) -> PromptTemplate:
    try:
        return next(item for item in bundle.templates if item.template_id == template_id)
    except StopIteration as exc:
        raise KeyError(f"Unknown prompt template ID: {template_id}") from exc


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
    dumped = state.model_dump(mode="json")
    return SpecificationEntry(
        concrete_target=path,
        applicability="value",
        value=dumped["value"],
        origin=state.origin,
        confirmed=state.confirmed,
        locked=state.locked,
    )


def _entries(
    revision: AnyDesignRevision | object,
) -> tuple[SpecificationEntry, ...]:
    revision = validate_design_revision(revision)
    return tuple(
        item
        for path, state in iter_prompt_state_fields(revision)
        if (item := _state_entry(path, state)) is not None
    )


def _source_reference(source) -> PromptSourceReference:
    if source.kind == "knowledge":
        identifier = source.record_id
    else:
        identifier = source.rule_id
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
        return PromptDisclosure(
            concrete_target=path,
            origin="not_applicable",
            reason=state.reason,
        )
    if isinstance(state, Explicit | Unknown) or state is None:
        return None
    return None


def _disclosures(
    revision: AnyDesignRevision | object,
) -> tuple[PromptDisclosure, ...]:
    revision = validate_design_revision(revision)
    by_path = {item.concrete_target: item for item in _entries(revision)}
    return tuple(
        disclosure
        for path, state in iter_prompt_state_fields(revision)
        if path in by_path
        and (disclosure := _state_disclosure(path, state)) is not None
    )


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _render_entry(entry: SpecificationEntry | PromptConstraint) -> str:
    value = "NOT_APPLICABLE" if entry.applicability == "not_applicable" else _json(entry.value)
    return f"{entry.concrete_target} = {value}"


def _render_disclosure(item: PromptDisclosure) -> str:
    payload = item.model_dump(mode="json", exclude_none=True)
    payload.pop("concrete_target")
    return f"{item.concrete_target} = {_json(payload)}"


def _render(template, entries, constraints, disclosures) -> str:
    lines = [template.introduction, *template.instructions]
    if entries:
        lines.extend(("", template.labels.specification))
        lines.extend(_render_entry(item) for item in entries)
    if constraints:
        lines.extend(("", template.labels.locked_constraints))
        lines.extend(_render_entry(item) for item in constraints)
    if disclosures:
        lines.extend(("", template.labels.disclosures))
        lines.extend(_render_disclosure(item) for item in disclosures)
    return "\n".join(lines)
