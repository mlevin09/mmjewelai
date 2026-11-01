"""F03: independent assertions retain authority through Matrix, EDIT and final output."""

import pytest
from jewelai_domain.knowledge_policy import RuntimeProvenance
from jewelai_domain.revisions import lock_field
from test_core_intent import _current, _field, _scenario, _seed, _submit
from test_f01_ownership import exercise_f01_case
from test_p010_symmetry_runtime import exercise_keep_correction_sequence

CONTRAST_CASES = (
    (
        "ru-contrast",
        "Не платина, а кольцо из золота с овальным алмазом.",
        "ru",
        {
            "metal.material": "gold",
            "center_stone.shape": "oval",
            "center_stone.material": "diamond",
        },
    ),
    (
        "mixed-contrast",
        "Не платина, а gold ring with an oval diamond.",
        "ru",
        {
            "metal.material": "gold",
            "center_stone.shape": "oval",
            "center_stone.material": "diamond",
        },
    ),
    ("reordered-contrast", "Кольцо из золота, а не платины.", "ru", {"metal.material": "gold"}),
    (
        "independent-stone-contrast",
        "Не круглый сапфир, а овальный алмаз в золотом кольце.",
        "ru",
        {
            "metal.material": "gold",
            "center_stone.shape": "oval",
            "center_stone.material": "diamond",
        },
    ),
    (
        "component-owner-contrast",
        "Не золотые крапаны, а кольцо из платины.",
        "ru",
        {"metal.material": "platinum"},
    ),
    ("unresolved-inflection-control", "Не золотые крапаны, а платиновое кольцо.", "ru", {}),
    ("en-control", "No platinum, but a gold ring.", "en", {"metal.material": "gold"}),
    ("ru-alternatives-control", "Кольцо из золота, а платина.", "ru", {}),
    ("negative-list-control", "Кольцо, без гало, золота или платины.", "ru", {}),
    ("ru-preference-control", "Не платина, а хочу золото.", "ru", {}),
    ("ru-uncertain-control", "Не платина, а возможно золото.", "ru", {}),
)


@pytest.mark.parametrize("binding", (False, True))
@pytest.mark.parametrize("case", CONTRAST_CASES, ids=[case[0] for case in CONTRAST_CASES])
def test_contrast_http_state_output_and_restart(engine, tmp_path, monkeypatch, binding, case):
    # Existing helper verifies actual Messages/Parser/Matrix, canonical facts,
    # source IDs/spans, description/IFP, immutable cycles, release pins and restart.
    exercise_f01_case(engine, tmp_path, monkeypatch, case, binding)


@pytest.mark.parametrize("binding", (False, True))
def test_authorized_edit_is_distinct_from_advisory_precedence(
    engine, tmp_path, monkeypatch, binding
):
    with _scenario(engine, tmp_path, monkeypatch, binding=binding, locale="ru") as ctx:
        _, initial, _, _ = _submit(ctx, "Кольцо из золота с овальным алмазом.")
        evaluation_index = len(ctx.evaluations)
        before, after, state, message = _submit(
            ctx, "Не золото, а кольцо из платины.", "corrections"
        )
        # Matrix evaluates NORMALIZED_FROM_USER against a canonical explicit
        # fact; it does not itself authorize or apply an explicit user EDIT.
        pre_edit = ctx.evaluations[evaluation_index][2]
        decision = next(
            d for d in pre_edit.enrichment_result.decisions if d.target == "metal.material"
        )
        assert decision.proposal.provenance == RuntimeProvenance.NORMALIZED_FROM_USER
        assert (decision.outcome, decision.reason) == ("KEPT", "lower_precedence")
        assert decision.result.value == "gold"
        assert before == initial and after.revision_id != initial.revision_id
        assert after.design.metal.material.value == "platinum"
        assert after.design.metal.material.source.message_id == message["message_id"]
        assert after.design.center_stone == before.design.center_stone
        assert _current(ctx) == after
        facts = {f.target: f for f in state.final_output.internal_final_prompt.design_facts}
        assert facts["metal.material"].value == "platinum"
        assert _field(after, "center_stone.shape").value == "oval"
        assert "платина" in state.final_output.description.text
        assert ctx.provider.calls == []


@pytest.mark.parametrize("binding", (False, True))
def test_contrast_cannot_bypass_current_lock(engine, tmp_path, monkeypatch, binding):
    with _scenario(engine, tmp_path, monkeypatch, binding=binding, locale="ru") as ctx:
        confirmed = _seed(ctx, material=True)
        locked = lock_field(
            confirmed,
            "metal.material",
            expected_revision_id=confirmed.revision_id,
            source=confirmed.design.metal.material.source,
            reason="Explicit F03 fixture lock",
            created_at=confirmed.created_at,
        )
        ctx.repo.append_revision_cas(ctx.sid, ctx.org, confirmed.revision_id, locked)
        _submit(ctx, "Кольцо из золота.")
        evaluation_index = len(ctx.evaluations)
        _, after, state, _ = _submit(ctx, "Не золото, а кольцо из платины.", "corrections")
        assert after.design.metal.material == locked.design.metal.material
        assert any(
            d.outcome == "BLOCKED" and "LOCKED_FIELD_CONFLICT" in d.parser_issue_codes
            for d in ctx.evaluations[evaluation_index][2].dispositions
        )
        fact = next(
            f
            for f in state.final_output.internal_final_prompt.design_facts
            if f.target == "metal.material"
        )
        assert fact.value == "gold" and fact.confirmed and fact.locked


def test_contrast_preserves_independent_keep_lineage(engine, tmp_path, monkeypatch):
    exercise_keep_correction_sequence(
        engine,
        tmp_path,
        monkeypatch,
        ("Не платина, а кольцо из золота.", "An asymmetric ring."),
    )
