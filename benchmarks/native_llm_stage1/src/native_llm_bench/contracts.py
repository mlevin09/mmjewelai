"""Strict local artifacts. Evaluator fields are not part of the runtime schema."""

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

VERSION = "1.0.0"
SEED = 20261111
HOLDOUT = {"KG09", "KJ08", "KJ12"}
DIMENSIONS = ("S", "T", "K", "R", "C", "X", "Q", "U", "H", "D")
ID = re.compile(r"[A-Z][A-Z0-9_.-]{0,63}")


class InvalidArtifact(ValueError):
    """A bounded error; never include source text or remote error bodies."""


def require(condition, reason):
    if not condition:
        raise InvalidArtifact(reason)


def keys(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected), "invalid artifact fields")


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _object(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, "duplicate JSON field")
        obj[key] = value
    return obj


def decode(data):
    try:
        return json.loads(
            data,
            object_pairs_hook=_object,
            parse_constant=lambda _: require(False, "nonfinite JSON number"),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidArtifact("invalid JSON artifact") from exc


def load(path):
    return decode(Path(path).read_bytes())


def text(value):
    require(isinstance(value, str) and bool(value.strip()), "missing text")


def loopback_address(endpoint):
    text(endpoint)
    u = urlsplit(endpoint)
    require(
        u.scheme == "http"
        and u.hostname in ("127.0.0.1", "::1")
        and not u.username
        and not u.password
        and not u.query
        and not u.fragment
        and u.path in ("", "/"),
        "endpoint must be numeric loopback HTTP",
    )
    try:
        require(u.port is not None and 1 <= u.port <= 65535, "explicit port required")
    except ValueError as exc:
        raise InvalidArtifact("invalid endpoint port") from exc
    return u


def validate_runtime(data):
    keys(
        data,
        (
            "schema_version",
            "corpus_id",
            "corpus_version",
            "protocol_version",
            "sources",
            "instructions",
            "sessions",
        ),
    )
    require(data["schema_version"] == VERSION, "unsupported runtime schema")
    for key in ("corpus_id", "corpus_version", "protocol_version"):
        text(data[key])
    require(isinstance(data["sources"], list), "invalid source manifest")
    source_ids = set()
    for source in data["sources"]:
        keys(source, ("id", "document_id", "revision_id", "text_sha256"))
        for value in source.values():
            text(value)
        require(source["id"] not in source_ids, "duplicate source ID")
        require(bool(re.fullmatch("[0-9a-f]{64}", source["text_sha256"])), "invalid source hash")
        source_ids.add(source["id"])
    require(isinstance(data["instructions"], dict) and data["instructions"], "missing instructions")
    for instruction_id, instruction in data["instructions"].items():
        require(bool(ID.fullmatch(instruction_id)), "invalid instruction ID")
        text(instruction)
    require(isinstance(data["sessions"], list) and data["sessions"], "missing sessions")
    sessions, turns = set(), set()
    for session in data["sessions"]:
        keys(
            session,
            (
                "session_id",
                "kind",
                "language",
                "domains",
                "role",
                "instruction_id",
                "holdout",
                "turns",
            ),
        )
        sid = session["session_id"]
        require(isinstance(sid, str) and bool(ID.fullmatch(sid)), "invalid session ID")
        require(sid not in sessions, "duplicate session ID")
        sessions.add(sid)
        require(
            session["kind"] in ("general", "jewelry", "role", "difficult", "synthetic"),
            "invalid session kind",
        )
        require(session["language"] in ("RU", "EN", "MIXED"), "invalid session language")
        require(isinstance(session["holdout"], bool), "invalid holdout flag")
        require(isinstance(session["domains"], list) and session["domains"], "missing domains")
        for domain in session["domains"]:
            text(domain)
        text(session["role"])
        require(session["instruction_id"] in data["instructions"], "unknown instruction")
        require(
            isinstance(session["turns"], list) and 2 <= len(session["turns"]) <= 5,
            "sessions require two to five turns",
        )
        for turn in session["turns"]:
            keys(turn, ("turn_id", "language", "text"))
            tid = turn["turn_id"]
            require(isinstance(tid, str) and bool(ID.fullmatch(tid)), "invalid turn ID")
            require(tid not in turns, "duplicate turn ID")
            turns.add(tid)
            require(turn["language"] in ("RU", "EN"), "invalid turn language")
            text(turn["text"])
    return data


def validate_manifest(data):
    keys(
        data,
        (
            "model_id",
            "model_sha256",
            "runtime_sha256",
            "runtime_commit",
            "quantization",
            "context_tokens",
            "runtime_flags",
            "verification_status",
            "verified_at",
            "environment",
        ),
    )
    for key in ("model_id", "runtime_commit", "quantization", "environment"):
        text(data[key])
    for key in ("model_sha256", "runtime_sha256"):
        require(bool(re.fullmatch("[0-9a-f]{64}", data[key])), "missing model/runtime fingerprint")
    require(type(data["context_tokens"]) is int and data["context_tokens"] > 0, "invalid context")
    require(
        data["runtime_flags"] is None
        or isinstance(data["runtime_flags"], list)
        and all(isinstance(x, str) for x in data["runtime_flags"]),
        "invalid runtime flags",
    )
    require(
        data["verification_status"] in ("SYNTHETIC", "HISTORICAL_NOT_REVERIFIED", "NB08_ATTESTED"),
        "invalid verification status",
    )
    require(
        data["verified_at"] is None or isinstance(data["verified_at"], str),
        "invalid verification timestamp",
    )
    if data["verification_status"] == "NB08_ATTESTED":
        text(data["verified_at"])
    return data


@dataclass(frozen=True)
class Config:
    endpoint: str = "http://127.0.0.1:8080"
    model: str = "qwen3-1.7b-q4_k_m"
    context_tokens: int = 2048
    temperature: float = 0
    top_p: float = 1
    top_k: int | None = 40
    seed: int | None = SEED
    max_tokens: int = 128
    repeat_penalty: float = 1
    timeout_seconds: float = 60
    max_attempts: int = 1
    min_p: float | None = None
    presence_penalty: float | None = None

    def validate(self, manifest):
        loopback_address(self.endpoint)
        require(self.model == manifest["model_id"], "model identifier mismatch")
        require(
            type(self.context_tokens) is int and self.context_tokens == manifest["context_tokens"],
            "context manifest mismatch",
        )
        require(
            type(self.max_tokens) is int and 1 <= self.max_tokens < self.context_tokens,
            "invalid maximum tokens",
        )
        require(
            type(self.max_attempts) is int and 1 <= self.max_attempts <= 3,
            "attempt budget must be one to three",
        )
        for value, lo, hi in (
            (self.temperature, 0, 2),
            (self.top_p, 0.00001, 1),
            (self.repeat_penalty, 0.01, 3),
            (self.timeout_seconds, 0.01, 1800),
        ):
            require(
                type(value) in (int, float) and math.isfinite(value) and lo <= value <= hi,
                "invalid numeric configuration",
            )
        require(
            self.top_k is None or type(self.top_k) is int and 0 <= self.top_k <= 10000,
            "invalid top-k",
        )
        require(
            self.seed is None or type(self.seed) is int and 0 <= self.seed < 2**32,
            "invalid inference seed",
        )
        for name, value, upper in (
            ("min_p", self.min_p, 1),
            ("presence_penalty", self.presence_penalty, 2),
        ):
            require(
                value is None
                or type(value) in (int, float)
                and math.isfinite(value)
                and 0 <= value <= upper,
                f"invalid {name}",
            )
        return self

    def payload(self, messages):
        """The only request builder: metadata/evaluator artifacts cannot be serialized here."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "repeat_penalty": self.repeat_penalty,
            "cache_prompt": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if self.seed is not None:
            payload["seed"] = self.seed
        if self.top_k is not None:
            payload["top_k"] = self.top_k
        if self.min_p is not None:
            payload["min_p"] = self.min_p
        if self.presence_penalty is not None:
            payload["presence_penalty"] = self.presence_penalty
        return payload

    def record(self):
        record = asdict(self)
        # Historical config/plan hashes predate these optional fields. Preserve them,
        # including the historical treatment of null seed/top_k, when controls are absent.
        for name in ("min_p", "presence_penalty"):
            if record[name] is None:
                del record[name]
        return record


class XorShift32:
    """xorshift32-v1: (13,17,5), unsigned 32-bit; rejection-sampled randbelow."""

    def __init__(self, seed):
        require(type(seed) is int and 0 <= seed < 2**32, "invalid scheduling seed")
        self.state = seed or 0x6D2B79F5

    def next(self):
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x & 0xFFFFFFFF
        return self.state

    def below(self, n):
        limit = 2**32 - (2**32 % n)
        while (value := self.next()) >= limit:
            pass
        return value % n

    def shuffle(self, values):
        for i in range(len(values) - 1, 0, -1):
            j = self.below(i + 1)
            values[i], values[j] = values[j], values[i]


def execution_plan(
    corpus,
    config,
    manifest,
    seed=SEED,
    selected=None,
    exclude_holdouts=False,
    *,
    instruction_override=None,
):
    validate_runtime(corpus)
    validate_manifest(manifest)
    config.validate(manifest)
    available = {s["session_id"] for s in corpus["sessions"]}
    if selected is not None:
        require(
            len(selected) == len(set(selected)) and set(selected) <= available,
            "unknown or duplicate selection ID",
        )
    sessions = [s for s in corpus["sessions"] if selected is None or s["session_id"] in selected]
    if exclude_holdouts:
        require(
            selected is None or not any(s["holdout"] for s in sessions),
            "explicit selection conflicts with excluded holdouts",
        )
        sessions = [s for s in sessions if not s["holdout"]]
    require(bool(sessions), "empty session selection")
    rng = XorShift32(seed)
    buckets = {}
    for s in sorted(sessions, key=lambda s: s["session_id"]):
        key = (s["kind"], s["language"], tuple(sorted(s["domains"])), len(s["turns"]))
        buckets.setdefault(key, []).append(s["session_id"])
    strata = sorted(buckets)
    rng.shuffle(strata)
    for key in strata:
        rng.shuffle(buckets[key])
    order = [
        buckets[key][i]
        for i in range(max(map(len, buckets.values())))
        for key in strata
        if i < len(buckets[key])
    ]
    plan = {
        "plan_version": VERSION,
        "corpus_id": corpus["corpus_id"],
        "corpus_version": corpus["corpus_version"],
        "protocol_version": corpus["protocol_version"],
        "runtime_artifact_sha256": digest(corpus),
        "sources": corpus["sources"],
        "configuration": config.record(),
        "configuration_sha256": digest(config.record()),
        "model_manifest": manifest,
        "model_manifest_sha256": digest(manifest),
        "scheduling_seed": seed,
        "prng": "xorshift32-13-17-5-rejection-v1",
        "schedule": "sorted-strata-fisher-yates-round-robin-v1",
        "session_order": order,
        "turn_order": {s["session_id"]: [t["turn_id"] for t in s["turns"]] for s in sessions},
        "holdout_sessions_selected": sorted(s["session_id"] for s in sessions if s["holdout"]),
        "exclude_holdouts": exclude_holdouts,
        "output_reproducibility": "NOT_ESTABLISHED; scheduling determinism is not output equality",
    }
    if instruction_override is not None:
        from .instructions import instruction_variation

        variation = instruction_variation(corpus, sessions, instruction_override)
        plan["instruction_override"] = variation
        experiment = {
            "profile_id": variation["manifest"]["profile_id"],
            "sampling_configuration": config.record(),
            "instruction_override_sha256": variation["manifest_sha256"],
        }
        plan["experiment_configuration"] = experiment
        plan["experiment_configuration_sha256"] = digest(experiment)
    return plan
