"""Knowledge Library Contract 2.0 on PostgreSQL (ADR 0048): AC-01…AC-11 and v1.2 §12.

Behind the unchanged disposable-PostgreSQL gate: no DDL runs until
``disposable_postgres.verified_ci_postgres`` independently identifies the CI container.
Each fixture works in its own generated schema (search_path), like the existing B2 tests.
"""

import copy
import os
from uuid import uuid4

import disposable_postgres
import pytest
from alembic import command
from alembic.config import Config
from conftest import ROOT
from jewelai_domain.knowledge_kb import KnowledgeKbError
from jewelai_persistence import create_database_engine, create_session_factory
from jewelai_persistence.kb_models import (
    KbClaimEvidenceRow,
    KbClaimRevisionRow,
    KbLegacyMapRow,
    KbReleaseArtifactRow,
    KbReleaseClaimRow,
    KbReleaseRow,
)
from jewelai_persistence.knowledge_kb import (
    KbAdmin,
    KbPublishBlocked,
    KnowledgeApi,
)
from jewelai_persistence.knowledge_kb_pilot import claim_identity, load_seed, read_seed
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.postgres

PILOT = "kb-2.0.0-pilot"
SO = "semantic_orchestrator"
RUBY = "gem.corundum.ruby"


def _schema_url(url, schema):
    assert schema.startswith("kb_") and len(schema) == 35
    assert all(c in "0123456789abcdef" for c in schema[3:])
    return url + "?options=-csearch_path=" + schema


