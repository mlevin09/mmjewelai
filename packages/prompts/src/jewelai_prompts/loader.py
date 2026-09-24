"""Explicit versioned prompt-template loading."""

import json
from pathlib import Path

from .models import PromptTemplateBundle


def load_prompt_templates(path: str | Path) -> PromptTemplateBundle:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return PromptTemplateBundle.model_validate(data)
