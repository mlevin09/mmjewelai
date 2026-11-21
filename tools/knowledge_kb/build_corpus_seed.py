"""Build the full Knowledge Library 2.0 corpus seed from v1.6.2 (ADR 0048, v1.2 phase D).

Every one of the 17 682 v1.6.2 K-IDs is mapped. Pilot-slice records reuse the pilot rules.
Remaining VERIFIED records get typed values and the source value of their reference table
(GIA constants and care guides, GOST 30649-99, pure-metal densities, recorded reviews of
normative texts); the loader re-qualifies them by profile. All other records keep their text
as REFERENCE ONLY (or REJECTED) claims, grouped by normalized subject so identical rows merge.

Usage:
  python tools/knowledge_kb/build_corpus_seed.py --xlsx v162.xlsx \\
    --out data/knowledge-kb/corpus-v1.6.2.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_pilot_seed as pilot  # noqa: E402
from jewelai_domain.kb_contract import normalize_term  # noqa: E402

REGISTRY = "Реестр источников"
TIER = {"A": "Q1", "B": "Q2", "C": "Q3"}

# Curated gem entities: (regex on normalized subject, entity_id, parent, ru, en)
GEMS = [
    (r"^(алмаз|бриллиант|diamond)", "gem.diamond", None, None, None),
    (r"^рубин$", "gem.corundum.ruby", None, None, None),
    (r"^сапфир$", "gem.corundum.sapphire", None, None, None),
    (r"^корунд$", "gem.corundum", None, None, None),
    (r"^изумруд", "gem.beryl.emerald", "gem.beryl", "Изумруд", "Emerald"),
    (r"^аквамарин", "gem.beryl.aquamarine", "gem.beryl", "Аквамарин", "Aquamarine"),
    (r"^морганит", "gem.beryl.morganite", "gem.beryl", "Морганит", "Morganite"),
    (r"^берилл", "gem.beryl", "gem", "Берилл", "Beryl"),
    (
        r"^александрит",
        "gem.chrysoberyl.alexandrite",
        "gem.chrysoberyl",
        "Александрит",
        "Alexandrite",
    ),
    (r"^шпинель", "gem.spinel", "gem", "Шпинель", "Spinel"),
    (r"^танзанит", "gem.zoisite.tanzanite", "gem.zoisite", "Танзанит", "Tanzanite"),
    (r"^топаз", "gem.topaz", "gem", "Топаз", "Topaz"),
    (r"^турмалин", "gem.tourmaline", "gem", "Турмалин", "Tourmaline"),
    (r"^перидот", "gem.peridot", "gem", "Перидот", "Peridot"),
    (r"^опал", "gem.opal", "gem", "Опал", "Opal"),
    (r"^гранат", "gem.garnet", "gem", "Гранат (группа)", "Garnet group"),
    (r"^(кварц|аметист|amethyst)", "gem.quartz.amethyst", "gem.quartz", "Аметист", "Amethyst"),
    (r"^цитрин", "gem.quartz.citrine", "gem.quartz", "Цитрин", "Citrine"),
    (r"^moissanite|^муассанит", "gem.moissanite", "gem", "Муассанит", "Moissanite"),
    (r"^коралл", "gem.organic.coral", "gem.organic", "Коралл", "Coral"),
    (r"^жадеит|^нефрит / жадеит", "gem.jade", "gem", "Нефрит / жадеит", "Jade"),
    (r"^циркон", "gem.zircon", "gem", "Циркон", "Zircon"),
    (r"^бирюза", "gem.turquoise", "gem", "Бирюза", "Turquoise"),
    (r"^лунный камень", "gem.feldspar.moonstone", "gem.feldspar", "Лунный камень", "Moonstone"),
    (r"^жемчуг", "gem.organic.pearl", "gem.organic", "Жемчуг", "Pearl"),
    (
        r"^(янтарь|гагат|перламутр|слоновая кость|кость|панцирь черепахи|раковина)",
        "gem.organic",
        "gem",
        "Органические материалы",
        "Organic gem materials",
    ),
    (r"^(лазурит)", "gem.lapis_lazuli", "gem", "Лазурит", "Lapis lazuli"),
    (r"^(малахит)", "gem.malachite", "gem", "Малахит", "Malachite"),
]
EXTRA_PARENTS = [
    ("gem.beryl", "mineral", "gem", "Берилл", "Beryl"),
    ("gem.chrysoberyl", "mineral", "gem", "Хризоберилл", "Chrysoberyl"),
    ("gem.zoisite", "mineral", "gem", "Цоизит", "Zoisite"),
    ("gem.quartz", "mineral", "gem", "Кварц", "Quartz"),
    ("gem.feldspar", "mineral", "gem", "Полевой шпат", "Feldspar"),
    ("gem.organic", "category", "gem", "Органические материалы", "Organic gem materials"),
    ("norm", "category", None, "Нормативные справки", "Normative references"),
    ("legacy", "category", None, "Справочные записи v1.6.2", "v1.6.2 reference records"),
]

# Source values exactly as recorded in the v1.6.2 evidence fragments (EV-GIA-*, EV-GG-MOISS).
# A nominal value with a stated uncertainty is the nominal value; ranges stay ranges.
GEM_SOURCE = {
    "gem.diamond": {
        "RI": ("2.42", "EV-GIA-DIA"),
        "SG": ("3.52", "EV-GIA-DIA"),
        "H": ("10", "EV-GIA-DIA"),
    },
    "gem.corundum.ruby": {
        "RI": ("1.762-1.770", "EV-GIA-RUBY"),
        "SG": ("4.00", "EV-GIA-RUBY"),
        "H": ("9", "EV-GIA-RUBY"),
    },
    "gem.corundum.sapphire": {
        "RI": ("1.762-1.770", "EV-GIA-SAPH"),
        "SG": ("4.00", "EV-GIA-SAPH"),
        "H": ("9", "EV-GIA-SAPH"),
    },
    "gem.beryl.emerald": {
        "RI": ("1.577-1.583", "EV-GIA-EMER"),
        "SG": ("2.72", "EV-GIA-EMER"),
        "H": ("7.5-8", "EV-GIA-EMER"),
    },
    "gem.beryl.aquamarine": {
        "RI": ("1.577-1.583", "EV-GIA-AQUA"),
        "SG": ("2.72", "EV-GIA-AQUA"),
        "H": ("7.5-8.0", "EV-GIA-AQUA"),
    },
    "gem.beryl.morganite": {
        "RI": ("1.583-1.590", "EV-GIA-MORG"),
        "SG": ("2.80-2.91", "EV-GIA-MORG"),
        "H": ("7.5-8", "EV-GIA-MORG"),
    },
    "gem.chrysoberyl.alexandrite": {
        "RI": ("1.746-1.755", "EV-GIA-ALEX"),
        "SG": ("3.73", "EV-GIA-ALEX"),
        "H": ("8.5", "EV-GIA-ALEX"),
    },
    "gem.spinel": {
        "RI": ("1.718", "EV-GIA-SPIN"),
        "SG": ("3.60", "EV-GIA-SPIN"),
        "H": ("8", "EV-GIA-SPIN"),
    },
    "gem.zoisite.tanzanite": {
        "RI": ("1.691-1.700", "EV-GIA-TANZ"),
        "SG": ("3.35", "EV-GIA-TANZ"),
        "H": ("6-7", "EV-GIA-TANZ"),
    },
    "gem.topaz": {
        "RI": ("1.619-1.627", "EV-GIA-TOPAZ"),
        "SG": ("3.53", "EV-GIA-TOPAZ"),
        "H": ("8", "EV-GIA-TOPAZ"),
    },
    "gem.tourmaline": {
        "RI": ("1.624-1.644", "EV-GIA-TOUR"),
        "SG": ("3.06", "EV-GIA-TOUR"),
        "H": ("7-7.5", "EV-GIA-TOUR"),
    },
    "gem.peridot": {
        "RI": ("1.65-1.69", "EV-GIA-PERI"),
        "SG": ("3.34", "EV-GIA-PERI"),
        "H": ("6.5-7", "EV-GIA-PERI"),
    },
    "gem.opal": {
        "RI": ("1.37-1.47", "EV-GIA-OPAL"),
        "SG": ("2.15", "EV-GIA-OPAL"),
        "H": ("5-6.5", "EV-GIA-OPAL"),
    },
    "gem.garnet": {
        "RI": ("1.714-1.888", "EV-GIA-GARN"),
        "SG": ("3.47-4.15", "EV-GIA-GARN"),
        "H": ("6.5-7.5", "EV-GIA-GARN"),
    },
    "gem.quartz.amethyst": {
        "RI": ("1.544-1.553", "EV-GIA-AMET"),
        "SG": ("2.66", "EV-GIA-AMET"),
        "H": ("7", "EV-GIA-AMET"),
    },
    "gem.moissanite": {
        "RI": ("2.648-2.691", "EV-GG-MOISS"),
        "SG": ("3.22", "EV-GG-MOISS"),
        "H": ("9.25", "EV-GG-MOISS"),
        "DISP": ("0.104", "EV-GG-MOISS"),
    },
    "gem.organic.coral": {"H": ("3-4", "EV-GIA-CORAL")},
    "gem.jade": {"H": ("6.5-7", "EV-GIA-CARE-JADE")},
}
# Subjects that v1.6.2 used for diamond facts in context (colour, origin, rendering).
DIAMOND_CONTEXT = (
    r"^(diamond|природный|синтетика|cvd\)?|hpht|diamond \(hpht|blue|brown|green|grey|orange|"
    r"pink|red|violet|yellow|pbr-параметры.*|физика дисперсии.*)$"
)
GEM_PARAM = {
    "Показатель преломления (RI)": ("RI", "refractive_index"),
    "Удельный вес / плотность (SG)": ("SG", "specific_gravity"),
    "Твёрдость (Моос)": ("H", "mohs_hardness"),
    "Дисперсия": ("DISP", "dispersion"),
}
# GIA care guidance (class, evidence) per gem and method.
CARE_SOURCE = {
    "gem.corundum.ruby": ("SAFE_COND", "EV-GIA-CARE-RUBY"),
    "gem.corundum.sapphire": ("SAFE_COND", "EV-GIA-CARE-RUBY"),
    "gem.corundum": ("SAFE_COND", "EV-GIA-CARE-RUBY"),
    "gem.beryl.emerald": ("AVOID", "EV-GIA-CARE-EMER"),
    "gem.beryl.aquamarine": ("SAFE_COND", "EV-GIA-CARE-AQUA"),
    "gem.beryl": ("SAFE_COND", "EV-GIA-CARE-AQUA"),
    "gem.chrysoberyl.alexandrite": ("SAFE", "EV-GIA-CARE-ALEX"),
    "gem.spinel": ("SAFE_COND", "EV-GIA-CARE-SPIN"),
    "gem.zoisite.tanzanite": ("AVOID", "EV-GIA-CARE-TANZ"),
    "gem.topaz": ("AVOID", "EV-GIA-CARE-TOPAZ"),
    "gem.tourmaline": ("AVOID", "EV-GIA-CARE-TOUR"),
    "gem.zircon": ("AVOID", "EV-GIA-CARE-ZIRC"),
    "gem.peridot": ("AVOID", "EV-GIA-CARE-PERI"),
    "gem.turquoise": ("AVOID", "EV-GIA-CARE-TURQ"),
    "gem.feldspar.moonstone": ("AVOID", "EV-GIA-CARE-MOON"),
    "gem.organic.pearl": ("AVOID", "EV-GIA-PEARL"),
    "gem.organic.coral": ("AVOID", "EV-GIA-CORAL"),
    "gem.jade": ("SAFE_COND", "EV-GIA-CARE-JADE"),
}
CARE_SOURCE_BY_METHOD = {  # exceptions where steam differs from ultrasonic
    ("gem.garnet", "care_ultrasonic"): ("SAFE_COND", "EV-GIA-CARE-GARN"),
    ("gem.garnet", "care_steam"): ("AVOID", "EV-GIA-CARE-GARN"),
    ("gem.quartz.amethyst", "care_ultrasonic"): ("SAFE_COND", "EV-GIA-CARE-QTZ"),
    ("gem.quartz.amethyst", "care_steam"): ("AVOID", "EV-GIA-CARE-QTZ"),
    ("gem.quartz.citrine", "care_ultrasonic"): ("SAFE_COND", "EV-GIA-CARE-QTZ"),
    ("gem.quartz.citrine", "care_steam"): ("AVOID", "EV-GIA-CARE-QTZ"),
    ("gem.organic", "care_ultrasonic"): ("AVOID", "EV-GIA-US-ORG"),
    ("gem.opal", "care_ultrasonic"): ("AVOID", "EV-GIA-TIPS"),
    ("gem.lapis_lazuli", "care_ultrasonic"): ("AVOID", "EV-GIA-TIPS"),
    ("gem.malachite", "care_ultrasonic"): ("AVOID", "EV-GIA-TIPS"),
}
CARE_ENUM = {"SAFE": "usually_safe", "SAFE_COND": "usually_safe", "AVOID": "not_recommended"}
PLEO_SOURCE = {"K-01053": "none", "K-17629": "strong", "K-00927": "strong"}
GOST = {
    "ЗлСрМ 375-20": "11.24",
    "ЗлСрМ 375-100": "11.41",
    "ЗлСрМ 375-160": "11.54",
    "ЗлСрМ 375-250": "11.74",
    "ЗлСрПдМ 375-100-38": "11.56",
    "ЗлСрМ 500-100": "12.47",
    "ЗлСр 585-415": "14.30",
    "ЗлСрМ 585-80": "13.24",
    "ЗлСрМ 585-200": "13.60",
    "ЗлСрМ 585-300": "13.92",
    "ЗлСрПд 585-255-160": "14.76",
    "ЗлСрПдЦ 585-287-100": "14.31",
    "ЗлСрПдКд 585-280-100": "14.60",
    "ЗлСрНЦМ 585-80-8,2-2,5": "13.11",
    "ЗлНЦМ 585-12,5-4": "12.85",
    "ЗлСр 750-250": "15.96",
    "ЗлСрМ 750-125": "15.45",
    "ЗлСрМ 750-150": "15.53",
    "ЗлСрНЦ 750-150-7,5": "15.38",
    "ЗлСрПд 750-100-150": "16.44",
    "ЗлСрПлМ 750-80-90": "16.78",
    "ЗлСрПдН 750-90-140": "16.32",
    "ЗлСрПдН 750-70-140": "16.25",
    "ЗлСрПдНКд 750-90-85-4": "15.80",
    "ЗлНЦМ 750-7,5-2,5": "14.81",
    "ЗлСрМ 958-20": "18.52",
    "Зл 999,9": "19.30",
    "СрМ 800": "10.13",
    "СрМ 830": "10.19",
    "СрМ 875": "10.28",
    "СрМ 925": "10.36",
    "СрМ 960": "10.43",
    "ПлИ 850-150": "21.59",
    "ПлПд 850-150": "19.25",
    "ПлРд 850-150": "19.90",
    "ПлМ 850": "17.79",
    "ПлИ 900-100": "21.54",
    "ПдСрН 500-450": "11.16",
    "ПдСрН 850-130": "11.83",
    "ПдМ 850": "11.54",
}
PURE = {
    "au 999": ("metal.gold.999", "19.32"),
    "зл 999": ("metal.gold.999", "19.32"),
    "ср 999": ("metal.silver.999", "10.49"),
}
# Normative statements: scope recorded from the reviewed source fragments (v1.4-C CHK-CANON).
LEGAL_SCOPE = {
    "K-17663": ("EAEU", "ТР ТС 017/2011", "ст. 1", "2012-07-01"),
    "K-17665": ("RU", "ПП РФ от 30.05.2026 № 657", "п. 51", "2026-09-01"),
    "K-17666": ("RU", "ГОСТ 1770-74", "п. 1 (область применения)", "1976-01-01"),
    "K-17667": ("RU", "ПП РФ от 30.05.2026 № 657", "п. 50", "2026-09-01"),
    "K-17668": ("RU", "ПП РФ от 30.05.2026 № 657", "вводная часть", "2026-09-01"),
    "K-17669": ("RU", "ПП РФ от 30.05.2026 № 657", "п. 50", "2026-09-01"),
    "K-17670": ("RU", "ПП РФ от 30.05.2026 № 657", "п. 49", "2026-09-01"),
    "K-17673": ("EU", "REACH, Annex XVII, entry 27", "1(a)–1(c)", "2009-06-01"),
    "K-17674": ("US", "16 CFR Part 23", "§23.0(d), §23.12", "2018-08-16"),
    "K-17676": ("INT", "ISO/TR 11211; ISO 24016:2020; ISO 8653:2016", "scope", "2016-01-01"),
    "K-17681": ("US", "CPSIA / 16 CFR 1500.87", "lead content limit", "2011-08-14"),
}
LEGAL_EFFECTIVE_TO = {
    "K-17665": "2032-09-01",
    "K-17667": "2032-09-01",
    "K-17668": "2032-09-01",
    "K-17669": "2032-09-01",
    "K-17670": "2032-09-01",
}


def norm(text) -> str:
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = re.sub(r"\[[^\]]*\]", "", text)
    return " ".join(text.casefold().split())


def nums(text):
    found = re.findall(r"\d+(?:[.,]\d+)?", str(text or ""))
    return [x.replace(",", ".") for x in found]


def gem_entity(subject: str) -> str | None:
    key = norm(subject)
    for pattern, entity, *_ in GEMS:
        if re.match(pattern, key):
            return entity
    return None


def value_of(text, attribute):
    """First number or range in a v1.6.2 value; a stated ± uncertainty is not a range."""
    cleaned = re.sub(r"[±]\s*\d+(?:[.,]\d+)?", " ", str(text or ""))
    cleaned = re.sub(r"\([^)]*\)", " ", cleaned)
    match = re.search(r"(\d+(?:[.,]\d+)?)(?:\s*[–—-]\s*(\d+(?:[.,]\d+)?))?", cleaned)
    if not match:
        return None
    low = match.group(1).replace(",", ".")
    high = (match.group(2) or "").replace(",", ".")
    if high and float(high) >= float(low):
        return {"min": low, "max": high}
    if attribute == "refractive_index":
        return {"min": low, "max": low}
    return {"num": low}


def source_of(text: str, attribute: str) -> dict:
    if "-" in text:
        low, high = text.split("-")
        return {"min": low, "max": high}
    if attribute == "refractive_index":  # RI is stored as a range attribute
        return {"min": text, "max": text}
    return {"num": text}


def care_class(text) -> str | None:
    s = str(text or "").lower()
    if re.search(r"❌|избегать|никогда|не рекоменд|не использовать|нельзя", s):
        return "not_recommended"
    if "/" in s and re.search(r"безопас|хорошо|✅", s) and re.search(r"риск|⚠", s):
        return "mixed"
    if re.search(r"⚠|риск|осторож", s):
        return "caution"
    if re.search(r"✅|безопас|хорошо|можно|допуст", s):
        return "usually_safe"
    return None


def build(xlsx: Path) -> dict:
    base = pilot.build(xlsx)
    workbook = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    rows = [list(r) for r in workbook[pilot.SHEET].iter_rows(values_only=True)][1:]
    rows = [r + [None] * (31 - len(r)) for r in rows if r and r[0]]
    registry = [list(r) for r in workbook[REGISTRY].iter_rows(values_only=True)][1:]
    col = pilot.COL
    handled = {k for claim in base["claims"] for k, _, _ in claim["legacy"]}
    claims = list(base["claims"])
    entities = {e["entity_id"]: e for e in base["entities"]}
    for eid, etype, parent, ru, en in EXTRA_PARENTS:
        entities.setdefault(
            eid,
            {
                "entity_id": eid,
                "entity_type": etype,
                "parent_id": parent,
                "label_ru": ru,
                "label_en": en,
            },
        )
    for _, eid, parent, ru, en in GEMS:
        if eid not in entities:
            entities[eid] = {
                "entity_id": eid,
                "entity_type": "gem",
                "parent_id": parent or "gem",
                "label_ru": ru,
                "label_en": en,
            }
    for eid, ru, en, parent in (
        ("metal.gold.999", "Золото 999", "Fine gold 999", "metal.gold"),
        ("metal.silver.999", "Серебро 999", "Fine silver 999", "metal.silver"),
    ):
        entities.setdefault(
            eid,
            {
                "entity_id": eid,
                "entity_type": "fineness",
                "parent_id": parent,
                "label_ru": ru,
                "label_en": en,
            },
        )
    attributes = {a["attribute_id"]: a for a in base["attributes"]}
    for attribute in (
        {
            "attribute_id": "dispersion",
            "value_type": "number",
            "unit": None,
            "scale": None,
            "validation_profile_id": "gem_dispersion_exact",
        },
        {
            "attribute_id": "pleochroism",
            "value_type": "enum",
            "unit": None,
            "scale": None,
            "validation_profile_id": "pleochroism_statement",
        },
        {
            "attribute_id": "normative_statement",
            "value_type": "text",
            "unit": None,
            "scale": None,
            "validation_profile_id": "normative_review",
        },
        {
            "attribute_id": "pure_metal_density",
            "value_type": "number",
            "unit": "g/cm3",
            "scale": None,
            "validation_profile_id": "pure_metal_density",
        },
    ):
        attributes[attribute["attribute_id"]] = attribute
    profiles = {p["profile_id"]: p for p in base["validation_profiles"]}
    for profile in (
        {
            "profile_id": "gem_dispersion_exact",
            "method": "exact_number",
            "params": {"precision": 3},
        },
        {"profile_id": "pleochroism_statement", "method": "enum_match", "params": {}},
        {"profile_id": "normative_review", "method": "recorded_review", "params": {}},
        {
            "profile_id": "pure_metal_density",
            "method": "exact_number",
            "params": {"precision": "claim"},
        },
    ):
        profiles[profile["profile_id"]] = profile
    evidence = {e["ev_id"]: e for e in base["evidence"]}
    for r in registry:
        if not r or not r[0] or not str(r[0]).startswith("EV-") or r[0] in evidence:
            continue
        evidence[r[0]] = {
            "ev_id": r[0],
            "org": str(r[1] or "—"),
            "title": str(r[2] or r[0]),
            "url": r[3],
            "tier": TIER.get(str(r[8] or "").strip()[:1], "Q4"),
            "fragment": str(r[6] or "—"),
            "limitations": None if r[9] is None else str(r[9]),
            "retrieved_at": "2026-11-20",
        }

    def ev_ids(text):
        return [e for e in re.findall(r"EV-[A-Z0-9-]+", str(text or "")) if e in evidence]

    def add_entity(entity_id, label):
        if entity_id not in entities:
            entities[entity_id] = {
                "entity_id": entity_id,
                "entity_type": "legacy_subject",
                "parent_id": "legacy",
                "label_ru": label,
                "label_en": None,
            }

    def legacy_entity(subject) -> str:
        curated = gem_entity(subject) if subject else None
        if curated:
            return curated
        key = norm(subject) or "(без темы)"
        entity_id = "legacy." + hashlib.sha256(key.encode()).hexdigest()[:12]
        add_entity(entity_id, str(subject or "(без темы)")[:300])
        return entity_id

    def claim(k, mapping, explanation, **fields):
        claims.append({"legacy": [[k, mapping, explanation]], **fields})
        handled.add(k)

    by_param = {"Ультразвук": "care_ultrasonic", "Пар": "care_steam"}
    for r in rows:
        k = r[col["k"]]
        if k in handled or r[col["status"]] != "VERIFIED":
            continue
        subject, parameter, value = r[col["entity"]], str(r[col["parameter"]]), r[col["value"]]
        code, check = r[col["permission"]], r[col["check"]]
        entity = gem_entity(subject)
        if check == "CHK-GEM" and entity is None and re.match(DIAMOND_CONTEXT, norm(subject)):
            entity = "gem.diamond"
        if check in ("CHK-GEM",) and entity in GEM_SOURCE and parameter in GEM_PARAM:
            key, attribute = GEM_PARAM[parameter]
            if key in GEM_SOURCE[entity]:
                stated, ev = GEM_SOURCE[entity][key]
                typed = value_of(value, attribute)
                if typed is not None:
                    claim(
                        k,
                        "one_to_one",
                        "gem constant (GIA reference)",
                        entity_id=entity,
                        attribute_id=attribute,
                        scope={"legacy_k_id": k},
                        value=typed,
                        value_kind="source_range" if "min" in typed else "exact",
                        proposed_status="VERIFIED",
                        permission_code=code,
                        evidence=[{"ev_id": ev, "source_value": source_of(stated, attribute)}]
                        + (
                            [
                                {
                                    "ev_id": "EV-IGS-DIA",
                                    "source_value": {"min": "2.417", "max": "2.417"},
                                }
                            ]
                            if (entity, attribute) == ("gem.diamond", "refractive_index")
                            else []
                        ),
                        reason=f"v1.6.2 VERIFIED ({check})",
                    )
                    continue
        if check == "CHK-PLEO" and k in PLEO_SOURCE and entity:
            stated = (
                "none"
                if re.search(r"\bнет\b", norm(value))
                else ("strong" if re.search("сильн|выраж", norm(value)) else None)
            )
            if stated:
                claim(
                    k,
                    "one_to_one",
                    "pleochroism statement (GIA)",
                    entity_id=entity,
                    attribute_id="pleochroism",
                    scope={},
                    value={"enum": stated},
                    value_kind="exact",
                    proposed_status="VERIFIED",
                    permission_code=code,
                    evidence=[
                        {
                            "ev_id": ev_ids(r[col["evidence"]])[0],
                            "source_value": {"enum": PLEO_SOURCE[k]},
                        }
                    ],
                    reason=f"v1.6.2 VERIFIED ({check})",
                )
                continue
        if check == "CHK-CARE" and parameter in by_param:
            attribute = by_param[parameter]
            entity = entity or gem_entity(re.split(r"[,(]", str(subject))[0])
            source = CARE_SOURCE_BY_METHOD.get((entity, attribute)) or CARE_SOURCE.get(entity)
            stated = care_class(value)
            if source and stated:
                klass, ev = source
                scope = {"treatment": "untreated"} if klass == "SAFE_COND" else {}
                scope["legacy_k_id"] = k
                claim(
                    k,
                    "one_to_one",
                    "care guidance (GIA)",
                    entity_id=entity,
                    attribute_id=attribute,
                    scope=scope,
                    value={"enum": stated},
                    value_kind="exact",
                    proposed_status="VERIFIED",
                    permission_code=code,
                    evidence=[{"ev_id": ev, "source_value": {"enum": CARE_ENUM[klass]}}],
                    reason=f"v1.6.2 VERIFIED ({check}); GIA class {klass}",
                )
                continue
        if check == "CHK-METAL":
            grade = re.sub(r"\s*-\s*", "-", str(subject).strip())
            if grade in GOST:
                entity_id = "metal.alloy." + hashlib.sha256(grade.encode()).hexdigest()[:10]
                entities.setdefault(
                    entity_id,
                    {
                        "entity_id": entity_id,
                        "entity_type": "alloy_grade",
                        "parent_id": "metal",
                        "label_ru": grade,
                        "label_en": None,
                    },
                )
                typed = {"num": (nums(value) or ["0"])[0]}
                claim(
                    k,
                    "one_to_one",
                    "GOST 30649-99 calculated density",
                    entity_id=entity_id,
                    attribute_id="density",
                    scope={"document": "ГОСТ 30649-99", "alloy_grade": grade, "legacy_k_id": k},
                    value=typed,
                    value_kind="exact",
                    proposed_status="VERIFIED",
                    permission_code=code,
                    evidence=[
                        {"ev_id": "EV-GOST30649-FACSIMILE", "source_value": {"num": GOST[grade]}}
                    ],
                    reason="v1.6.2 VERIFIED (GOST facsimile, re-read 21.11.2026)",
                )
                continue
            if norm(subject) in PURE:
                entity_id, density = PURE[norm(subject)]
                claim(
                    k,
                    "one_to_one",
                    "pure metal density (vendor reference)",
                    entity_id=entity_id,
                    attribute_id="pure_metal_density",
                    scope={"legacy_k_id": k},
                    value={"num": nums(value)[0]},
                    value_kind="exact",
                    proposed_status="VERIFIED",
                    permission_code=code,
                    evidence=[{"ev_id": "EV-METALS", "source_value": {"num": density}}],
                    reason="v1.6.2 VERIFIED (CHK-METAL)",
                )
                continue
        if code == "LEGAL_INFORMATION_ONLY" and k in LEGAL_SCOPE:
            jurisdiction, document, clause, start = LEGAL_SCOPE[k]
            scope = {
                "jurisdiction": jurisdiction,
                "document": document,
                "clause": clause,
                "effective_from": start,
                "legacy_k_id": k,
            }
            if k in LEGAL_EFFECTIVE_TO:
                scope["effective_to"] = LEGAL_EFFECTIVE_TO[k]
            ids = ev_ids(r[col["evidence"]])
            fragment = evidence[ids[0]]["fragment"] if ids else ""
            claim(
                k,
                "one_to_one",
                "normative statement with recorded review",
                entity_id="norm",
                attribute_id="normative_statement",
                scope=scope,
                value={"text_ru": str(value)},
                value_kind="text",
                proposed_status="VERIFIED",
                permission_code=code,
                evidence=[
                    {
                        "ev_id": ev,
                        "source_value": {
                            "text_ru": fragment or str(r[col["basis"]]),
                            "text_en": f"reviewed in v1.4-C CHK-CANON: {r[col['basis']]}"[:500],
                        },
                    }
                    for ev in ids
                ],
                reason=f"v1.6.2 VERIFIED ({check})",
            )
            continue
        # Any other VERIFIED record: kept with its proposal; the loader decides.
        claim(
            k,
            "one_to_one",
            "VERIFIED in v1.6.2 without a comparable source value",
            entity_id=legacy_entity(subject),
            attribute_id="legacy_reference",
            scope={"legacy_k_id": k, "legacy_parameter": parameter[:200]},
            value={"text_ru": str(value)},
            value_kind="text",
            proposed_status="VERIFIED",
            permission_code=code,
            evidence=[{"ev_id": ev, "source_value": None} for ev in ev_ids(r[col["evidence"]])],
            reason=f"v1.6.2 VERIFIED ({check})",
        )
    # Term rows → kb terms with review_status=unreviewed (v1.2 §11: terms go to terms).
    terms = {term["term_id"]: term for term in base["terms"]}
    seen_terms: dict[tuple, str] = {}
    term_legacy = []

    def add_term(entity_id, text, kind, k):
        text = " ".join(str(text).split())
        if not 1 <= len(text) <= 200 or re.fullmatch(r"[\W\d_]+", text):
            return None
        lang = "ru" if re.search("[А-Яа-яЁё]", text) else "en"
        key = (entity_id, lang, normalize_term(text))
        if key not in seen_terms:
            term_id = "term.v162." + hashlib.sha256("|".join(key).encode()).hexdigest()[:16]
            seen_terms[key] = term_id
            terms[term_id] = {
                "term_id": term_id,
                "entity_id": entity_id,
                "lang": lang,
                "text": text,
                "kind": kind,
                "is_preferred": False,
                "review_status": "unreviewed",
                "review_note": f"imported from v1.6.2 {k}; terminology review pending",
            }
        return seen_terms[key]

    for r in rows:
        k = r[col["k"]]
        if (
            k in handled
            or r[3] != "Термин"
            or r[col["status"]] != "REFERENCE ONLY"
            or r[col["parameter"]] not in ("Название EN", "Название RU")
        ):
            continue
        entity_id = legacy_entity(r[col["entity"]])
        produced = []
        subject = re.sub(r"\[[^\]]*\]", "", str(r[col["entity"]] or "")).strip()
        if subject and "=" not in subject and ":" not in subject:
            produced.append(add_term(entity_id, subject, "name", k))
        for piece in re.split(r"\s*/\s*|;\s*", str(r[col["value"]] or "")):
            produced.append(add_term(entity_id, piece, "translation", k))
        produced = sorted({p for p in produced if p})
        if not produced:
            continue
        for term_id in produced:
            term_legacy.append(
                [k, term_id, f"v1.6.2 «{r[col['parameter']]}» row → unreviewed term"]
            )
        handled.add(k)

    # Everything else: text claims grouped by subject + parameter + value.
    groups: dict[tuple, list] = {}
    for r in rows:
        k = r[col["k"]]
        if k in handled:
            continue
        key = (
            legacy_entity(r[col["entity"]]),
            norm(r[col["parameter"]])[:200],
            norm(r[col["value"]]),
            r[col["status"]],
        )
        groups.setdefault(key, []).append(r)
    for (entity_id, _parameter, _, status), members in sorted(
        groups.items(), key=lambda item: item[1][0][col["k"]]
    ):
        first = members[0]
        k = first[col["k"]]
        code = "EXCLUDE" if status == "REJECTED" else "RESEARCH_WITH_CAVEAT"
        mapping = "excluded" if status == "REJECTED" else "one_to_one"
        legacy = [[k, mapping, f"v1.6.2 {first[3] or 'reference record'}"]]
        for other in members[1:]:
            legacy.append(
                [
                    other[col["k"]],
                    "merged" if status != "REJECTED" else "excluded",
                    f"identical subject, parameter and value as {k}",
                ]
            )
        claims.append(
            {
                "legacy": [[a, b, c or "v1.6.2 reference record"] for a, b, c in legacy],
                "entity_id": entity_id,
                "attribute_id": "legacy_reference",
                "scope": {"legacy_k_id": k, "legacy_parameter": str(first[col["parameter"]])[:200]},
                "value": {"text_ru": str(first[col["value"]])},
                "value_kind": "text",
                "proposed_status": status,
                "permission_code": code,
                "evidence": [
                    {"ev_id": ev, "source_value": None} for ev in ev_ids(first[col["evidence"]])
                ],
                "reason": f"v1.6.2 {status}: {str(first[col['basis']] or '')[:200]}",
            }
        )
        for member in members:
            handled.add(member[col["k"]])
    all_k = {r[col["k"]] for r in rows}
    missing = sorted(all_k - handled)
    if missing:
        raise SystemExit(f"unmapped K-IDs: {missing[:10]} (+{len(missing) - 10})")
    seed = dict(base)
    seed.update(
        {
            "seed": "jewelai.knowledge_library.kb.corpus",
            "release_id": "kb-2.1.0",
            "entities": sorted(
                entities.values(), key=lambda e: (e["entity_id"].count("."), e["entity_id"])
            ),
            "attributes": sorted(attributes.values(), key=lambda a: a["attribute_id"]),
            "validation_profiles": sorted(profiles.values(), key=lambda p: p["profile_id"]),
            "evidence": sorted(evidence.values(), key=lambda e: e["ev_id"]),
            "claims": claims,
            "terms": sorted(terms.values(), key=lambda term: term["term_id"]),
            "term_legacy": sorted(term_legacy),
            "k_ids": len(all_k),
        }
    )
    return seed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    seed = build(args.xlsx)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    lines = json.dumps(
        {k: v for k, v in seed.items() if k != "claims"}, ensure_ascii=False, indent=1
    )
    body = ",\n".join(json.dumps(c, ensure_ascii=False, sort_keys=True) for c in seed["claims"])
    args.out.write_text(lines[:-2] + ',\n "claims": [\n' + body + "\n ]\n}\n", encoding="utf-8")
    print(f"{seed['k_ids']} K-IDs → {len(seed['claims'])} claims → {args.out}")


if __name__ == "__main__":
    main()