def _fresh_schema():
    if os.getenv("GITHUB_ACTIONS") != "true":
        pytest.skip(
            "NOT VERIFIED locally: kb requires independently verified disposable PostgreSQL"
        )
    url = disposable_postgres.verified_ci_postgres()
    control = create_database_engine(url)
    schema = "kb_" + uuid4().hex
    with control.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    control.dispose()
    scoped = _schema_url(url, schema)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = scoped
    try:
        command.upgrade(Config(str(ROOT / "packages/persistence/alembic.ini")), "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
    return scoped


def _published(scoped):
    engine = create_database_engine(scoped)
    factory = create_session_factory(engine)
    with factory() as session, session.begin():
        report = load_seed(session, read_seed(), "kb-test")
        admin = KbAdmin(session, "kb-test")
        admin.publish(PILOT, "pilot release for tests", None)
        admin.activate(PILOT, "test activation")
    return engine, factory, report


@pytest.fixture(scope="module")
def pilot():
    engine, factory, report = _published(_fresh_schema())
    yield engine, factory, report
    engine.dispose()


@pytest.fixture
def fresh():
    engine, factory, report = _published(_fresh_schema())
    yield engine, factory, report
    engine.dispose()


def _api(factory, caller=SO):
    return KnowledgeApi(factory, caller)


def _code(error):
    return error.value.code


# ---------------------------------------------------------------- B2: re-qualification


def test_requalification_demotes_only_records_without_full_source_match(pilot):
    _, factory, report = pilot
    assert (report["verified"], report["reference_only"], report["rejected"]) == (108, 177, 2)
    demoted = {k for item in report["demoted"] for k in item["legacy"]}
    reasons = " ".join(item["reason"] for item in report["demoted"])
    assert len(report["demoted"]) == 13
    # 7 JP sizes (no JP rule in EV-RING), 3 purity rows (EV-CARAT is mass, not fineness),
    # 3 EU sizes that v1.6.2 rounded inconsistently.
    assert {"K-14282", "K-02644", "K-14293", "K-14337", "K-14353"} <= demoted
    assert "no automatic source comparison" in reasons
    with factory() as session:
        purity = session.scalars(
            select(KbClaimRevisionRow).where(KbClaimRevisionRow.claim_id.like("%karat_fineness%"))
        ).all()
        assert {row.status for row in purity} == {"REFERENCE ONLY"}
        assert all(row.qualification["demoted"] for row in purity)


def test_ac11_every_imported_k_id_has_an_explainable_mapping(pilot):
    _, factory, _ = pilot
    seed = read_seed()
    expected = {k for claim in seed["claims"] for k, _, _ in claim["legacy"]}
    with factory() as session:
        rows = session.scalars(select(KbLegacyMapRow)).all()
    assert {row.legacy_k_id for row in rows} == expected
    assert all(row.explanation and row.source_version == "v1.6.2" for row in rows)
    by_k = {}
    for row in rows:
        by_k.setdefault(row.legacy_k_id, []).append(row)
    assert len(by_k["K-17678"]) == 40 and {r.mapping_type for r in by_k["K-17678"]} == {"split"}
    assert len(by_k["K-04474"]) == 2  # «рубин, сапфир» split per variety
    assert {r.mapping_type for r in by_k["K-17166"]} == {"split"}  # 6.4–6.5 mixed sources
    assert {r.target_kind for r in by_k["K-05100"]} == {"excluded"}


# ------------------------------------------------------------------ AC-01 immutability


def test_ac01_publish_is_idempotent_and_conflicts_on_a_different_payload(fresh):
    _, factory, _ = fresh
    with factory() as session, session.begin():
        admin = KbAdmin(session, "kb-test")
        first = session.get(KbReleaseRow, PILOT).checksum
        assert admin.publish(PILOT, "replay").checksum == first
        admin.draft_artifact(
            "evidence",
            "EV-EXTRA@1",
            "new source",
            ev_id="EV-EXTRA",
            org="x",
            title="x",
            fragment="x",
            tier="Q3",
        )
        with pytest.raises(KnowledgeKbError) as error:
            admin.publish(PILOT, "different payload under the same id")
        assert _code(error) == "payload_conflict"


@pytest.mark.parametrize(
    "statement",
    [
        lambda: update(KbClaimRevisionRow).values(status="REJECTED"),
        lambda: delete(KbClaimRevisionRow),
        lambda: delete(KbReleaseClaimRow),
        lambda: update(KbReleaseArtifactRow).values(content_hash="0" * 64),
        lambda: update(KbReleaseRow).values(checksum="0" * 64),
        lambda: delete(KbLegacyMapRow),
        lambda: update(KbClaimEvidenceRow).values(check_id="tampered"),
    ],
    ids=["rev-update", "rev-delete", "member-delete", "artifact-update", "release", "legacy", "ev"],
)
def test_ac01_published_rows_and_membership_are_immutable_in_postgres(pilot, statement):
    engine, _, _ = pilot
    with pytest.raises(DBAPIError, match="kb:"):
        with engine.begin() as db:
            db.execute(statement())


def test_ac01_truncate_and_direct_published_insert_are_rejected(pilot):
    engine, _, _ = pilot
    with pytest.raises(DBAPIError, match="append-only"):
        with engine.begin() as db:
            db.execute(text("TRUNCATE kb_release_claim"))
    with pytest.raises(DBAPIError, match="must start as draft"):
        with engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO kb_evidence_revision (ev_revision_id, ev_id, org, title, "
                    "fragment, tier, rev_state, reason, created_by) VALUES "
                    "('EV-X@1','EV-X','o','t','f','Q1','published','r','a')"
                )
            )


# ---------------------------------------------------------- AC-02, AC-03 release pinning


def _new_policy_release(factory):
    """Release N+1: a changed ruby SG value and a policy revision without prompt."""
    with factory() as session, session.begin():
        admin = KbAdmin(session, "kb-test")
        claim_id = claim_identity(RUBY, "mohs_hardness", {})
        admin.draft_claim(
            entity_id=RUBY,
            attribute_id="mohs_hardness",
            scope={},
            revision_id=f"{claim_id}@2",
            value={"num": "9"},
            value_kind="exact",
            status="REFERENCE ONLY",
            permission_code="RESEARCH_WITH_CAVEAT",
            qualification={"method": "ordinal_scale", "outcome": "no_source"},
            reason="test: downgrade in N+1",
            evidence=[{"ev_revision_id": "EV-GIA-RUBY@1", "source_value": {"num": "9"}}],
        )
        admin.draft_artifact(
            "policy",
            "policy-r2:FACT_DISPLAY_RENDER_HINT",
            "test: prompt withdrawn",
            permission_code="FACT_DISPLAY_RENDER_HINT",
            allowed_status="VERIFIED",
            uses=["display", "explain"],
            prompt_conditions="",
            forbidden="prompt",
            conditions="",
        )
        admin.publish("kb-2.0.1", "N+1")
        admin.activate("kb-2.0.1", "test")


