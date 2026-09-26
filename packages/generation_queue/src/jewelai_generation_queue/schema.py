"""Published Generation Task JSON Schema."""

from .models import GenerationTaskEnvelope


def generation_task_json_schema() -> dict:
    return GenerationTaskEnvelope.model_json_schema()
