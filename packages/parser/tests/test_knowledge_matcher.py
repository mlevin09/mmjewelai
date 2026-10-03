from jewelai_domain.knowledge_library import (
    CompiledKnowledgeLibrary,
    CompiledLanguageMapping,
    MappingMode,
    MappingQuality,
)

from jewelai_parser.knowledge_matcher import (
    AmbiguousKnowledgeMatch,
    KnowledgeLibraryMatcher,
    KnowledgeMatchMethod,
    ResolvedKnowledgeMatch,
    UnsupportedKnowledgeMatch,
    normalize_knowledge_text,
    ru_morphology_key,
)


def runtime():
    return CompiledKnowledgeLibrary(
        package_id="jewelai.test.matcher",
        artifact_version="1.0.0",
        sources=(),
        claims=(),
        domain_knowledge=(),
        policies=(),
        language_mappings=(
            CompiledLanguageMapping(
                mapping_id="LANG-EN-OVAL",
                concept_id="stone.shape.oval",
                locale="en",
                canonical_term="oval",
                aliases=("oval shape",),
                mapping_mode=MappingMode.DIRECT,
                mapping_quality=MappingQuality.EXACT,
                context=None,
            ),
            CompiledLanguageMapping(
                mapping_id="LANG-RU-OVAL",
                concept_id="stone.shape.oval",
                locale="ru",
                canonical_term="овал",
                aliases=("овальная",),
                mapping_mode=MappingMode.DIRECT,
                mapping_quality=MappingQuality.PREFERRED,
                context=None,
            ),
            CompiledLanguageMapping(
                mapping_id="LANG-RU-PRONG",
                concept_id="setting.prong",
                locale="ru",
                canonical_term="крапановая закрепка",
                aliases=("крапановый",),
                mapping_mode=MappingMode.DIRECT,
                mapping_quality=MappingQuality.PREFERRED,
                context=None,
            ),
            CompiledLanguageMapping(
                mapping_id="LANG-RU-BEZEL",
                concept_id="setting.bezel",
                locale="ru",
                canonical_term="глухая закрепка",
                aliases=(),
                mapping_mode=MappingMode.CONTEXTUAL,
                mapping_quality=MappingQuality.CONTEXT_DEPENDENT,
                context="stone_setting",
            ),
            CompiledLanguageMapping(
                mapping_id="LANG-RU-SOLITAIRE",
                concept_id="style.solitaire",
                locale="ru",
                canonical_term="солитер",
                aliases=(),
                mapping_mode=MappingMode.INPUT_ONLY,
                mapping_quality=MappingQuality.APPROXIMATE,
                context=None,
            ),
            CompiledLanguageMapping(
                mapping_id="LANG-RU-RED",
                concept_id="metal.color.red",
                locale="ru",
                canonical_term="красное золото",
                aliases=(),
                mapping_mode=MappingMode.AMBIGUOUS,
                mapping_quality=MappingQuality.CONTEXT_DEPENDENT,
                context=None,
            ),
            CompiledLanguageMapping(
                mapping_id="LANG-RU-ROSE",
                concept_id="metal.color.rose",
                locale="ru",
                canonical_term="красное золото",
                aliases=(),
                mapping_mode=MappingMode.AMBIGUOUS,
                mapping_quality=MappingQuality.CONTEXT_DEPENDENT,
                context=None,
            ),
        ),
    )


def test_normalization_and_ru_morphology_are_deterministic():
    assert normalize_knowledge_text("  ОВАЛЬНАЯ   ") == "овальная"
    assert ru_morphology_key("крапановой закрепки") == ru_morphology_key("крапановая закрепка")


def test_exact_direct_match_resolves():
    result = KnowledgeLibraryMatcher(runtime()).match(" OVAL ", locale="en-US")
    assert isinstance(result, ResolvedKnowledgeMatch)
    assert result.candidate.concept_id == "stone.shape.oval"
    assert result.candidate.match_method == KnowledgeMatchMethod.EXACT


def test_ru_inflection_resolves_without_fuzzy_matching():
    result = KnowledgeLibraryMatcher(runtime()).match(
        "крапановой закрепки",
        locale="ru-RU",
    )
    assert isinstance(result, ResolvedKnowledgeMatch)
    assert result.candidate.concept_id == "setting.prong"
    assert result.candidate.match_method == KnowledgeMatchMethod.RU_MORPHOLOGY


def test_contextual_mapping_requires_matching_context():
    matcher = KnowledgeLibraryMatcher(runtime())

    unresolved = matcher.match("глухая закрепка", locale="ru")
    assert isinstance(unresolved, AmbiguousKnowledgeMatch)
    assert unresolved.reason == "context_required"

    resolved = matcher.match(
        "глухая закрепка",
        locale="ru",
        context="stone_setting",
    )
    assert isinstance(resolved, ResolvedKnowledgeMatch)
    assert resolved.candidate.concept_id == "setting.bezel"


def test_declared_ambiguity_is_preserved():
    result = KnowledgeLibraryMatcher(runtime()).match("красное золото", locale="ru")
    assert isinstance(result, AmbiguousKnowledgeMatch)
    assert result.reason == "declared_ambiguous"
    assert {item.concept_id for item in result.candidates} == {
        "metal.color.red",
        "metal.color.rose",
    }


def test_input_only_is_matchable_for_user_input():
    result = KnowledgeLibraryMatcher(runtime()).match("солитер", locale="ru")
    assert isinstance(result, ResolvedKnowledgeMatch)
    assert result.candidate.mapping_mode == MappingMode.INPUT_ONLY


def test_scope_can_resolve_or_reject_candidate():
    matcher = KnowledgeLibraryMatcher(runtime())
    resolved = matcher.match(
        "oval",
        locale="en",
        allowed_concept_ids={"stone.shape.oval"},
    )
    assert isinstance(resolved, ResolvedKnowledgeMatch)

    unsupported = matcher.match(
        "oval",
        locale="en",
        allowed_concept_ids={"stone.shape.round"},
    )
    assert isinstance(unsupported, UnsupportedKnowledgeMatch)
    assert unsupported.reason == "scope_no_match"


def test_unsupported_locale_and_unknown_term_fail_closed():
    matcher = KnowledgeLibraryMatcher(runtime())

    locale = matcher.match("oval", locale="de")
    assert isinstance(locale, UnsupportedKnowledgeMatch)
    assert locale.reason == "unsupported_locale"

    term = matcher.match("round brilliant", locale="en")
    assert isinstance(term, UnsupportedKnowledgeMatch)
    assert term.reason == "term_not_found"


def test_exact_match_has_priority_over_ru_morphology():
    result = KnowledgeLibraryMatcher(runtime()).match("овальная", locale="ru")
    assert isinstance(result, ResolvedKnowledgeMatch)
    assert result.candidate.match_method == KnowledgeMatchMethod.EXACT
