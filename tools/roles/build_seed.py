"""Deterministically rebuild the explicit initial Roles import from retained source documents.

Offline operator tool only; never imported or executed by application startup.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
archive = ZipFile(ROOT / "data/roles/sources/original-role-sources.zip")
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--output",
    type=Path,
    default=ROOT / "packages/persistence/src/jewelai_persistence/role_seed.json",
)
output = parser.parse_args().output
registry = archive.read("JewelAI_Role_Registry_v1.0_Approved_RU.md").decode()
cards = archive.read("COMPACT_PERSONA_CARDS_36_v0.5_RU.md").decode()
rows = []
for line in registry.splitlines():
    if not re.match(r"^\| RR-C\d+ \|", line) or "`MERGED_INTO`" in line:
        continue
    cells = [s.strip() for s in line.strip("|").split("|")]
    rid, name, *rest = cells
    rows.append((rid, name, line))
assert len(rows) == 21 and len({r[0] for r in rows}) == 21
aliases = {
    "RR-C04": ["RR-C01", "RR-C05"],
    "RR-C11": ["RR-C03"],
    "RR-C06": ["RR-C07", "RR-C08"],
    "RR-C12": ["RR-C13"],
    "RR-C18": ["RR-C19"],
}


def doc(path, maturity):
    b = archive.read(path)
    return {
        "source_id": path,
        "sha256": hashlib.sha256(b).hexdigest(),
        "language": "ru",
        "maturity": maturity,
        "content": b.decode(),
    }


records = []
for rid, name, line in rows:
    data = {
        "registry": doc("JewelAI_Role_Registry_v1.0_Approved_RU.md", "OWNER_CONFIRMED_COMPOSITION"),
        "registry_entry": line,
        "personas": [],
        "source_date": "2026-11-12",
        "authorization_effect": "none",
    }
    path = f"ROLE_PASSPORT_{rid}_v0.5_RU.md"
    if path in archive.namelist():
        data["passport"] = doc(path, "DRAFT_NOT_OWNER_APPROVED")
        headings = re.findall(r"^## (\d+)\.", archive.read(path).decode(), re.M)
        assert headings == [str(i) for i in range(1, 14)], (rid, headings)
        group = re.search(r"^## " + rid + r" —.*?(?=^## RR-C|\Z)", cards, re.M | re.S).group()
        variants = re.findall(r"^### (" + rid + r"/P\d) —(.*?)(?=^### |\Z)", group, re.M | re.S)
        assert len(variants) == 4
        for pid, body in variants:
            data["personas"].append(
                {
                    "persona_id": pid,
                    "content": "### " + pid + " —" + body,
                    "maturity": "PROTO_PERSONA_MODELING_HYPOTHESIS",
                    "source_id": "COMPACT_PERSONA_CARDS_36_v0.5_RU.md",
                    "source_sha256": hashlib.sha256(
                        archive.read("COMPACT_PERSONA_CARDS_36_v0.5_RU.md")
                    ).hexdigest(),
                }
            )
    records.append(
        {
            "role_id": rid,
            "name_ru": name,
            "name_en": None,
            "status": "active",
            "merged_from_ids": aliases.get(rid, []),
            "role_data": data,
        }
    )
assert sum("passport" in x["role_data"] for x in records) == 9
assert sum(len(x["role_data"]["personas"]) for x in records) == 36
output.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
print("21 roles / 9 draft passports / 36 proto-personas verified")
