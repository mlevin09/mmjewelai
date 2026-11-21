"""Full Knowledge Library v1.6.2 corpus in kb (ADR 0048, Architecture v1.2 phase D).

Behind the unchanged disposable-PostgreSQL gate. Loads all 17 682 K-IDs, re-qualifies them,
publishes kb-2.1.0 and checks completeness, statuses, permissions and history.
"""

from pathlib import Path

import pytest
from conftest import ROOT
from jewelai_persistence import create_database_engine, create_session_factory
from jewelai_persistence.kb_models import KbLegacyMapRow, KbReleaseClaimRow, KbReleaseRow
from jewelai_persistence.knowledge_kb import KbAdmin, KnowledgeApi
from jewelai_persistence.knowledge_kb_pilot import load_seed, read_seed
from sqlalchemy import func, select
from test_knowledge_kb_postgres import _fresh_schema

pytestmark = pytest.mark.postgres

CORPUS = ROOT / "data/knowledge-kb/corpus-v1.6.2.json"
RELEASE = "kb-2.1.0"


@pytest.fixture(scope="module")
def corpus():
    engine = create_database_engine(_fresh_schema())
    factory = create_session_factory(engine)
    seed = read_seed(Path(CORPUS))
    with factory() as session, session.begin():
        report = load_seed(session, seed, "kb-corpus-test")
        admin = KbAdmin(session, "kb-corpus-test")
        admin.publish(RELEASE, "full v1.6.2 corpus", None)
        admin.activate(RELEASE, "test")
    yield engine, factory, report, seed
    engine.dispose()


def test_every_v162_k_id_is_in_the_database_with_an_explained_mapping(corpus):
    _, factory, _, seed = corpus
    assert seed["k_ids"] == 17682
    with factory() as session:
        k_ids = session.scalar(select(func.count(func.distinct(KbLegacyMapRow.legacy_k_id))))
        members = session.scalar(
            select(func.count()).where(KbReleaseClaimRow.release_id == RELEASE)
        )
        types = dict(
            session.execute(
                select(
                    KbLegacyMapRow.mapping_type,
                    func.count(func.distinct(KbLegacyMapRow.legacy_k_id)),
                ).group_by(KbLegacyMapRow.mapping_type)
            ).all()
        )
        unexplained = session.scalar(select(func.count()).where(KbLegacyMapRow.explanation == ""))
    assert k_ids == 17682 and members == len(seed["claims"]) == 14658
    assert types["excluded"] == 267 and types["merged"] >= 1 and types["split"] >= 1
    assert types["to_term"] == 2974  # v1.6.2 term rows now live in the term dictionary
    assert unexplained == 0


def test_corpus_statuses_after_requalification(corpus):
    _, factory, report, _ = corpus
    assert (report["verified"], report["reference_only"], report["rejected"]) == (256, 14136, 266)
    assert len(report["demoted"]) == 19
    with factory() as session:
        release = session.get(KbReleaseRow, RELEASE)
    assert release.manifest["status"] == {"REFERENCE ONLY": 14136, "REJECTED": 266, "VERIFIED": 256}
    assert release.manifest["artifacts"]["term"] == 4230
    assert release.validation_report["errors"] == []


def test_diamond_ri_is_verified_by_the_igs_source_and_keeps_the_gia_link(corpus):
    _, factory, _, _ = corpus
    api = KnowledgeApi(factory, "semantic_orchestrator")
    ri = api.get_claims("gem.diamond", "prompt", RELEASE, attributes=["refractive_index"]).claims
    assert len(ri) == 16
    assert all(c.evidence_revision_ids == ("EV-GIA-DIA@1", "EV-IGS-DIA@1") for c in ri)


def test_imported_terms_are_flagged_unreviewed_and_never_outrank_curated_terms(corpus):
    _, factory, _, _ = corpus
    api = KnowledgeApi(factory, "semantic_orchestrator")
    ruby = api.resolve_terms("рубин", RELEASE)
    assert ruby.candidates[0].entity_id == "gem.corundum.ruby"
    assert ruby.candidates[0].review_status == "curated"
    assert not ruby.ambiguous and not ruby.unreviewed_only
    assert any(c.review_status == "unreviewed" for c in ruby.candidates[1:])
    fishtail = api.resolve_terms("рыбий хвост", RELEASE)
    assert fishtail.unreviewed_only
    assert {c.review_status for c in fishtail.candidates} == {"unreviewed"}


def test_corpus_knowledge_api_applies_policies_on_real_entities(corpus):
    _, factory, _, _ = corpus
    api = KnowledgeApi(factory, "semantic_orchestrator")
    emerald = {
        c.attribute: c.value for c in api.get_claims("gem.beryl.emerald", "prompt", RELEASE).claims
    }
    assert emerald["refractive_index"] == {"min": "1.577", "max": "1.583"}
    assert emerald["mohs_hardness"] == {"min": "7.5", "max": "8"}
    tanzanite = api.get_claims(
        "gem.zoisite.tanzanite", "display", RELEASE, attributes=["care_ultrasonic"]
    ).claims
    assert tanzanite and tanzanite[0].value == {"enum": "not_recommended"}
    assert (
        api.get_claims(
            "gem.zoisite.tanzanite", "prompt", RELEASE, attributes=["care_ultrasonic"]
        ).claims
        == ()
    )
    norms = api.get_claims("norm", "display", RELEASE)
    assert norms.claims == () and norms.denials  # norms are legal_info only
    consultant = KnowledgeApi(factory, "consultant")
    legal = consultant.get_claims("norm", "legal_info", RELEASE).claims
    assert len(legal) == 11
    assert all(
        {"jurisdiction", "document", "clause", "effective_from"} <= set(c.scope) for c in legal
    )
