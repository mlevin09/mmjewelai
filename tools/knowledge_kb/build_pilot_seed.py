"""Build the Knowledge Library 2.0 pilot seed from Knowledge Library v1.6.2 (ADR 0048, phase B2).

Input: an .xlsx export of the v1.6.2 Google Sheet («Library and Matrix», Drive file
1So1_YjY4DRKbFMALybKPyWcdcBd-EmL7_3OaCzQ71rA). Output: a deterministic JSON seed under
data/knowledge-kb/. The seed records what v1.6.2 proposed (status, permission, source value).
It does not decide VERIFIED: the loader re-qualifies every record by its validation profile.

Usage:
  python tools/knowledge_kb/build_pilot_seed.py --xlsx v162.xlsx \
    --out data/knowledge-kb/pilot-v1.6.2.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import openpyxl

SOURCE_FILE_ID = "1So1_YjY4DRKbFMALybKPyWcdcBd-EmL7_3OaCzQ71rA"
SHEET = "Библиотека (финал)"
COL = {
    "k": 0,
    "entity": 4,
    "parameter": 5,
    "value": 6,
    "status": 8,
    "evidence": 12,
    "check": 13,
    "basis": 14,
    "permission": 26,
    "stuller": 28,
    "dalila": 29,
}

ENTITIES = [
    ("gem", "category", None, "Драгоценные камни", "Gemstones"),
    ("gem.corundum", "mineral", "gem", "Корунд", "Corundum"),
    ("gem.corundum.ruby", "variety", "gem.corundum", "Рубин", "Ruby"),
    ("gem.corundum.sapphire", "variety", "gem.corundum", "Сапфир", "Sapphire"),
    ("gem.diamond", "mineral", "gem", "Алмаз (бриллиант)", "Diamond"),
    ("measure", "category", None, "Единицы и размеры", "Units and sizes"),
    ("measure.ring_size", "measure", "measure", "Размер кольца", "Ring size"),
    ("measure.metric_carat", "unit", "measure", "Метрический карат", "Metric carat"),
    ("metal", "category", None, "Металлы", "Metals"),
    ("metal.gold", "metal", "metal", "Золото", "Gold"),
    ("metal.gold.karat", "unit", "metal.gold", "Карат пробы золота", "Gold karat"),
    ("metal.silver", "metal", "metal", "Серебро", "Silver"),
    ("metal.silver.925", "fineness", "metal.silver", "Серебро 925 (обобщённо)", "Silver 925"),
    ("metal.platinum", "metal", "metal", "Платина", "Platinum"),
    ("metal.platinum.950", "fineness", "metal.platinum", "Платина 950 (обобщённо)", "Pt 950"),
    ("metal.alloy.srm_925", "alloy_grade", "metal.silver", "СрМ 925", "AgCu 925"),
    ("metal.alloy.plpd_850_150", "alloy_grade", "metal.platinum", "ПлПд 850-150", "PtPd 850-150"),
    ("metal.alloy.zlsrm_585_80", "alloy_grade", "metal.gold", "ЗлСрМ 585-80", "AuAgCu 585-80"),
]

# attribute_id, value_type, unit, scale, validation_profile_id
ATTRIBUTES = [
    ("refractive_index", "range", None, None, "gem_ri_source_range"),
    ("mohs_hardness", "range", None, "mohs", "mohs_ordinal"),
    ("specific_gravity", "range", None, None, "gem_sg_source"),
    ("care_steam", "enum", None, None, "care_statement"),
    ("care_ultrasonic", "enum", None, None, "care_statement"),
    ("diameter_at_weight", "number", "mm", None, "stuller_point"),
    ("typical_diameter_range_at_weight", "range", "mm", None, "retail_typical_range"),
    ("ring_size_us", "number", None, "US", "ring_us"),
    ("ring_size_eu", "number", None, "EU/ISO", "ring_eu"),
    ("ring_size_uk", "enum", None, "UK", "ring_uk"),
    ("ring_size_jp", "number", None, "JP", "ring_jp_unsourced"),
    ("mass_in_grams", "number", "g", None, "unit_definition"),
    ("karat_fineness_equivalent", "enum", None, None, "purity_fineness_designation"),
    ("density", "number", "g/cm3", None, "gost_density_exact"),
    ("legacy_reference", "text", None, None, "reference_text"),
]

PROFILES = [
    ("gem_ri_source_range", "source_range", {"precision": 3}),
    ("mohs_ordinal", "ordinal_scale", {"precision": 1}),
    ("gem_sg_source", "source_range", {"precision": 2}),
    ("care_statement", "enum_match", {}),
    ("stuller_point", "approximate_point", {"precision": 1}),
    ("retail_typical_range", "typical_range", {"precision": 1}),
    ("ring_us", "formula", {"formula": "ring_us_from_diameter", "rounding": "nearest_half"}),
    ("ring_eu", "formula", {"formula": "ring_eu_from_diameter", "rounding": "nearest_int"}),
    ("ring_uk", "formula", {"formula": "ring_uk_from_diameter", "rounding": "floor"}),
    ("ring_jp_unsourced", "manual_source_review", {"reason": "EV-RING has no JP formula"}),
    ("unit_definition", "exact_number", {"precision": 3}),
    ("purity_fineness_designation", "enum_match", {}),
    ("gost_density_exact", "exact_number", {"precision": 2}),
    ("reference_text", "manual_source_review", {"reason": "unnormalized legacy text"}),
]

# Evidence copied from the v1.6.2 source registry (fragments as recorded there).
EVIDENCE = {
    "EV-GIA-RUBY": ("GIA", "Gem Encyclopedia — Ruby (FACTS)", "https://www.gia.edu/ruby", "Q1"),
    "EV-GIA-SAPH": (
        "GIA",
        "Gem Encyclopedia — Sapphire (FACTS)",
        "https://my.gia.edu/sapphire",
        "Q1",
    ),
    "EV-GIA-CARE-RUBY": (
        "GIA",
        "Ruby Care and Cleaning Guide (корунд)",
        "https://www.gia.edu/ruby-care-cleaning",
        "Q1",
    ),
    "EV-STULLER": (
        "Stuller",
        "Millimeter to Diamond Carat Weight Conversion Chart",
        "https://blog.stuller.com/wp-content/uploads/2025/05/MM-CT-Chart.pdf",
        "Q2",
    ),
    "EV-DALILA-SIZE": (
        "Dalila Diamonds",
        "Round diamond size chart (secondary retailer)",
        "https://www.daliladiamonds.com/resources/diamond-size-chart",
        "Q3",
    ),
    "EV-RING": (
        "ISO 8653:2016 (iteh preview) + industry tables",
        "Jewellery — Ring-sizes — Definition, measurement and designation; US size chart",
        "https://standards.iteh.ai/catalog/standards/iso/799f4661-1465-4f4f-a23d-1a9ad8567517/iso-8653-2016",
        "Q2",
    ),
    "EV-CARAT": (
        "NBS (NIST) Circular 43",
        "The Metric Carat",
        "https://nvlpubs.nist.gov/nistpubs/Legacy/circ/nbscircular43.pdf",
        "Q1",
    ),
    "EV-BHC-FINENESS": (
        "British Hallmarking Council",
        "Guidance on Fineness Description (approved 7 April 2014)",
        "https://assets.publishing.service.gov.uk/media/5a7f05baed915d74e6227f54/"
        "bhc-guidance-on-fineness-april-2014.pdf",
        "Q1",
    ),
    "EV-IGS-DIA": (
        "International Gem Society",
        "Diamond properties",
        "https://www.gemsociety.org/article/diamond-properties/",
        "Q2",
    ),
    "EV-GOST30649-FACSIMILE": (
        "МГС / Госстандарт (републикация сторонним сайтом)",
        "ГОСТ 30649-99, скан печатного издания, Изм. № 1 и № 2",
        "https://auremo.org/files/gosts/gost-30649-99.pdf",
        "Q2",
    ),
}
FRAGMENTS = {
    "EV-GIA-RUBY": "Corundum, Al2O3; RI 1.762–1.770; SG 4.00 (±0.05); Mohs 9",
    "EV-GIA-SAPH": "Every color but red; RI 1.762–1.770; SG 4.00; Mohs 9",
    "EV-GIA-CARE-RUBY": (
        "Ultrasonic and steam usually safe for untreated, heat-treated and diffused stones; "
        "fracture-filled only with a damp cloth"
    ),
    "EV-STULLER": (
        "Round: 0.005 ct — 1.0 mm … 1 ct — 6.4 mm … 5 ct — 11.0 mm; sizes are approximate"
    ),
    "EV-DALILA-SIZE": "Typical weight–diameter ranges; for example 1.50 ct ≈ 7.3–7.5 mm",
    "EV-RING": (
        "ISO size = inner circumference; US: d = 11.63 + 0.8128 × size (mm); "
        "UK: C = 40 mm, step 1.25 mm"
    ),
    "EV-CARAT": "Metric carat = 200 mg",
    "EV-BHC-FINENESS": "Gold: 999/Fine gold/24ct; 990; 916/22ct; 750/18ct; 585/14ct; 375/9ct",
    "EV-IGS-DIA": "Natural & Synthetics: hardness 10; SG 3.51–3.53; RI 2.417",
    "EV-GOST30649-FACSIMILE": (
        "Tables А.1, Б.1, В.1, Г.1 (calculated density); cross-checked with the dnaop.com and "
        "meganorm.ru transcriptions on 20.11.2026"
    ),
}
LIMITATIONS = {
    "EV-STULLER": "Approximate points; not a production tolerance",
    "EV-DALILA-SIZE": "Secondary retail orientation; not a tolerance or guarantee",
    "EV-GOST30649-FACSIMILE": "Third-party copy of the printed edition; not a certified copy",
    "EV-RING": "Standard annotation plus secondary tables; no JP rule",
    "EV-BHC-FINENESS": (
        "UK traditional descriptions of hallmark finenesses; CARICOM CRS 17:2010 maps 14 kt to "
        "583 (14/24), so 585 ↔ 14K is a designation, not an exact ratio"
    ),
}

# Independently re-read GOST 30649-99 densities (dnaop.com tables, 21.11.2026).
GOST = {"K-03224": "10.36", "K-03091": "19.25", "K-15538": "13.24"}
GOST_ENTITY = {
    "K-03224": "metal.alloy.srm_925",
    "K-03091": "metal.alloy.plpd_850_150",
    "K-15538": "metal.alloy.zlsrm_585_80",
}
GEM_SOURCE = {
    "refractive_index": {"min": "1.762", "max": "1.77"},
    "mohs_hardness": {"num": "9"},
    "specific_gravity": {"num": "4"},
}
REJECTED_EXAMPLES = ("K-05100", "K-09789")

TERMS = [
    ("term.ruby.ru", "gem.corundum.ruby", "ru", "рубин", "name", True),
    ("term.ruby.en", "gem.corundum.ruby", "en", "ruby", "name", True),
    ("term.sapphire.ru", "gem.corundum.sapphire", "ru", "сапфир", "name", True),
    ("term.sapphire.en", "gem.corundum.sapphire", "en", "sapphire", "name", True),
    ("term.corundum.ru", "gem.corundum", "ru", "корунд", "name", True),
    ("term.corundum.en", "gem.corundum", "en", "corundum", "name", True),
    ("term.diamond.ru", "gem.diamond", "ru", "бриллиант", "name", True),
    ("term.diamond.en", "gem.diamond", "en", "diamond", "name", True),
    ("term.metric_carat.ru", "measure.metric_carat", "ru", "карат", "name", True),
    ("term.metric_carat.en", "measure.metric_carat", "en", "carat", "name", True),
    ("term.metric_carat.ct", "measure.metric_carat", "en", "ct", "synonym", False),
    ("term.gold_karat.ru", "metal.gold.karat", "ru", "карат", "name", True),
    ("term.gold_karat.en", "metal.gold.karat", "en", "karat", "name", True),
]
RELATIONS = [
    (
        "rel.carat_karat",
        "term.metric_carat.en",
        "term.gold_karat.en",
        "false_equivalent",
        "carat (mass, 0.2 g) ≠ karat (gold fineness in 24ths)",
    ),
    (
        "rel.karat_ru_ambiguous",
        "term.metric_carat.ru",
        "term.gold_karat.ru",
        "ambiguous",
        "В русском «карат» обозначает и массу камня, и пробу золота",
    ),
]

CALLERS = [
    (
        "semantic_orchestrator",
        "Conversational Core SO (phase C consumer)",
        [
            "resolve",
            "verify_evidence",
            "release_metadata",
            "display",
            "display_caveat",
            "explain",
            "prompt",
            "calc_reference",
            "validate_warn",
        ],
    ),
    (
        "consultant",
        "AI consultant",
        [
            "resolve",
            "search",
            "release_metadata",
            "display",
            "display_caveat",
            "explain",
            "legal_info",
        ],
    ),
    (
        "trainer",
        "Gemology trainer",
        ["resolve", "search", "release_metadata", "display", "display_caveat", "explain"],
    ),
]


def num(text: str) -> str:
    return text.replace(",", ".")


def parse_mm(text) -> dict | None:
    if text in (None, ""):
        return None
    cleaned = str(text).replace("≈", " ")
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*[–-]\s*(\d+(?:[.,]\d+)?)", cleaned)
    if match:
        return {"min": num(match.group(1)), "max": num(match.group(2))}
    match = re.search(r"(\d+(?:[.,]\d+)?)", cleaned)
    return {"num": num(match.group(1))} if match else None


def ring_value(text: str) -> str:
    text = str(text).strip()
    if text.endswith("½"):
        base = text[:-1] or "0"
        return f"{base}.5"
    return num(text)


def gem_entity(name: str) -> str:
    name = name.lower()
    ruby, sapphire = "рубин" in name, "сапфир" in name
    if ruby and not sapphire:
        return "gem.corundum.ruby"
    if sapphire and not ruby:
        return "gem.corundum.sapphire"
    return "gem.corundum"


def build(xlsx: Path) -> dict:
    workbook = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    rows = [list(r) for r in workbook[SHEET].iter_rows(values_only=True)][1:]
    rows = [r + [None] * (31 - len(r)) for r in rows if r and r[0]]
    by_k = {r[COL["k"]]: r for r in rows}
    claims = []

    def add(claim):
        claims.append(claim)

    # --- corundum
    for r in rows:
        entity_text = str(r[COL["entity"]] or "")
        if not re.search("рубин|сапфир|корунд", entity_text.lower()):
            continue
        k, parameter, status = r[COL["k"]], str(r[COL["parameter"]]), r[COL["status"]]
        if status == "VERIFIED":
            continue
        add(
            {
                "legacy": [[k, "one_to_one", "unnormalized legacy text kept as reference"]],
                "entity_id": gem_entity(entity_text),
                "attribute_id": "legacy_reference",
                "scope": {"legacy_k_id": k, "legacy_parameter": parameter[:200]},
                "value": {"text_ru": str(r[COL["value"]])},
                "value_kind": "text",
                "proposed_status": status,
                "permission_code": r[COL["permission"]],
                "evidence": [],
                "reason": f"v1.6.2 {status}: {str(r[COL['basis']] or '')[:200]}",
            }
        )
    for k in REJECTED_EXAMPLES:
        r = by_k[k]
        add(
            {
                "legacy": [[k, "excluded", "REJECTED in v1.6.2; kept for history only"]],
                "entity_id": "gem.corundum",
                "attribute_id": "legacy_reference",
                "scope": {"legacy_k_id": k},
                "value": {"text_ru": str(r[COL["value"]])},
                "value_kind": "text",
                "proposed_status": "REJECTED",
                "permission_code": "EXCLUDE",
                "evidence": [],
                "reason": f"v1.6.2 REJECTED: {str(r[COL['basis']] or '')[:200]}",
            }
        )
    gem_attr = {
        "Показатель преломления (RI)": "refractive_index",
        "Твёрдость (Моос)": "mohs_hardness",
        "Удельный вес / плотность (SG)": "specific_gravity",
    }
    for k in ("K-00851", "K-00853", "K-00855", "K-00894", "K-00896", "K-00898"):
        r = by_k[k]
        attribute = gem_attr[r[COL["parameter"]]]
        ev = r[COL["evidence"]]
        raw = str(r[COL["value"]])
        value = parse_mm(raw) if attribute == "refractive_index" else {"num": num(raw.split()[0])}
        if attribute == "refractive_index":
            value = {"min": value["min"], "max": value["max"]}
        add(
            {
                "legacy": [[k, "one_to_one", "atomic gem constant"]],
                "entity_id": gem_entity(r[COL["entity"]]),
                "attribute_id": attribute,
                "scope": {},
                "value": value,
                "value_kind": "source_range" if attribute == "refractive_index" else "exact",
                "proposed_status": "VERIFIED",
                "permission_code": r[COL["permission"]],
                "evidence": [{"ev_id": ev, "source_value": GEM_SOURCE[attribute]}],
                "reason": f"v1.6.2 VERIFIED ({r[COL['check']]})",
            }
        )
    care = {
        ("gem.corundum.ruby", "care_steam"): ["K-04474", "K-11034"],
        ("gem.corundum.ruby", "care_ultrasonic"): ["K-04475", "K-11037"],
        ("gem.corundum.sapphire", "care_steam"): ["K-04474", "K-11074"],
        ("gem.corundum.sapphire", "care_ultrasonic"): ["K-04475", "K-11077"],
    }
    for (entity, attribute), ks in care.items():
        legacy_rows = [
            [
                ks[0],
                "split",
                "«рубин, сапфир (не облагороженные)» split into one claim per variety",
            ],
            [
                ks[1],
                "merged",
                "✅ without treatment scope merged; GIA limits it to untreated/heated/diffused",
            ],
        ]
        add(
            {
                "legacy": legacy_rows,
                "entity_id": entity,
                "attribute_id": attribute,
                "scope": {"treatment": "untreated"},
                "value": {"enum": "usually_safe"},
                "value_kind": "exact",
                "proposed_status": "VERIFIED",
                "permission_code": "CARE_GUIDANCE_CONDITIONAL",
                "evidence": [
                    {"ev_id": "EV-GIA-CARE-RUBY", "source_value": {"enum": "usually_safe"}}
                ],
                "reason": "v1.6.2 VERIFIED (CHK-CARE)",
            }
        )
    # --- diamond sizes
    size_rows = [
        r for r in rows if r[COL["permission"]] == "APPROX_SIZE_REFERENCE" and r[0] != "K-17678"
    ]
    stuller_claims = []
    for r in sorted(size_rows, key=lambda r: float(re.search(r"массе ([0-9.]+)", r[5]).group(1))):
        k = r[COL["k"]]
        weight = re.search(r"массе ([0-9.]+)", r[COL["parameter"]]).group(1)
        stuller = parse_mm(r[COL["stuller"]])
        stated = parse_mm(r[COL["value"]])
        mapping = (
            ("one_to_one", "atomic Stuller reference point")
            if stated == stuller
            else ("split", f"v1.6.2 value «{r[COL['value']]}» mixed sources; Stuller point kept")
        )
        legacy_rows = [[k, *mapping]]
        claim = {
            "legacy": legacy_rows,
            "entity_id": "gem.diamond",
            "attribute_id": "diameter_at_weight",
            "scope": {"shape": "round", "carat_weight": weight, "reference": "stuller_2025"},
            "value": stuller,
            "value_kind": "approximate",
            "proposed_status": "VERIFIED",
            "permission_code": "APPROX_SIZE_REFERENCE",
            "evidence": [{"ev_id": "EV-STULLER", "source_value": stuller}],
            "reason": "v1.6.2 VERIFIED (CHK-SIZE)",
        }
        stuller_claims.append(claim)
        add(claim)
        dalila = parse_mm(r[COL["dalila"]])
        if dalila:
            if "num" in dalila:
                dalila = {"min": dalila["num"], "max": dalila["num"]}
            add(
                {
                    "legacy": [[k, "split", "independent Dalila typical range kept separately"]],
                    "entity_id": "gem.diamond",
                    "attribute_id": "typical_diameter_range_at_weight",
                    "scope": {
                        "shape": "round",
                        "carat_weight": weight,
                        "reference": "dalila_typical",
                    },
                    "value": dalila,
                    "value_kind": "source_range",
                    "proposed_status": "REFERENCE ONLY",
                    "permission_code": "RESEARCH_WITH_CAVEAT",
                    "evidence": [{"ev_id": "EV-DALILA-SIZE", "source_value": dalila}],
                    "reason": "secondary retail range; orientation only (v1.6.2 column «Dalila»)",
                }
            )
    for claim in stuller_claims:
        claim["legacy"].append(
            ["K-17678", "split", "aggregated weight–diameter table split into atomic points"]
        )
    # --- ring sizes and metric carat
    ring_attr = {
        "US": "ring_size_us",
        "EU (окр. мм)": "ring_size_eu",
        "UK": "ring_size_uk",
        "JP": "ring_size_jp",
    }
    for r in rows:
        if r[COL["permission"]] != "NONBINDING_UNIT_CONVERSION":
            continue
        k = r[COL["k"]]
        if k == "K-17682":
            add(
                {
                    "legacy": [[k, "one_to_one", "metric carat definition"]],
                    "entity_id": "measure.metric_carat",
                    "attribute_id": "mass_in_grams",
                    "scope": {},
                    "value": {"num": "0.2"},
                    "value_kind": "exact",
                    "proposed_status": "VERIFIED",
                    "permission_code": "NONBINDING_UNIT_CONVERSION",
                    "evidence": [{"ev_id": "EV-CARAT", "source_value": {"num": "0.2"}}],
                    "reason": "v1.6.2 VERIFIED (1 ct = 200 mg)",
                }
            )
            continue
        attribute = ring_attr[r[COL["parameter"]]]
        diameter = num(re.search(r"= *([0-9,.]+)", r[COL["entity"]]).group(1))
        raw = ring_value(r[COL["value"]])
        value = {"enum": raw} if attribute == "ring_size_uk" else {"num": raw}
        add(
            {
                "legacy": [[k, "one_to_one", "ring size conversion"]],
                "entity_id": "measure.ring_size",
                "attribute_id": attribute,
                "scope": {"from_system": "RU_inner_diameter_mm", "from_value": diameter},
                "value": value,
                "value_kind": "derived",
                "proposed_status": "VERIFIED",
                "permission_code": "NONBINDING_UNIT_CONVERSION",
                "evidence": [{"ev_id": "EV-RING", "source_value": None}],
                "reason": "v1.6.2 VERIFIED (CHK-RING)",
            }
        )
    # --- purity
    for k in ("K-02643", "K-02644", "K-02645"):
        r = by_k[k]
        fineness, karat = re.match(r"(\d+) / (\d+)K", r[COL["entity"]]).groups()
        add(
            {
                "legacy": [[k, "one_to_one", "fineness ↔ karat correspondence"]],
                "entity_id": "metal.gold.karat",
                "attribute_id": "karat_fineness_equivalent",
                "scope": {"from_system": "fineness_per_mille", "from_value": fineness},
                "value": {"enum": f"k{karat}"},
                "value_kind": "derived",
                "proposed_status": "VERIFIED",
                "permission_code": "NONBINDING_PURITY_CONVERSION",
                "evidence": [{"ev_id": "EV-BHC-FINENESS", "source_value": {"enum": f"k{karat}"}}],
                "reason": f"v1.6.2 VERIFIED (CHK-PURITY): {r[COL['basis']]}",
            }
        )
    # --- GOST alloys and generic grades
    for k, density in GOST.items():
        add(
            {
                "legacy": [[k, "one_to_one", "GOST 30649-99 calculated density"]],
                "entity_id": GOST_ENTITY[k],
                "attribute_id": "density",
                "scope": {"document": "ГОСТ 30649-99", "alloy_grade": by_k[k][COL["entity"]]},
                "value": {"num": density},
                "value_kind": "exact",
                "proposed_status": "VERIFIED",
                "permission_code": "GOST_ALLOY_DENSITY_REFERENCE",
                "evidence": [{"ev_id": "EV-GOST30649-FACSIMILE", "source_value": {"num": density}}],
                "reason": "v1.6.2 VERIFIED (GOST facsimile, re-read 21.11.2026)",
            }
        )
    for k, entity in (("K-02658", "metal.silver.925"), ("K-02808", "metal.platinum.950")):
        r = by_k[k]
        add(
            {
                "legacy": [[k, "one_to_one", "generic grade: no single density"]],
                "entity_id": entity,
                "attribute_id": "legacy_reference",
                "scope": {"legacy_k_id": k, "legacy_parameter": r[COL["parameter"]]},
                "value": {"text_ru": str(r[COL["value"]])},
                "value_kind": "text",
                "proposed_status": "REFERENCE ONLY",
                "permission_code": "RESEARCH_WITH_CAVEAT",
                "evidence": [{"ev_id": "EV-GOST30649-FACSIMILE", "source_value": None}],
                "reason": "generic grade; GOST defines densities per exact grade only",
            }
        )
    xlsx_hash = hashlib.sha256(xlsx.read_bytes()).hexdigest()
    return {
        "seed": "jewelai.knowledge_library.kb.pilot",
        "seed_version": "1.0.0",
        "release_id": "kb-2.0.0-pilot",
        "source": {
            "library": "JewelAI Knowledge Library v1.6.2",
            "drive_file_id": SOURCE_FILE_ID,
            "xlsx_export_sha256": xlsx_hash,
        },
        "entities": [
            dict(
                zip(
                    ("entity_id", "entity_type", "parent_id", "label_ru", "label_en"),
                    e,
                    strict=True,
                )
            )
            for e in ENTITIES
        ],
        "attributes": [
            dict(
                zip(
                    ("attribute_id", "value_type", "unit", "scale", "validation_profile_id"),
                    a,
                    strict=True,
                )
            )
            for a in ATTRIBUTES
        ],
        "validation_profiles": [
            {"profile_id": p, "method": m, "params": params} for p, m, params in PROFILES
        ],
        "evidence": [
            {
                "ev_id": ev,
                "org": org,
                "title": title,
                "url": url,
                "tier": tier,
                "fragment": FRAGMENTS[ev],
                "limitations": LIMITATIONS.get(ev),
                "retrieved_at": "2026-11-20",
            }
            for ev, (org, title, url, tier) in EVIDENCE.items()
        ],
        "terms": [
            {**term, "review_status": "curated", "review_note": "JewelAI pilot canonical name"}
            for term in [
                dict(
                    zip(
                        ("term_id", "entity_id", "lang", "text", "kind", "is_preferred"),
                        t,
                        strict=True,
                    )
                )
                for t in TERMS
            ]
        ],
        "term_relations": [
            dict(zip(("relation_id", "term_a", "term_b", "relation", "note"), r, strict=True))
            for r in RELATIONS
        ],
        "callers": [{"caller_id": c, "description": d, "purposes": p} for c, d, p in CALLERS],
        "claims": claims,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    seed = build(args.xlsx)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(seed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(seed['claims'])} claims → {args.out}")


if __name__ == "__main__":
    main()