def test_ac02_ac03_pinned_session_keeps_release_n_after_n_plus_1(fresh):
    _, factory, _ = fresh
    api = _api(factory)
    before = api.get_claims(RUBY, "prompt", PILOT)
    assert {c.attribute for c in before.claims} == {"mohs_hardness", "refractive_index"}
    _new_policy_release(factory)
    after_on_n = api.get_claims(RUBY, "prompt", PILOT)
    assert after_on_n == before  # same revisions, same policy revision, same provenance
    assert api.get_release("active")["release_id"] == "kb-2.0.1"
    on_n1 = api.get_claims(RUBY, "prompt", "kb-2.0.1")
    assert on_n1.claims == ()  # new policy revision withdraws prompt; old sessions unaffected
    display = api.get_claims(RUBY, "display_caveat", "kb-2.0.1", attributes=["mohs_hardness"])
    assert display.claims[0].revision_id.endswith("@2")
    assert display.claims[0].policy_revision_id == "policy-r1:RESEARCH_WITH_CAVEAT"


def test_ac03_prompt_returns_only_prompt_permitted_claims_with_provenance(pilot):
    _, factory, _ = pilot
    api = _api(factory)
    result = api.get_claims(RUBY, "prompt", PILOT)
    for claim in result.claims:
        assert "prompt" in claim.allowed_uses and claim.status == "VERIFIED"
        assert claim.evidence_revision_ids == ("EV-GIA-RUBY@1",)
        assert claim.policy_revision_id == f"policy-r1:{claim.permission_code}"
        assert claim.release_id == PILOT and claim.legacy_k_ids
    denied = {d.claim_id for d in result.denials}
    # SG (FACT_PARTIAL_DISPLAY_ONLY), care (CARE_GUIDANCE_CONDITIONAL), reference text.
    assert claim_identity(RUBY, "specific_gravity", {}) in denied
    assert claim_identity(RUBY, "care_steam", {"treatment": "untreated"}) in denied


# ---------------------------------------------------------------- AC-04 release errors


def test_ac04_unknown_unavailable_and_unpinned_releases_are_typed_errors(fresh):
    _, factory, _ = fresh
    api = _api(factory)
    for release in ("kb-9.9.9", "active", ""):
        with pytest.raises(KnowledgeKbError) as error:
            api.get_claims(RUBY, "display", release)
        assert _code(error) == "release_not_found"
    _new_policy_release(factory)
    with factory() as session, session.begin():
        KbAdmin(session, "kb-test").retire(PILOT, "test retention")
    with pytest.raises(KnowledgeKbError) as error:
        api.get_claims(RUBY, "display", PILOT)
    assert _code(error) == "release_unavailable"
    assert api.get_claims(RUBY, "display", "kb-2.0.1").claims  # existing old release ok


# --------------------------------------------------------------- AC-05, AC-06 content QA


