"""Offline, fail-closed import of the four exact NB document text snapshots."""

import re
from pathlib import Path

from .contracts import DIMENSIONS, HOLDOUT, VERSION, digest, require, validate_runtime

NEUTRAL = (
    "Answer the user's requests in the user's language. Preserve the conversation context, "
    "state uncertainty honestly, and use no tools."
)
ROLES = ("BUYER_RETAIL", "SELLER", "DESIGNER", "TECHNOLOGIST", "GEMOLOGIST", "BUYER_PM", "MARKETER")
KNOWLEDGE_GROUPS = {
    "KG01": ("G", 1, 2),
    "KG02": ("G", 3, 4),
    "KG03": ("G", 5, 6),
    "KG04": ("G", 7, 9),
    "KG05": ("G", 10, 12),
    "KG06": ("G", 13, 16),
    "KG07": ("G", 17, 20),
    "KG08": ("G", 21, 25),
    "KG09": ("G", 26, 30),
    "KJ01": ("J", 1, 5),
    "KJ02": ("J", 6, 10),
    "KJ03": ("J", 11, 15),
    "KJ04": ("J", 16, 20),
    "KJ05": ("J", 21, 25),
    "KJ06": ("J", 26, 30),
    "KJ07": ("J", 31, 34),
    "KJ08": ("J", 35, 37),
    "KJ09": ("J", 38, 40),
    "KJ10": ("J", 41, 44),
    "KJ11": ("J", 45, 47),
    "KJ12": ("J", 48, 50),
    "KJ13": ("J", 51, 54),
    "KJ14": ("J", 55, 56),
    "KJ15": ("J", 57, 58),
    "KJ16": ("J", 59, 60),
}
DIFFICULT_LENGTHS = (4, 3, 2, 4, 5, 4, 3, 4, 4, 2, 4, 4, 5, 3, 5)


def _cell(applicability):
    return {
        "applicability": applicability,
        "score": "N/A" if applicability == "N/A" else None,
        "reviewer": None,
        "evidence": [],
    }


def evaluation_item(sid, tid, gold, source, tags, difficulty, first, role):
    cells = {d: _cell("APPLICABLE" if d in tags else "N/A") for d in ("S", "T", "K")}
    # NB-04 defines these two by turn position and role. Other applicability needs human review.
    cells.update({d: _cell("REVIEW_REQUIRED") for d in ("X", "Q", "U", "H")})
    cells["R"] = _cell("APPLICABLE" if role else "N/A")
    cells["C"] = _cell("N/A" if first else "APPLICABLE")
    cells["D"] = _cell("N/A" if first else "APPLICABLE")
    return {
        "session_id": sid,
        "turn_id": tid,
        "difficulty": difficulty,
        "gold": gold,
        "source": source,
        "ground_truth_status": "REVIEW_REQUIRED",
        "source_applicability": tags,
        "dimensions": cells,
        "critical_errors": [],
        "review_notes": [],
    }


