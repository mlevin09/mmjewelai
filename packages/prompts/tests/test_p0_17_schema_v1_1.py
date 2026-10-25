from pathlib import Path

from jewelai_domain.models import DesignRevision
from jewelai_domain.models_v1_1 import upgrade_design_revision_v1_to_v1_1
from jewelai_prompts import compile_prompt, load_prompt_templates

ROOT = Path(__file__).resolve().parents[3]
RING = ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json"
PROMPTS = ROOT / "data" / "prompts" / "v1.0.0.json"


def test_prompt_text_is_compatible_when_v1_revision_is_only_upgraded():
    v1 = DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))
    upgraded = upgrade_design_revision_v1_to_v1_1(v1)
    templates = load_prompt_templates(PROMPTS)

    old = compile_prompt(v1, templates)
    new = compile_prompt(upgraded, templates)

    assert old.design_schema_version == "1.0.0"
    assert new.design_schema_version == "1.1.0"
    assert old.prompt_text == new.prompt_text
    assert old.specification_entries == new.specification_entries
    assert old.locked_constraints == new.locked_constraints
    assert old.disclosures == new.disclosures


def test_v1_1_new_state_is_compiled_when_explicitly_present():
    v1 = DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))
    payload = upgrade_design_revision_v1_to_v1_1(v1).model_dump(mode="json")
    payload["design"]["center_stone"]["variety_or_type"] = {
        "availability": "value",
        "origin": "explicit",
        "value": "paraiba_tourmaline",
        "source": payload["event"]["source"],
        "confirmed": False,
        "locked": False,
    }
    upgraded = type(upgrade_design_revision_v1_to_v1_1(v1)).model_validate(payload)
    templates = load_prompt_templates(PROMPTS)

    compiled = compile_prompt(upgraded, templates)

    entries = {item.concrete_target: item for item in compiled.specification_entries}
    assert entries["center_stone.variety_or_type"].value == "paraiba_tourmaline"
    assert "center_stone.variety_or_type" in compiled.prompt_text