def test_ac05_verified_without_full_source_match_blocks_publication(fresh):
    _, factory, _ = fresh
    with factory() as session, session.begin():
        admin = KbAdmin(session, "kb-test")
        claim_id = claim_identity("gem.corundum.sapphire", "mohs_hardness", {})
        admin.draft_claim(
            entity_id="gem.corundum.sapphire",
            attribute_id="mohs_hardness",
            scope={},
            revision_id=f"{claim_id}@2",
            value={"num": "8.75"},  # a universal ±0.25 would have accepted this
            value_kind="exact",
            status="VERIFIED",
            permission_code="FACT_DISPLAY_RENDER_HINT",
            qualification={"profile_revision_id": "mohs_ordinal@1", "outcome": "source_match"},
            reason="test",
            evidence=[{"ev_revision_id": "EV-GIA-SAPH@1", "source_value": {"num": "9"}}],
        )
        with pytest.raises(KbPublishBlocked) as blocked:
            admin.publish("kb-bad", "must fail")
    errors = blocked.value.report["errors"]
    assert any("without full source match" in e and claim_id in e for e in errors)
    with factory() as session:
        assert session.get(KbReleaseRow, "kb-bad") is None


def test_ac06_stuller_points_are_approximate_and_never_tolerances(pilot):
    _, factory, _ = pilot
    api = _api(factory)
    one_carat = api.get_claims(
        "gem.diamond",
        "prompt",
        PILOT,
        attributes=["diameter_at_weight"],
        scope={"carat_weight": "1"},
    ).claims
    assert len(one_carat) == 1
    claim = one_carat[0]
    assert claim.value == {"num": "6.4"} and claim.approximate and claim.unit == "mm"
    assert claim.qualification_method == "approximate_point"
    assert "calc_reference" not in claim.allowed_uses  # not a production calculation
    dalila = api.get_claims(
        "gem.diamond", "prompt", PILOT, attributes=["typical_diameter_range_at_weight"]
    )
    assert dalila.claims == () and dalila.denials  # secondary range: reference only


# -------------------------------------------------------------------- AC-07 metals


def test_ac07_generic_grades_are_not_verified_and_gost_density_is_not_prompt(pilot):
    _, factory, _ = pilot
    api = _api(factory)
    for generic in ("metal.silver.925", "metal.platinum.950"):
        result = api.get_claims(generic, "display_caveat", PILOT)
        assert {c.status for c in result.claims} == {"REFERENCE ONLY"}
        assert api.get_claims(generic, "prompt", PILOT).claims == ()
    alloy = "metal.alloy.plpd_850_150"
    assert api.get_claims(alloy, "prompt", PILOT).claims == ()
    reference = api.get_claims(alloy, "calc_reference", PILOT).claims[0]
    assert reference.value == {"num": "19.25"} and reference.status == "VERIFIED"
    assert "prompt" not in reference.allowed_uses and "legal_info" not in reference.allowed_uses


# ------------------------------------------------------- AC-08 rules, no State writes


def test_ac08_block_is_disabled_and_rules_are_metadata_only(fresh):
    _, factory, _ = fresh
    with factory() as session, session.begin():
        admin = KbAdmin(session, "kb-test")
        admin.draft_artifact(
            "rule",
            "rule.corundum_filled_care@1",
            "test fixture rule",
            rule_id="rule.corundum_filled_care",
            kind="care_constraint",
            expression={"entities_any": [RUBY], "reason": "filled stones: damp cloth only"},
            depends_on=[],
            status="VERIFIED",
            permission_code="CARE_GUIDANCE_CONDITIONAL",
            severity="block",
            expert_signoff=None,
        )
        published = admin.publish("kb-rules", "rule fixture")
        assert any("without expert sign-off" in w for w in published.validation_report["warnings"])
    api = _api(factory)
    with pytest.raises(KnowledgeKbError) as error:
        api.evaluate_rules({"entities": [RUBY]}, "kb-rules", purpose="validate_block")
    assert _code(error) == "purpose_not_allowed"
    for preview in (True, False):
        rules = api.evaluate_rules({"entities": [RUBY]}, "kb-rules", preview=preview)
        assert [r.severity for r in rules] == ["block"] and not rules[0].enforced