def import_sources(directory, sources):
    """Never invoked by run/resume. Only the offline importer can read gold."""
    root = Path(directory)
    texts = {
        name: (root / (name + ".txt")).read_text(encoding="utf-8")
        for name in ("NB-01", "NB-04", "NB-05", "NB-06")
    }
    import hashlib

    require({s["id"] for s in sources} == set(texts), "four source identities required")
    for s in sources:
        require(
            s["text_sha256"]
            == hashlib.sha256((root / (s["id"] + ".txt")).read_bytes()).hexdigest(),
            "source snapshot hash mismatch",
        )
        require("v1.0" in texts[s["id"]][:250], "unrecognized source version")
    pattern = re.compile(
        r"^([GJ]\d{2}) \[(RU|EN); D([1-4]); ([STK,]+)\] (.+)\n"
        r"    GOLD \(evaluator only\): (.+)\n    SOURCE: (.+)$",
        re.M,
    )
    questions = {}
    for match in pattern.finditer(texts["NB-05"]):
        qid, lang, difficulty, tags, prompt, gold, source = match.groups()
        require(qid not in questions, "duplicate knowledge question")
        questions[qid] = (lang, int(difficulty), tags.split(","), prompt, gold, source)
    expected_ids = {f"G{i:02}" for i in range(1, 31)} | {f"J{i:02}" for i in range(1, 61)}
    require(set(questions) == expected_ids, "incomplete 90-question source")
    instructions = {"NEUTRAL": NEUTRAL}
    # This is the approved verbatim NB-06 neutral instruction, also satisfying NB-01's neutral rule.
    require(f'"{NEUTRAL}"' in texts["NB-06"], "neutral instruction missing from approved source")
    for role in ROLES:
        matches = re.findall(r"^" + role + r': "([^"\n]+)"$', texts["NB-06"], re.M)
        require(len(matches) == 1, "missing or repeated role instruction")
        instructions[role] = matches[0]
    runtime = {
        "schema_version": VERSION,
        "corpus_id": "jewelai.native.stage1",
        "corpus_version": "1.0.0",
        "protocol_version": "NB-01/1.0",
        "sources": sources,
        "instructions": instructions,
        "sessions": [],
    }
    evaluator = {
        "schema_version": VERSION,
        "rubric_version": "NB-04/1.0",
        "runtime_artifact_sha256": None,
        "items": [],
    }
    groups = re.findall(r"(K[GJ]\d{2}) ([GJ])(\d{2})–[GJ](\d{2}) \(([2-5])\)", texts["NB-01"])
    require(len(groups) == 25, "25 explicit knowledge groups required")
    used = []
    for sid, prefix, start, stop, count in groups:
        ids = [f"{prefix}{n:02}" for n in range(int(start), int(stop) + 1)]
        require(len(ids) == int(count), "group length mismatch")
        used.extend(ids)
        languages = {questions[q][0] for q in ids}
        domains = (
            sorted({f"P0-{(int(q[1:]) - 1) // 5 + 1}" for q in ids})
            if prefix == "J"
            else ["general"]
        )
        session = {
            "session_id": sid,
            "kind": "jewelry" if prefix == "J" else "general",
            "language": next(iter(languages)) if len(languages) == 1 else "MIXED",
            "domains": domains,
            "role": "NEUTRAL",
            "instruction_id": "NEUTRAL",
            "holdout": sid in HOLDOUT,
            "turns": [],
        }
        for index, qid in enumerate(ids):
            lang, difficulty, tags, prompt, gold, source = questions[qid]
            session["turns"].append({"turn_id": qid, "language": lang, "text": prompt})
            evaluator["items"].append(
                evaluation_item(sid, qid, gold, source, tags, difficulty, index == 0, False)
            )
        runtime["sessions"].append(session)
    require(len(used) == 90 and set(used) == expected_ids, "knowledge grouping coverage mismatch")
    headers = list(
        re.finditer(
            r"^([RD]\d{2}) · (\w+) · (RU|EN) · ([2-5]) turns · rubric ([STK,]+)$",
            texts["NB-06"],
            re.M,
        )
    )
    require(len(headers) == 36, "36 dialogue scripts required")
    for i, header in enumerate(headers):
        sid, role, lang, count, tags = header.groups()
        require(role in instructions, "unknown source role")
        chunk = texts["NB-06"][
            header.end() : headers[i + 1].start() if i + 1 < len(headers) else len(texts["NB-06"])
        ]
        users = re.findall(r"^ T([1-5]) USER: (.+)$", chunk, re.M)
        golds = re.findall(r"^ T([1-5]) GOLD \(evaluator-only\): (.+)$", chunk, re.M)
        source = re.findall(r"^ SOURCE: (.+)$", chunk, re.M)
        require(
            [n for n, _ in users] == [str(n) for n in range(1, int(count) + 1)],
            "missing or duplicate scripted turn",
        )
        require(
            [n for n, _ in golds] == [n for n, _ in users] and len(source) == 1,
            "missing dialogue evaluation source",
        )
        session = {
            "session_id": sid,
            "kind": "role" if sid.startswith("R") else "difficult",
            "language": lang,
            "domains": ["professional_role" if sid[0] == "R" else "difficult_dialogue"],
            "role": role,
            "instruction_id": role,
            "holdout": False,
            "turns": [],
        }
        for (number, prompt), (_, gold) in zip(users, golds, strict=True):
            tid = sid + ".T" + number
            session["turns"].append({"turn_id": tid, "language": lang, "text": prompt})
            evaluator["items"].append(
                evaluation_item(
                    sid, tid, gold, source[0], tags.split(","), None, number == "1", sid[0] == "R"
                )
            )
        runtime["sessions"].append(session)
    validate_runtime(runtime)
    validate_stage1(runtime)
    evaluator["runtime_artifact_sha256"] = digest(runtime)
    validate_evaluator(evaluator, runtime)
    return runtime, evaluator


