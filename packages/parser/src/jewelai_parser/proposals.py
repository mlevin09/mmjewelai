"""Bounded deterministic conversion from untrusted candidate to schema-safe proposal."""

from jewelai_domain.dictionary import (
    AmbiguousMatch,
    DictionaryCategory,
    DictionaryRegistry,
    MatchKind,
    ResolvedMatch,
    UnsupportedMatch,
)
from jewelai_domain.models import (
    Design,
    DesignRevision,
    Dimensions,
    Explicit,
    FinenessPurity,
    KaratPurity,
    KnownValue,
    MessageSource,
    NotApplicable,
    StoneQuantity,
    Weight,
)

from .models import (
    AcceptedUpdate,
    CandidateUpdate,
    DimensionsCandidate,
    ParserCandidate,
    ParserIssue,
    ParserIssueCode,
    ParserProposal,
    ParserTarget,
    ParserWarning,
    ParserWarningCode,
    PurityCandidate,
    QuantityCandidate,
    StyleTermsCandidate,
    TermCandidate,
    WeightCandidate,
)


class StaleParserProposalError(ValueError):
    pass


_CATEGORIES = {
    ParserTarget.JEWELRY_TYPE: DictionaryCategory.JEWELRY_TYPE,
    ParserTarget.METAL_MATERIAL: DictionaryCategory.METAL_MATERIAL,
    ParserTarget.METAL_COLOR: DictionaryCategory.METAL_COLOR,
    ParserTarget.CENTER_STONE_MATERIAL: DictionaryCategory.GEMSTONE_MATERIAL,
    ParserTarget.CENTER_STONE_SHAPE: DictionaryCategory.STONE_SHAPE,
    ParserTarget.CENTER_STONE_CUT: DictionaryCategory.STONE_CUT,
    ParserTarget.CENTER_STONE_SETTING: DictionaryCategory.STONE_SETTING,
    ParserTarget.STYLE: DictionaryCategory.STYLE,
}


def build_parser_proposal(
    revision: DesignRevision,
    *,
    expected_revision_id,
    source: MessageSource,
    locale: str,
    dictionary: DictionaryRegistry,
    candidate: ParserCandidate,
) -> ParserProposal:
    revision = DesignRevision.model_validate(revision)
    candidate = ParserCandidate.model_validate(candidate)
    source = MessageSource.model_validate(source)
    if revision.revision_id != expected_revision_id:
        raise StaleParserProposalError("Stale parser proposal: current revision has changed")
    data = revision.design.model_dump(mode="json")
    accepted: list[AcceptedUpdate] = []
    issues: list[ParserIssue] = []
    warnings: list[ParserWarning] = []
    for update in sorted(candidate.updates, key=lambda item: item.concrete_target):
        current = _current_state(revision.design, update)
        if update.target == ParserTarget.SIDE_STONE_QUANTITY and current is _MISSING:
            issues.append(
                ParserIssue(
                    code=ParserIssueCode.UNKNOWN_SIDE_STONE_GROUP,
                    target=update.target,
                    concrete_target=update.concrete_target,
                    detail="The side-stone group does not exist in the current design.",
                )
            )
            continue
        if isinstance(current, NotApplicable):
            issues.append(
                ParserIssue(
                    code=ParserIssueCode.NOT_APPLICABLE_CONFLICT,
                    target=update.target,
                    concrete_target=update.concrete_target,
                    detail=(
                        "The existing field is explicitly marked not applicable; "
                        "Parser Proposal v1 cannot reinterpret applicability."
                    ),
                )
            )
            continue

        result = _canonicalize(update, locale, dictionary)
        if isinstance(result, ParserIssue):
            issues.append(result)
            continue
        canonical, match_kind, update_warnings = result
        warnings.extend(update_warnings)
        if isinstance(current, KnownValue) and current.value == canonical:
            continue
        if isinstance(current, KnownValue) and current.locked:
            issues.append(
                ParserIssue(
                    code=ParserIssueCode.LOCKED_FIELD_CONFLICT,
                    target=update.target,
                    concrete_target=update.concrete_target,
                    detail="A parser proposal cannot replace a locked field.",
                )
            )
            continue
        state = _explicit_state(update, canonical, source)
        _set_state(data, update, state.model_dump(mode="json"))
        accepted.append(
            AcceptedUpdate(
                target=update.target,
                concrete_target=update.concrete_target,
                candidate_value=update.value,
                canonical_value=canonical,
                match_kind=match_kind,
            )
        )

    accepted.sort(key=lambda item: item.concrete_target)
    issues.sort(key=lambda item: (item.concrete_target, item.code.value))
    warnings.sort(key=lambda item: (item.concrete_target, item.code.value, item.canonical_id))
    proposed = Design.model_validate(data)
    return ParserProposal(
        expected_revision_id=revision.revision_id,
        source=source,
        locale=locale,
        dictionary_artifact_version=dictionary.artifact_version,
        proposed_design=proposed,
        accepted_updates=tuple(accepted),
        issues=tuple(issues),
        warnings=tuple(warnings),
        has_changes=bool(accepted),
    )