def test_ac08_knowledge_api_is_read_only_and_never_touches_product_state(pilot):
    engine, factory, _ = pilot
    api = _api(factory)
    with engine.connect() as db:
        before = {
            table: db.scalar(text(f"SELECT count(*) FROM {table}"))
            for table in ("design_session", "specification_revision", "kb_change_log")
        }
    api.get_release(PILOT)
    api.resolve_terms("рубин", PILOT)
    api.get_claims(RUBY, "display", PILOT)
    api.evaluate_claim(RUBY, "specific_gravity", {"num": "4"}, PILOT)
    _api(factory, "consultant").search_knowledge("рубин", PILOT)
    with engine.connect() as db:
        after = {table: db.scalar(text(f"SELECT count(*) FROM {table}")) for table in before}
    assert after == before
    with pytest.raises(DBAPIError, match="read-only transaction"):
        api._read(lambda session: session.execute(text("DELETE FROM kb_caller")))


# --------------------------------------------------------- AC-09 reference and rejected


def test_ac09_reference_only_needs_caveat_and_rejected_is_never_returned(pilot):
    _, factory, _ = pilot
    api = _api(factory)
    references = api.get_claims("gem.corundum", "display_caveat", PILOT).claims
    assert references and all(c.caveat for c in references)
    assert all(c.status == "REFERENCE ONLY" for c in references)
    assert api.get_claims("gem.corundum", "prompt", PILOT).claims == ()
    rejected = {claim_identity("gem.corundum", "legacy_reference", {"legacy_k_id": "K-05100"})}
    everything = api.get_claims("gem.corundum", "display_caveat", PILOT)
    shown = {c.claim_id for c in everything.claims} | {d.claim_id for d in everything.denials}
    assert not rejected & shown
    consultant = _api(factory, "consultant")
    found = {item["claim_id"] for item in consultant.search_knowledge("сапфир", PILOT)}
    assert found and not rejected & found
    hits = consultant.search_knowledge("рубин", PILOT)
    assert hits and all(not item["prompt_permission"] for item in hits)
    with pytest.raises(KnowledgeKbError):
        api.search_knowledge("рубин", PILOT)  # SO has no search purpose


# ---------------------------------------------------------- AC-10 terms and conflicts


def test_ac10_ambiguity_false_equivalents_and_conflicts(fresh):
    _, factory, _ = fresh
    api = _api(factory)
    karat_ru = api.resolve_terms("Карат", PILOT)
    assert karat_ru.ambiguous
    assert {c.entity_id for c in karat_ru.candidates} == {
        "measure.metric_carat",
        "metal.gold.karat",
    }
    carat = api.resolve_terms("carat", PILOT, lang="en")
    assert not carat.ambiguous and carat.candidates[0].entity_id == "measure.metric_carat"
    assert any("karat" in warning for warning in carat.false_equivalent_warnings)
    with pytest.raises(KnowledgeKbError) as error:
        api.resolve_terms("изумруд", PILOT)
    assert _code(error) == "unknown_entity"
    # A contradicting source on a reference claim: review_required, never a silent winner.
    claim_id = claim_identity(
        "gem.diamond",
        "typical_diameter_range_at_weight",
        {"shape": "round", "carat_weight": "1.5", "reference": "dalila_typical"},
    )
    with factory() as session, session.begin():
        admin = KbAdmin(session, "kb-test")
        admin.draft_claim(
            entity_id="gem.diamond",
            attribute_id="typical_diameter_range_at_weight",
            scope={"shape": "round", "carat_weight": "1.5", "reference": "dalila_typical"},
            revision_id=f"{claim_id}@2",
            value={"min": "7.3", "max": "7.5"},
            value_kind="source_range",
            status="REFERENCE ONLY",
            permission_code="RESEARCH_WITH_CAVEAT",
            qualification={"outcome": "conflict"},
            reason="test: Stuller point 7.2 outside the retail range",
            evidence=[
                {
                    "ev_revision_id": "EV-DALILA-SIZE@1",
                    "source_value": {"min": "7.3", "max": "7.5"},
                },
                {"ev_revision_id": "EV-STULLER@1", "role": "contradicts"},
            ],
        )
        admin.publish("kb-conflict", "conflict fixture")
    result = api.evaluate_claim(
        "gem.diamond",
        "typical_diameter_range_at_weight",
        {"min": "7.3", "max": "7.5"},
        "kb-conflict",
        scope={"shape": "round", "carat_weight": "1.5", "reference": "dalila_typical"},
    )
    assert result.result == "review_required" and "no winner" in result.reason