def validate_stage1(runtime):
    validate_runtime(runtime)
    groups = {s["session_id"]: s for s in runtime["sessions"]}
    expected = (
        {f"KG{n:02}" for n in range(1, 10)}
        | {f"KJ{n:02}" for n in range(1, 17)}
        | {f"R{n:02}" for n in range(1, 22)}
        | {f"D{n:02}" for n in range(1, 16)}
    )
    require(set(groups) == expected, "Stage1 requires exactly 61 session IDs")
    require(sum(len(s["turns"]) for s in groups.values()) == 209, "Stage1 requires 209 turns")
    for sid, (prefix, start, stop) in KNOWLEDGE_GROUPS.items():
        require(
            [t["turn_id"] for t in groups[sid]["turns"]]
            == [f"{prefix}{n:02}" for n in range(start, stop + 1)],
            "knowledge parent/order mismatch",
        )
        require(groups[sid]["instruction_id"] == "NEUTRAL", "knowledge instruction must be neutral")
    for n in range(1, 22):
        s = groups[f"R{n:02}"]
        require(
            len(s["turns"]) == (n - 1) % 3 + 2
            and s["role"] == ROLES[(n - 1) // 3]
            and s["instruction_id"] == s["role"],
            "role scenario mapping mismatch",
        )
    for n, count in enumerate(DIFFICULT_LENGTHS, 1):
        s = groups[f"D{n:02}"]
        require(
            len(s["turns"]) == count and s["instruction_id"] == "NEUTRAL",
            "difficult scenario mapping mismatch",
        )
    for sid in expected - KNOWLEDGE_GROUPS.keys():
        require(
            [t["turn_id"] for t in groups[sid]["turns"]]
            == [f"{sid}.T{i}" for i in range(1, len(groups[sid]["turns"]) + 1)],
            "dialogue turn identity mismatch",
        )
    require(
        {s["session_id"] for s in groups.values() if s["holdout"]} == HOLDOUT,
        "holdout parents must match NB-01",
    )
    reserved = {t["turn_id"] for sid in HOLDOUT for t in groups[sid]["turns"]}
    require(
        reserved
        == {f"G{n:02}" for n in range(26, 31)} | {f"J{n:02}" for n in (35, 36, 37, 48, 49, 50)},
        "holdout question mismatch",
    )
    require(
        {d for s in groups.values() for d in s["domains"] if d.startswith("P0-")}
        == {f"P0-{n}" for n in range(1, 13)},
        "missing P0 coverage",
    )
    require(
        {s["role"] for s in groups.values() if s["kind"] == "role"} == set(ROLES),
        "seven roles required",
    )
    return {
        "sessions": 61,
        "user_turns": 209,
        "knowledge_questions": 90,
        "role_scenarios": 21,
        "difficult_scenarios": 15,
        "holdout_questions": 11,
    }


def validate_evaluator(data, runtime):
    require(data["schema_version"] == VERSION, "unsupported evaluator schema")
    require(data["runtime_artifact_sha256"] == digest(runtime), "evaluation corpus mismatch")
    expected = {(s["session_id"], t["turn_id"]) for s in runtime["sessions"] for t in s["turns"]}
    seen = set()
    for item in data["items"]:
        key = (item["session_id"], item["turn_id"])
        require(key in expected and key not in seen, "duplicate or unscoped evaluator item")
        seen.add(key)
        require(set(item["dimensions"]) == set(DIMENSIONS), "missing evaluation dimension")
        require(
            item["ground_truth_status"] in ("REVIEW_REQUIRED", "VERIFIED", "DISPUTED"),
            "invalid ground truth status",
        )
        for cell in item["dimensions"].values():
            a, score = cell["applicability"], cell["score"]
            require(a in ("APPLICABLE", "N/A", "REVIEW_REQUIRED"), "invalid applicability")
            require(
                score is None or score == "N/A" or type(score) is int and 0 <= score <= 4,
                "invalid score",
            )
            require(a != "N/A" or score == "N/A", "N/A must not become zero")
            require(a != "REVIEW_REQUIRED" or score is None, "unresolved applicability scored")
            require(
                item["ground_truth_status"] == "VERIFIED" or score in (None, "N/A"),
                "unresolved gold must not be scored",
            )
    require(seen == expected, "missing evaluation item")
    return data