_MISSING = object()


def _current_state(design: Design, update: CandidateUpdate):
    if update.target == ParserTarget.JEWELRY_TYPE:
        return design.jewelry_type
    if update.target == ParserTarget.METAL_MATERIAL:
        return design.metal.material
    if update.target == ParserTarget.METAL_COLOR:
        return design.metal.color
    if update.target == ParserTarget.METAL_PURITY:
        return design.metal.purity
    if update.target == ParserTarget.CENTER_STONE_MATERIAL:
        return design.center_stone.material
    if update.target == ParserTarget.CENTER_STONE_SHAPE:
        return design.center_stone.shape
    if update.target == ParserTarget.CENTER_STONE_CUT:
        return design.center_stone.cut
    if update.target == ParserTarget.CENTER_STONE_WEIGHT:
        return design.center_stone.weight
    if update.target == ParserTarget.CENTER_STONE_DIMENSIONS:
        return design.center_stone.dimensions
    if update.target == ParserTarget.CENTER_STONE_SETTING:
        return design.center_stone.setting
    if update.target == ParserTarget.STYLE:
        return design.style
    return next(
        (group.quantity for group in design.side_stones if group.group_id == update.group_id),
        _MISSING,
    )


def _canonicalize(update, locale, dictionary):
    if isinstance(update.value, TermCandidate):
        return _normalize_term(update, update.value.text, locale, dictionary)
    if isinstance(update.value, StyleTermsCandidate):
        values = []
        warnings = []
        match_kinds = []
        for term in update.value.terms:
            result = _normalize_term(update, term, locale, dictionary)
            if isinstance(result, ParserIssue):
                return result
            value, match_kind, found_warnings = result
            values.append(value)
            warnings.extend(found_warnings)
            match_kinds.append(match_kind)
        return tuple(values), _combined_match_kind(match_kinds), warnings
    return update.value.value, None, []


def _normalize_term(update, term, locale, dictionary):
    match = dictionary.normalize(term, locale=locale, category=_CATEGORIES[update.target])
    if isinstance(match, AmbiguousMatch):
        return ParserIssue(
            code=ParserIssueCode.AMBIGUOUS_TERM,
            target=update.target,
            concrete_target=update.concrete_target,
            normalized_input=match.normalized_term,
            candidates=match.candidates,
            detail="The term has multiple valid dictionary meanings in this lookup scope.",
        )
    if isinstance(match, UnsupportedMatch):
        return ParserIssue(
            code=ParserIssueCode.UNSUPPORTED_TERM,
            target=update.target,
            concrete_target=update.concrete_target,
            normalized_input=match.normalized_term,
            detail="The term is unsupported for the target category and locale.",
        )
    if not isinstance(match, ResolvedMatch):
        raise TypeError("Unsupported dictionary match outcome")
    found = match.candidate
    if found.entry_deprecated:
        return ParserIssue(
            code=ParserIssueCode.DEPRECATED_ENTRY,
            target=update.target,
            concrete_target=update.concrete_target,
            normalized_input=match.normalized_term,
            candidates=(found,),
            detail="The matched dictionary entry is deprecated and requires review.",
        )
    warnings = []
    if found.deprecated_input:
        warnings.append(
            ParserWarning(
                code=ParserWarningCode.DEPRECATED_ALIAS_USED,
                target=update.target,
                concrete_target=update.concrete_target,
                normalized_input=match.normalized_term,
                canonical_id=found.domain_id,
            )
        )
    return found.domain_id, found.matched_via, warnings


def _combined_match_kind(values):
    if MatchKind.DEPRECATED_ALIAS in values:
        return MatchKind.DEPRECATED_ALIAS
    if MatchKind.SYNONYM in values:
        return MatchKind.SYNONYM
    return MatchKind.CANONICAL


def _explicit_state(update, value, source):
    common = dict(value=value, source=source, confirmed=False, locked=False)
    if isinstance(update.value, WeightCandidate):
        return Explicit[Weight](**common)
    if isinstance(update.value, DimensionsCandidate):
        return Explicit[Dimensions](**common)
    if isinstance(update.value, PurityCandidate):
        return Explicit[KaratPurity | FinenessPurity](**common)
    if isinstance(update.value, QuantityCandidate):
        return Explicit[StoneQuantity](**common)
    if isinstance(update.value, StyleTermsCandidate):
        return Explicit[tuple[str, ...]](**common)
    return Explicit[str](**common)


def _set_state(data, update, state):
    target = update.target
    if target == ParserTarget.JEWELRY_TYPE:
        data["jewelry_type"] = state
    elif target.value.startswith("metal."):
        data["metal"][target.value.split(".")[1]] = state
    elif target.value.startswith("center_stone."):
        data["center_stone"][target.value.split(".")[1]] = state
    elif target == ParserTarget.STYLE:
        data["style"] = state
    else:
        group = next(item for item in data["side_stones"] if item["group_id"] == update.group_id)
        group["quantity"] = state