def test_evaluate_claim_is_qualification_not_permission(pilot):
    _, factory, _ = pilot
    api = _api(factory)
    supported = api.evaluate_claim(RUBY, "specific_gravity", {"num": "4.00"}, PILOT)
    assert supported.result == "supported" and not hasattr(supported, "allowed_uses")
    assert api.evaluate_claim(RUBY, "specific_gravity", {"num": "3.5"}, PILOT).result == (
        "contradicted"
    )
    unknown = api.evaluate_claim(RUBY, "density", {"num": "4"}, PILOT)
    assert unknown.result == "unknown"
    # SG is FACT_PARTIAL_DISPLAY_ONLY: a supported check still grants no prompt use.
    assert claim_identity(RUBY, "specific_gravity", {}) in {
        d.claim_id for d in api.get_claims(RUBY, "prompt", PILOT).denials
    }


def test_callers_and_purposes_are_authorized_server_side(pilot):
    _, factory, _ = pilot
    for caller, purpose in (("trainer", "prompt"), ("nobody", "display"), (SO, "legal_info")):
        with pytest.raises(KnowledgeKbError) as error:
            _api(factory, caller).get_claims(RUBY, purpose, PILOT)
        assert _code(error) == "purpose_not_allowed"
    with pytest.raises(KnowledgeKbError) as error:
        _api(factory).get_claims(RUBY, "verify_evidence", PILOT)
    assert _code(error) == "purpose_not_allowed"


# --------------------------------------------------------- rollback and portable package


def test_revert_creates_a_new_release_and_leaves_history_unchanged(fresh):
    _, factory, _ = fresh
    _new_policy_release(factory)
    with factory() as session, session.begin():
        admin = KbAdmin(session, "kb-test")
        old = session.get(KbReleaseRow, PILOT).checksum
        reverted = admin.revert(PILOT, "kb-2.0.2", "test rollback")
        admin.activate("kb-2.0.2", "rollback")
        assert reverted.checksum == old and reverted.kind == "revert"
        assert session.get(KbReleaseRow, "kb-2.0.1").checksum != old
    api = _api(factory)
    assert {c.attribute for c in api.get_claims(RUBY, "prompt", "kb-2.0.2").claims} == {
        "mohs_hardness",
        "refractive_index",
    }


def test_release_package_moves_to_an_independent_deployment_with_identical_checksum(pilot):
    _, factory, _ = pilot
    with factory() as session:
        package = KbAdmin(session, "kb-test").export_release(PILOT)
    target = create_database_engine(_fresh_schema())
    target_factory = create_session_factory(target)
    try:
        with target_factory() as session, session.begin():
            imported = KbAdmin(session, "kb-import").import_release(package)
            assert imported.checksum == package["checksum"]
            again = KbAdmin(session, "kb-import").import_release(package)
            assert again.checksum == package["checksum"]
            tampered = copy.deepcopy(package)
            tampered["checksum"] = "0" * 64
            with pytest.raises(KnowledgeKbError) as error:
                KbAdmin(session, "kb-import").import_release(tampered)
            assert _code(error) == "payload_conflict"
            count = session.scalar(select(func.count()).select_from(KbReleaseClaimRow))
            assert count == package["manifest"]["claims"]
    finally:
        target.dispose()


def test_downgrade_refuses_to_destroy_published_releases(pilot):
    engine, _, _ = pilot
    # Keep '=' unescaped for Alembic's ConfigParser, as the existing B2 helper does.
    url = engine.url.render_as_string(hide_password=False).replace("%3D", "=")
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        with pytest.raises(RuntimeError, match="kb downgrade refused"):
            command.downgrade(Config(str(ROOT / "packages/persistence/alembic.ini")), "-1")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
