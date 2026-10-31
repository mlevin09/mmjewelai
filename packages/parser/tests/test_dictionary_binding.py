"""F02 uses existing vocabulary; no catalog edits or new binding authority."""

import json
from pathlib import Path

import pytest
from jewelai_domain import compile_knowledge_library, load_domain_dictionary
from jewelai_domain.dictionary import MatchKind
from test_parser import SOURCE, revision

from jewelai_parser import ParserCandidate, build_parser_proposal, parse_full_message
from jewelai_parser.knowledge_matcher import KnowledgeLibraryMatcher

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def dictionary():
    return load_domain_dictionary(ROOT / "data/dictionary/v1.0.0.json")


ALIAS_CASES = (
    ("en", "An emerald shape diamond.", "center_stone.shape", "emerald_cut", "deprecated_alias"),
    ("ru", "Алмаз изумрудной формы.", "center_stone.shape", "emerald_cut", "deprecated_alias"),
    ("ru", "Алмаз изумрудною формою.", "center_stone.shape", "emerald_cut", "deprecated_alias"),
    ("ru", "Кольцо с бриллиантом.", "center_stone.material", "diamond", "synonym"),
    ("ru", "Кольцо с бриллиантами.", "center_stone.material", "diamond", "synonym"),
    ("ru", "Кольцо из розового золота.", "metal.color", "rose", "synonym"),
    ("ru", "Алмаз овальной формы.", "center_stone.shape", "oval", "synonym"),
    ("en", "A rose-gold ring.", "metal.color", "rose", "synonym"),
    ("en", "An oval shape diamond.", "center_stone.shape", "oval", "synonym"),
    ("en", "A step-cut diamond.", "center_stone.cut", "step_cut", "synonym"),
    ("ru", "Овальный алмаз.", "center_stone.shape", "oval", "canonical"),
    ("ru", "Алмаз изумрудной огранки.", "center_stone.shape", "emerald_cut", "canonical"),
)


@pytest.mark.parametrize("locale,text,target,value,kind", ALIAS_CASES)
def test_indexed_surface_preserves_dictionary_match_kind(
    dictionary, locale, text, target, value, kind
):
    parsed = parse_full_message(text, locale=locale, dictionary=dictionary)
    current = revision()
    proposal = build_parser_proposal(
        current,
        expected_revision_id=current.revision_id,
        source=SOURCE,
        locale=locale,
        dictionary=dictionary,
        candidate=ParserCandidate(
            updates=tuple(c.parser_update for c in parsed.candidates if c.parser_update)
        ),
    )
    accepted = next(u for u in proposal.accepted_updates if u.concrete_target == target)
    assert accepted.canonical_value == value
    assert accepted.match_kind == MatchKind(kind)
    warnings = [w for w in proposal.warnings if w.concrete_target == target]
    assert bool(warnings) is (kind == "deprecated_alias")
    if warnings:
        assert warnings[0].code == "DEPRECATED_ALIAS_USED"
        assert warnings[0].canonical_id == value
    candidate = next(c for c in parsed.candidates if c.target == target)
    assert candidate.normalization_source == "domain_dictionary"
    assert candidate.normalized_values == (value,)
    assert text[candidate.evidence.start : candidate.evidence.end] == candidate.evidence.text
    assert proposal.source == SOURCE
    assert proposal.dictionary_artifact_version == dictionary.artifact_version


@pytest.mark.parametrize(
    "text", ("No rose-gold ring.", "Без бриллиантов.", "Не нужна изумрудная форма.")
)
def test_alias_normalization_does_not_restore_rejected_positive(dictionary, text):
    parsed = parse_full_message(
        text, locale="ru" if "ring" not in text else "en", dictionary=dictionary
    )
    assert all(c.parser_update is None for c in parsed.candidates)


@pytest.mark.parametrize(
    "locale,text",
    (
        ("en", "A gold ring with an oval diamond."),
        ("ru", "Кольцо из белого золота с овальным алмазом."),
        ("ru", "White gold ring. Центральный овальный алмаз."),
    ),
)
def test_real_catalog_overlap_retains_independent_authorities(dictionary, locale, text):
    # Read-only compilation of existing REVIEWED input, never ACTIVE promotion.
    payload = json.loads((ROOT / "data/knowledge/v1/jewelry-core-1.0.0.json").read_text())
    runtime, _ = compile_knowledge_library(payload)
    plain = parse_full_message(text, locale=locale, dictionary=dictionary)
    combined = parse_full_message(
        text, locale=locale, dictionary=dictionary, knowledge_runtime=runtime
    )

    def dictionary_candidates(parsed):
        return [
            c.model_dump(exclude={"candidate_id"})
            for c in parsed.candidates
            if c.normalization_source == "domain_dictionary"
        ]

    assert dictionary_candidates(plain) == dictionary_candidates(combined)
    knowledge = [c for c in combined.candidates if c.normalization_source == "knowledge_library"]
    assert knowledge and all(c.parser_update is None for c in knowledge)
    matcher = KnowledgeLibraryMatcher(runtime)
    for c in knowledge:
        matches = [matcher.match(c.evidence.text, locale=language) for language in ("en", "ru")]
        assert any(
            m.outcome == "resolved" and m.candidate.concept_id in c.normalized_values
            for m in matches
        )
    assert combined.knowledge_runtime_sha256 == runtime.sha256
    assert combined.knowledge_package_id == payload["package_id"]


def test_real_content_and_conditional_review_status_are_not_invented(dictionary):
    assert all(
        e.provenance.review_status == "proposed_pending_domain_review" for e in dictionary.values()
    )
    assert dictionary["oval"].synonyms.en == ("oval shape",)
    assert dictionary["emerald_cut"].deprecated_aliases[1].term == "изумрудная форма"
    assert dictionary.normalize("halo", locale="en").outcome == "ambiguous"
    assert dictionary.normalize("palladium", locale="en").outcome == "unsupported"
    core = json.loads((ROOT / "data/knowledge/v1/jewelry-core-1.0.0.json").read_text())
    assert any(c["concept_id"] == "palladium" for c in core["domain_knowledge"])
    # F02-14 requires absence from BOTH checked vocabularies. Palladium is
    # Knowledge-only, whereas ruthenium has no entry in the supplied artifacts.
    assert dictionary.normalize("ruthenium", locale="en").outcome == "unsupported"
    assert "ruthenium" not in json.dumps(core).casefold()
