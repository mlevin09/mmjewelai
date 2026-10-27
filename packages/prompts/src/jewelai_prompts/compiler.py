"""Canonical Design traversal, rendering, hashing, and fail-closed validation."""

import hashlib
import json

from jewelai_domain.models_v1_1 import AnyDesignRevision, validate_design_revision

from .models import (
    PROMPT_COMPILER_VERSION,
    CompiledPrompt,
    PromptConstraint,
    PromptDisclosure,
    PromptTemplate,
    PromptTemplateBundle,
    SpecificationEntry,
)
from .revision_projection import _disclosures, _entries


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
