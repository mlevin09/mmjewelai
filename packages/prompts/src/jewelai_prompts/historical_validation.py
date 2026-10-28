"""Strict read-only validation of frozen enrichment 1.2 compiled sources.

This is not a current compiler/writer. Reuse the unchanged original renderer and revision
projection to verify every original field, without calling compile_prompt or rewriting history.
"""

import hashlib

from .compiler import _render, _template
from .models import CompiledPrompt
from .revision_projection import project_revision


def validate_historical_compiled_source(compiled, revision, templates):
    projection = project_revision(revision)
    template = _template(templates, compiled.template_id)
    text = _render(
        template,
        projection.specification_entries,
        projection.locked_constraints,
        projection.disclosures,
    )
    expected = CompiledPrompt(
        template_id=template.template_id,
        template_version=template.template_version,
        template_artifact_version=templates.artifact_version,
        specification_revision_id=revision.revision_id,
        design_id=revision.design_id,
        design_schema_version=revision.schema_version,
        prompt_text=text,
        specification_entries=projection.specification_entries,
        locked_constraints=projection.locked_constraints,
        disclosures=projection.disclosures,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
    if compiled != expected:
        raise ValueError("historical compiled source does not match its pinned rendering")
