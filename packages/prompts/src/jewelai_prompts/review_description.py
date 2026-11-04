"""Internal deterministic F06 review presentation; never a Product State writer.

Only validated projected facts/constraints enter this layer. Coverage is internal,
not an API field, durable payload, inference engine or new Knowledge catalog.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from jewelai_domain.dictionary import DictionaryLocale, DictionaryRegistry
from jewelai_domain.knowledge_policy import RuntimeProvenance

from .final_prompt import (
    FinalPromptConstraint,
    FinalPromptDesignFact,
    FinalPromptUnresolvedDetail,
    _check_current_text_capacity,
    _classification_label,
)


class UnsupportedReason(StrEnum):
    LABEL = "unsupported_label"
    VALUE = "unsupported_value_type"
    TERM = "untranslated_source_term"
    PRIVATE = "private_or_opaque_value"


@dataclass(frozen=True)
class ReviewCoverage:
    kind: str
    target: str
    owner: str
    status: Literal["rendered", "review_section", "unsupported"]
    reason: UnsupportedReason | None = None
    represented_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewRendering:
    text: str
    coverage: tuple[ReviewCoverage, ...]
    unresolved_summary: tuple[str, ...]


# Presentation labels for existing typed property names, not canonical bindings.
# Unknown names fail visibly with an internal typed reason instead of raw paths.
_LABEL_PAIRS = {
    "jewelry_type": ("Jewelry", "Украшение"),
    "components": ("Components", "Компоненты"),
    "band": ("Band", "Шинка"),
    "side_stones": ("Side stones", "Боковые камни"),
    "engraving": ("Engraving", "Гравировка"),
    "dimension_scope": ("Dimension scope", "Область размеров"),
    "metal": ("Metal", "Металл"),
    "center_stone": ("Center stone", "Центральный камень"),
    "material": ("Material", "Материал"),
    "color": ("Color", "Цвет"),
    "purity": ("Purity", "Проба"),
    "finish": ("Finish", "Отделка"),
    "shape": ("Shape", "Форма"),
    "cut": ("Cut", "Огранка"),
    "weight": ("Weight", "Вес"),
    "dimensions": ("Dimensions", "Размеры"),
    "setting": ("Setting", "Закрепка"),
    "orientation": ("Orientation", "Ориентация"),
    "quantity": ("Quantity", "Количество"),
    "role": ("Role", "Роль"),
    "role_or_location": ("Role or location", "Роль или расположение"),
    "arrangement": ("Arrangement", "Расположение"),
    "location": ("Location", "Расположение"),
    "coverage": ("Coverage", "Покрытие"),
    "total_carat_weight": ("Total weight", "Общий вес"),
    "material_origin_status": ("Material origin", "Происхождение материала"),
    "geographic_origin": ("Geographic origin", "Географическое происхождение"),
    "treatment_status": ("Treatment status", "Статус обработки"),
    "treatments": ("Treatments", "Обработки"),
    "variety_or_type": ("Variety or type", "Разновидность или тип"),
    "cut_style_class": ("Cut style", "Тип огранки"),
    "style": ("Style", "Стиль"),
    "style_descriptors": ("Style descriptors", "Характеристики стиля"),
    "style_influences": ("Style influences", "Влияния стиля"),
    "style_period_or_movement": ("Style period or movement", "Период или направление стиля"),
    "prong_count": ("Prong count", "Количество крапанов"),
    "prong_style": ("Prong style", "Стиль крапанов"),
    "prong_configuration": ("Prong configuration", "Конфигурация крапанов"),
    "halo": ("Halo", "Гало"),
    "pave": ("Pavé", "Паве"),
    "enabled": ("Enabled", "Наличие"),
    "type": ("Type", "Тип"),
    "row_count": ("Row count", "Количество рядов"),
    "outline_relation": ("Outline relation", "Соотношение контуров"),
    "construction": ("Construction", "Конструкция"),
    "shank": ("Shank", "Шинка"),
    "head": ("Head", "Головка"),
    "gallery": ("Gallery", "Галерея"),
    "basket": ("Basket", "Корзина"),
    "clasp": ("Clasp", "Застёжка"),
    "setting_height": ("Setting height", "Высота закрепки"),
    "shank_width": ("Band width", "Ширина шинки"),
    "thickness": ("Thickness", "Толщина"),
    "shoulders": ("Shoulders", "Плечи"),
    "bridge": ("Bridge", "Перемычка"),
    "sizing_area": ("Sizing area", "Зона изменения размера"),
    "shank_configuration": ("Shank configuration", "Конфигурация шинки"),
    "solidity": ("Solidity", "Полнотелость"),
    "ring": ("Ring", "Кольцо"),
    "earring": ("Earring", "Серьга"),
    "pendant": ("Pendant", "Подвеска"),
    "necklace": ("Necklace", "Колье"),
    "bracelet": ("Bracelet", "Браслет"),
    "brooch": ("Brooch", "Брошь"),
    "size": ("Size", "Размер"),
    "size_system": ("Size system", "Система размеров"),
    "inner_diameter_mm": ("Inner diameter", "Внутренний диаметр"),
    "inner_circumference_mm": ("Inner circumference", "Внутренняя окружность"),
    "head_dimensions": ("Head dimensions", "Размеры головки"),
    "overall_dimensions": ("Overall dimensions", "Габаритные размеры"),
    "body_dimensions": ("Body dimensions", "Размеры корпуса"),
    "coating": ("Coating", "Покрытие"),
    "alloy_system": ("Alloy system", "Система сплава"),
    "surface_treatment": ("Surface treatment", "Обработка поверхности"),
    "method": ("Method", "Метод"),
    "color_or_effect": ("Color or effect", "Цвет или эффект"),
    "composition": ("Composition", "Композиция"),
    "symmetry_mode": ("Symmetry", "Симметрия"),
    "organization": ("Organization", "Организация"),
    "focal_hierarchy": ("Focal hierarchy", "Иерархия акцентов"),
    "negative_space_intent": ("Negative space", "Негативное пространство"),
    "rhythm": ("Rhythm", "Ритм"),
    "decorative_elements": ("Decoration", "Декор"),
    "technique": ("Technique", "Техника"),
    "motif": ("Motif", "Мотив"),
    "prominence": ("Prominence", "Выраженность"),
    "product": ("Product", "Изделие"),
    "length": ("Length", "Длина"),
    "width": ("Width", "Ширина"),
    "depth": ("Depth", "Глубина"),
    "diameter": ("Diameter", "Диаметр"),
    "minimum": ("Minimum", "Минимум"),
    "maximum": ("Maximum", "Максимум"),
    "diameter_range_mm": ("Diameter range", "Диапазон диаметров"),
    "references": ("Private references", "Приватные референсы"),
    "visual_constraints": ("Visual requirements", "Визуальные требования"),
}
_PRIVATE = re.compile(
    r"[a-z][a-z0-9+.-]*://|\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b|[{}]", re.I
)
_UNITS = {
    "mm": ("mm", "мм"),
    "cm": ("cm", "см"),
    "ct": ("ct", "карат"),
    "karat": ("karat", "карат"),
    "percent": ("%", "%"),
    "g": ("g", "г"),
}
_SCOPES = {
    "per_side": ("per side", "с каждой стороны"),
    "per_item": ("per item", "на изделие"),
    "per_pair": ("per pair", "на пару"),
}


def render_review_description(
    snapshot,
    facts: tuple[FinalPromptDesignFact, ...],
    constraints: tuple[FinalPromptConstraint, ...],
    unresolved: tuple[FinalPromptUnresolvedDetail, ...],
    *,
    dictionary: DictionaryRegistry,
    pending=(),
) -> ReviewRendering:
    """Render validated canonical projections, without inferring or accepting facts.

    This function is internal presentation, not a contract reader. Its callers
    validate the complete scoped snapshot first. Coverage uses exact target
    identity and typed section membership, never substring matches in prose.
    """
    ru = snapshot.locale == "ru"
    locale = DictionaryLocale(snapshot.locale)
    targets = {f.target for f in facts}
    if len(targets) != len(facts):
        raise ValueError("Readable projection has duplicate authoritative targets")
    owners: dict[str, list[str]] = {}
    for target in sorted(targets):
        p = target.split(".")
        for prefix, count in (
            ("side_stones", 2),
            ("metal.components", 3),
            ("decorative_elements", 2),
        ):
            if target.startswith(prefix + ".") and len(p) > count:
                owners.setdefault(prefix, []).append(p[count - 1])
    owners = {k: sorted(set(v)) for k, v in owners.items()}
    ids = {v for values in owners.values() for v in values}
    ids.update(source for fact in facts for source in fact.source_ids)
    ids.update(source for constraint in constraints for source in constraint.source_ids)

    def safe(text):
        return (
            isinstance(text, str)
            and not _PRIVATE.search(text)
            and not any(i in text for i in ids)
            and not re.search(
                r"\b(?:center_stone|side_stones|metal|construction|composition)\.[a-z_]", text
            )
        )

    def label(key):
        return _LABEL_PAIRS.get(key, (None, None))[ru]

    def owner_and_label(target):
        p = target.split(".")
        for prefix, count, en, russian in (
            ("side_stones", 2, "Side-stone group", "Группа боковых камней"),
            ("metal.components", 3, "Metal component", "Компонент металла"),
            ("decorative_elements", 2, "Decorative element", "Элемент декора"),
        ):
            if target.startswith(prefix + ".") and len(p) > count:
                identifier = p[count - 1]
                if identifier not in owners.get(prefix, ()):
                    return prefix, None
                ordinal = owners[prefix].index(identifier) + 1
                readable = f"{russian if ru else en} {ordinal}"
                role_target = ".".join(p[:count]) + ".role_or_location"
                role_fact = next((f for f in facts if f.target == role_target), None)
                role = role_fact.value if role_fact and role_fact.confirmed else None
                if isinstance(role, str) and role in {"head", "shank", "gallery", "basket"}:
                    readable += " — " + label(role)
                tail = [x for x in p[count:] if x != "stones"]
                labels = [label(x) for x in tail]
                name = readable + ": " + " / ".join(labels) if all(labels) else None
                return ".".join(p[:count]), name
        if target.startswith(("component.", "feature.", "dimensions.")):
            return target, label(p[-1])
        labels = [label(x) for x in p]
        return p[0], " / ".join(labels) if all(labels) else None

    def value_text(value):
        if isinstance(value, bool):
            return (
                ("есть" if value else "нет") if ru else ("present" if value else "absent")
            ), None
        if isinstance(value, (float, int)):
            return str(value), None
        if isinstance(value, str):
            if not safe(value):
                return None, UnsupportedReason.PRIVATE
            try:
                return dictionary[value].canonical_terms.for_locale(locale), None
            except KeyError:
                # Preserve the source term visibly, never invent professional translations.
                return value + (
                    " (термин требует проверки)" if ru else " (term needs review)"
                ), UnsupportedReason.TERM
        if isinstance(value, list):
            parts = [value_text(x) for x in value]
            if any(t is None for t, _ in parts):
                return None, next(r for t, r in parts if t is None)
            return ", ".join(t for t, _ in parts) or ("нет" if ru else "none"), next(
                (r for _, r in parts if r), None
            )
        if not isinstance(value, dict):
            return None, UnsupportedReason.VALUE
        if (
            set(value) >= {"value", "unit"}
            and isinstance(value["unit"], str)
            and value["unit"] in _UNITS
        ):
            text, reason = value_text(value["value"])
            return (
                (f"{text} {_UNITS[value['unit']][ru]}", reason)
                if text is not None
                else (None, reason)
            )
        if (
            set(value) >= {"value", "scope"}
            and isinstance(value["scope"], str)
            and value["scope"] in _SCOPES
        ):
            text, reason = value_text(value["value"])
            return (
                (f"{text} {_SCOPES[value['scope']][ru]}", reason)
                if text is not None
                else (None, reason)
            )
        if "availability" in value:
            if value["availability"] == "value":
                text, reason = value_text(value["value"])
                if text is None:
                    return None, reason
                return (
                    f"{text} [{authority(value['origin'], value['confirmed'], value['locked'])}]",
                    reason,
                )
            if value["availability"] == "not_applicable":
                text = "не применимо" if ru else "not applicable"
                return (
                    f"{text} [{authority('explicit', value['confirmed'], value['locked'])}]",
                    None,
                )
            return ("неизвестно" if ru else "unknown"), None
        pairs = []
        for key, val in sorted(value.items()):
            if val is None:
                continue
            name = label(key)
            if name is None:
                return None, UnsupportedReason.LABEL
            text, reason = value_text(val)
            if text is None:
                return None, reason
            pairs.append((name + ": " + text, reason))
        if not pairs:
            return None, UnsupportedReason.VALUE
        return "; ".join(t for t, _ in pairs), next((r for _, r in pairs if r), None)

    def authority(origin, confirmed, locked, provenance=None):
        if origin == "assumed":
            result = "Предположение" if ru else "Assumption"
        elif origin == "derived":
            accepted = provenance == RuntimeProvenance.USER_ACCEPTED_RECOMMENDATION or (
                provenance is None and confirmed
            )
            result = (
                ("Принятая рекомендация" if ru else "Accepted recommendation")
                if accepted
                else ("Выведенные сведения" if ru else "Derived information")
            )
        else:
            result = (
                ("Подтверждено пользователем" if ru else "User-confirmed")
                if confirmed
                else ("Не подтверждено" if ru else "Unconfirmed")
            )
        if locked:
            result += "; LOCK — зафиксировано" if ru else "; LOCK — locked"
        return result

    lines, coverage = [], []
    collections = {"metal.components": "component_id", "decorative_elements": "element_id"}
    for fact in sorted(facts, key=lambda f: f.target):
        owner, name = owner_and_label(fact.target)
        children = tuple(t for t in sorted(targets) if t.startswith(fact.target + "."))
        # Only known aggregate containers can be represented by their projected
        # children. Arbitrary structured values never disappear on a prefix match.
        if children and fact.target in {*collections, "composition"}:
            if fact.target in collections:
                text = str(len(fact.value))
            else:
                text = "подробности ниже" if ru else "details below"
            lines.append(
                f"{name}: {text} "
                f"[{authority(fact.origin, fact.confirmed, fact.locked, fact.provenance)}]."
            )
            coverage.append(
                ReviewCoverage(
                    "fact", fact.target, owner, "review_section", represented_by=children
                )
            )
            continue
        if fact.target == "references":
            text, reason = str(len(fact.value or ())), None
        elif fact.target == "visual_constraints":
            parts = [x.get("instruction", "") for x in fact.value]
            text, reason = (
                ("; ".join(parts), None)
                if all(safe(p) for p in parts)
                else (None, UnsupportedReason.PRIVATE)
            )
        elif fact.applicability == "not_applicable":
            text, reason = ("не применимо" if ru else "not applicable"), None
        elif (
            fact.target.endswith(".role_or_location")
            and isinstance(fact.value, str)
            and fact.value in {"head", "shank", "gallery", "basket"}
        ):
            text, reason = label(fact.value), None
        else:
            text, reason = value_text(fact.value)
        if name is None:
            reason, text = UnsupportedReason.LABEL, None
        if text is None:
            lines.append(
                "Свойство требует проверки терминологии."
                if ru
                else "A property needs terminology review."
            )
            coverage.append(ReviewCoverage("fact", fact.target, owner, "unsupported", reason))
        else:
            lines.append(
                f"{name}: {text} "
                f"[{authority(fact.origin, fact.confirmed, fact.locked, fact.provenance)}]."
            )
            coverage.append(
                ReviewCoverage(
                    "fact", fact.target, owner, "unsupported" if reason else "rendered", reason
                )
            )
    facts_by_target = {f.target: f for f in facts}
    for constraint in constraints:
        owner, name = owner_and_label(constraint.target)
        fact = facts_by_target.get(constraint.target)
        if fact is not None and (
            (constraint.kind == "requirement" and constraint.value == fact.value)
            or (
                constraint.kind == "prohibition"
                and fact.applicability == "not_applicable"
                and constraint.source_ids == fact.source_ids
            )
        ):
            coverage.append(
                ReviewCoverage(
                    "constraint:" + constraint.kind,
                    constraint.target,
                    owner,
                    "review_section",
                    represented_by=(constraint.target,),
                )
            )
            continue
        locked = constraint.target in facts_by_target and facts_by_target[constraint.target].locked
        if locked and constraint.instruction == "This confirmed locked value must not change.":
            coverage.append(
                ReviewCoverage(
                    "constraint:preservation",
                    constraint.target,
                    owner,
                    "review_section",
                    represented_by=(constraint.target,),
                )
            )
            continue
        instruction = constraint.instruction
        if ru:
            instruction = {
                "Keep the existing authoritative design value unchanged.": (
                    "Сохранить текущее принятое значение без изменений."
                ),
                "Keep the current center stone unchanged.": (
                    "Сохранить текущий центральный камень без изменений."
                ),
                "Keep this current authoritative center-stone field unchanged.": (
                    "Сохранить текущее принятое значение параметра центрального камня."
                ),
            }.get(instruction, instruction)
        if name is None or not safe(instruction):
            lines.append("Ограничение требует проверки." if ru else "A constraint needs review.")
            coverage.append(
                ReviewCoverage(
                    "constraint:" + constraint.kind,
                    constraint.target,
                    owner,
                    "unsupported",
                    UnsupportedReason.LABEL if name is None else UnsupportedReason.PRIVATE,
                )
            )
        else:
            heading = {
                "requirement": ("Requirement", "Требование"),
                "prohibition": ("Prohibition", "Запрет"),
                "preservation": ("KEEP — preserve", "KEEP — сохранить"),
            }[constraint.kind][ru]
            # Scope comes from the validated constraint, never its technical target or ID.
            lines.append(f"{heading} ({name}): {instruction}")
            coverage.append(
                ReviewCoverage(
                    "constraint:" + constraint.kind, constraint.target, owner, "rendered"
                )
            )
    summaries = []
    for detail in unresolved:
        _, name = owner_and_label(detail.target)
        summaries.append(
            (name or ("Сведения" if ru else "Information"))
            + ": "
            + _classification_label(detail.classification, snapshot.locale)
        )
    overlay = getattr(snapshot.enrichment_result, "availability_overlay", None)
    for entry in overlay.entries if overlay else ():
        _, name = owner_and_label(entry.target.concrete_target)
        name = name or ("Сведения" if ru else "Information")
        if entry.availability == "UNKNOWN":
            qualifier = {
                "required": ("information requested", "сведения запрошены"),
                "optional": ("optional information", "необязательные сведения"),
                "undetermined": ("requirement undetermined", "необходимость не определена"),
            }[entry.unknown_requirement][ru]
            summaries.append(name + (": неизвестно" if ru else ": unknown") + f" ({qualifier})")
        elif entry.availability == "NOT_APPLICABLE" and entry.target.concrete_target not in targets:
            reason = entry.not_applicable.reason
            lines.append(
                name
                + (": не применимо" if ru else ": not applicable")
                + ": "
                + (
                    reason
                    if safe(reason)
                    else ("основание требует проверки" if ru else "reason needs review")
                )
            )
    for evidence in snapshot.constraint_evidence:
        if evidence.status == "unresolved":
            wording = evidence.original_wording
            summaries.append(
                (
                    "Непринятая интерпретация исходного текста: "
                    if ru
                    else "Unaccepted source interpretation: "
                )
                + (
                    wording
                    if safe(wording)
                    else ("требуется проверка" if ru else "review required")
                )
            )
    summaries.extend(
        (
            "Требуется подтверждение изменения сохранённого свойства."
            if ru
            else "A preserved-property change needs confirmation."
        )
        for _ in pending
    )
    if summaries:
        lines.append(
            ("Остаётся уточнить: " if ru else "Still open: ")
            + "; ".join(dict.fromkeys(summaries))
            + "."
        )
    text = "\n".join(lines) or (
        "Принятых сведений пока нет." if ru else "No design facts accepted yet."
    )
    _check_current_text_capacity(text)
    if (
        len(coverage) != len(facts) + len(constraints)
        or {c.target for c in coverage if c.kind == "fact"} != targets
    ):
        raise ValueError("Incomplete readable projection coverage")
    if any(t not in targets for c in coverage for t in c.represented_by):
        raise ValueError("Unbacked readable review section")
    return ReviewRendering(text, tuple(coverage), tuple(dict.fromkeys(summaries)))
