# NB-07 — standalone native LLM benchmark runner

**Benchmark branch only. Do not merge or open a PR against JewelAI integration/production.**
Zero-runtime-dependency Python3.12+ CLI, POSIX filesystem; never an application dependency.
No JewelAI imports, VM startup, infrastructure operations, tool calls or external inference APIs.

## Authority and private data

NB-01 protocol, NB-04 rubric, NB-05 questions and NB-06 scripts are authoritative.
Captured document revisions and UTF-8 snapshot SHA-256 values:
[source-pins.v1.json](fixtures/source-pins.v1.json).
Actual offline import: 30G +60J in25 sessions,21R +15D scenarios:
**61 sessions /209 user turns**, every session2–5 turns. Gold remains REVIEW_REQUIRED.

The repository is public. Actual source snapshots, runtime/evaluator artifacts and transcripts
belong in private storage, **not Git**. Only synthetic prompts are committed. The private NB-07
evidence includes the actual imported corpus. Private/runs/exports directories here are ignored.
Versioned runtime.json and evaluator.json are separate artifacts, joined by stable IDs and the
canonical runtime SHA-256. Run/resume do not open the evaluator file. No professional grading,
real inference, pilot, full campaign, model-quality acceptance or VM activation occurs in NB-07.

## CLI (from this directory)

~~~bash
export PYTHONPATH="$PWD/src"
python3 -m native_llm_bench validate --runtime fixtures/synthetic.runtime.json
python3 -m native_llm_bench plan --runtime fixtures/synthetic.runtime.json \
  --config fixtures/synthetic.config.json --model-manifest fixtures/synthetic.model.json \
  --sessions SYN2,SYN5
~~~

Validation/preview are offline: no endpoint health probe or VM operation.
For a runnable synthetic HTTP demonstration, in another terminal:

~~~bash
python3 tests/synthetic_server.py --port 8080
~~~

This is a fake acknowledgment server, **not a model**. Stop it with Ctrl-C. Then:

~~~bash
python3 -m native_llm_bench run --runtime fixtures/synthetic.runtime.json \
  --config fixtures/synthetic.config.json --model-manifest fixtures/synthetic.model.json \
  --sessions SYN2,SYN5 --output runs
# Substitute the returned run_directory below:
python3 -m native_llm_bench inspect runs/RUN_ID
python3 -m native_llm_bench resume runs/RUN_ID \
  --runtime fixtures/synthetic.runtime.json --config fixtures/synthetic.config.json \
  --model-manifest fixtures/synthetic.model.json
python3 -m native_llm_bench export runs/RUN_ID --output exports/RUN_ID.json
# Explicit new run, preserving original results and recording parent lineage:
python3 -m native_llm_bench run --runtime fixtures/synthetic.runtime.json \
  --config fixtures/synthetic.config.json --model-manifest fixtures/synthetic.model.json \
  --sessions SYN2,SYN5 --output runs --rerun-of runs/RUN_ID
~~~

Run/resume exit0 only when all selected turns complete; otherwise2. Invalid artifacts/config
exit64; handled interruption130. Inspect reports journal accounting, not quality.
Exports contain full transcripts, are private and refuse to overwrite existing files.

## Exact source import

~~~bash
python3 -m native_llm_bench import-corpus --sources /PRIVATE/NB-SNAPSHOTS \
  --provenance fixtures/source-pins.v1.json --output private/corpus-v1
python3 -m native_llm_bench validate --runtime private/corpus-v1/runtime.json \
  --evaluator private/corpus-v1/evaluator.json
~~~

Source directory: NB-01.txt, NB-04.txt, NB-05.txt, NB-06.txt. Snapshots preserve native paragraph/
table text and exact RU/EN user/role strings; never hand-rewrite prompts. Hashes bind extraction
bytes, distinct from canonical JSON hashes and output-file byte hashes. Import fails on changed
hashes/versions, duplicate/missing IDs, incomplete USER/GOLD entries, invalid lengths/parent
mappings, missing P0 coverage or holdout mismatch. Source-format changes require importer review.

Knowledge turns keep G/J IDs; dialogue turns use R01.T1/D01.T1. KG09(G26–30), KJ08(J35–37),
KJ12(J48–50) remain in the full corpus. The optional --exclude-holdouts selector excludes them;
explicit conflicting selection fails. No NB-09 pilot sampling/execution is implemented.

The exact NB-06 neutral instruction is reused for knowledge under NB-01's neutral instruction rule.
Roles receive only their corresponding exact NB-06 instruction. No gold/reference/rubric text is
present in runtime artifacts. Evaluator S/T/K are independent; non-tagged dimensions are N/A,
not zero. Unresolved extra applicability is REVIEW_REQUIRED. No automatic scoring or LLM judge.
Numeric scores require VERIFIED ground truth; disputed/unreviewed gold cannot be graded.

## Reproducibility

Default scheduling seed20261111. Algorithm xorshift32-13-17-5-rejection-v1: unsigned32 shifts
(13,17,5), zero-seed initial state0x6D2B79F5. randbelow(n) rejects values at/above
2^32−(2^32 mod n), then uses modulo. Descending Fisher–Yates swaps i with a draw in[0,i].

Schedule sorted-strata-fisher-yates-round-robin-v1: sort session IDs, bucket by
(kind,language,sorted domain tuple,turn count), sort bucket keys, shuffle keys, shuffle each bucket
in that order using the same PRNG, emit round-robin. Selection/exclusion happens first.
This is a complete stratified permutation, **not random regrouping or shuffled user turns**.
Mixed-language KJ08 remains mixed. Store permutation, turn order, corpus/protocol/source hashes,
parameters, model manifest, Git SHA/dirty flag and executable-source hash.

Seeded execution reproducibility is separate from **unestablished model-output equality**.
NB-08 must verify actual model/runtime fingerprints and any real replay claims.

## Direct inference and measurements

Only numeric-loopback HTTP127.0.0.1/[::1] with explicit port is accepted, even by the transport.
No DNS destination, proxy, redirect, credential URL or arbitrary path/query. Only
/v1/chat/completions is called. Each payload contains system + this session's preceding
user/actual completed assistant content + one new user turn. New sessions start fresh.

Request allowlist: model/messages/stream=false/temperature/top_p/optional top_k+seed/max_tokens/
repeat_penalty/cache_prompt=false/chat_template_kwargs.enable_thinking=false.
Supported by [the installed llama.cpp commit](https://github.com/ggml-org/llama.cpp/blob/cd959bae99ff4bed22bef2604f45241c09bbb8c8/tools/server/README.md);
this is not a promise of arbitrary external-provider compatibility.
Context configuration must match manifest; no fictitious per-request n_ctx setting is sent.
Actual template/context/threads/cache behavior must be independently verified in NB-08.

Preserve full raw response bytes as base64+SHA-256, parsed response and exact content whitespace.
Record timestamps, monotonic latency, reported usage, finish reason and truncation. TTFT
(nonstreaming), CPU/RAM and unavailable token measurements stay null. Server-reported decode
tokens/s differs from calculated completion_tokens/request_wall_time (end-to-end throughput).
No response correction/translation/reference substitution. Response cap8MiB.
Unexpected reasoning/tool output is PROMPT_TEMPLATE; it never silently enters history.

Reused response IDs across sessions produce SUSPECTED_CONTEXT_LEAKAGE. Source/history journals
also fail closed on mismatches. These guards do not prove semantic/model-cache isolation.
NB-08 owns a real contamination probe; no hidden canaries are inserted into approved prompts.

## Atomic artifacts and recovery

Run.json pins the plan. Requests/SESSION/TURN/ATTEMPT.json is fsynced BEFORE I/O; results/... is
a separate immutable record. Temp-file+link+directory fsync prevents partial JSON or overwrite.
Files600, new directories700; nonblocking flock permits one executor/run.
Summary.json is a replaceable derived view, never authoritative raw evidence.

Outcomes: ENDPOINT_UNAVAILABLE, TIMEOUT, TRANSPORT, INVALID_API_RESPONSE, SERVER_ERROR,
HTTP_ERROR, PROMPT_TEMPLATE, MISSING_CONTENT, TRUNCATED, INTERRUPTED_UNKNOWN,
SUSPECTED_CONTEXT_LEAKAGE; invalid inputs/state are INVALID_FIXTURE_OR_RUN.
Later turns become BLOCKED_BY_PRIOR_TURN when no valid prefix exists. No infrastructure error
becomes a model score.

Attempt budget defaults1, maximum3. Only refused-connection/server-error failures auto-retry
within that explicit budget. Timeout/transport uncertainty never auto-retries. A pending request
without result becomes INTERRUPTED_UNKNOWN on resume: the provider MAY have executed it.
Default resume blocks it. Explicit --retry-uncertain permits another attempt only within the
original budget and records authorization. Otherwise create a new run/--rerun-of.
Never edit the original budget or erase an uncertain attempt.

Completed prefixes are validated/reconstructed, never resent/duplicated. Failed, truncated or
uncertain responses never enter history. Corpus/config/selection/model/source changes cannot
silently reuse incompatible state. Local hashes detect accidental corruption, not a malicious
operator rewriting every file; no cryptographic third-party attestation is claimed.

## NB-08 handoff

Reuse [llm-lab.md](../../docs/operations/llm-lab.md) and
[ADR0043](../../docs/adr/0043-isolated-cpu-llm-lab.md); no reinstall/new infrastructure.
Installed-model.historical.json contains historical pinned weights/binary, Q4_K_M and2048 context.
Unknown current flags stay null; HISTORICAL_NOT_REVERIFIED is not current environment approval.
NB-08 supplies its independently verified manifest with current flags/time and NB08_ATTESTED.
Installed.config.json is a starting configuration, not an official frozen benchmark choice.
Review/freeze intended sampling before real runs.

After separately authorized CPU environment readiness, NB-08 can directly run one five-turn D05:

~~~bash
python3 -m native_llm_bench plan --runtime private/corpus-v1/runtime.json \
  --config fixtures/installed.config.json --model-manifest /PRIVATE/verified-model.json \
  --sessions D05
python3 -m native_llm_bench run --runtime private/corpus-v1/runtime.json \
  --config fixtures/installed.config.json --model-manifest /PRIVATE/verified-model.json \
  --sessions D05 --output runs
~~~

NB-07 does not execute these real commands. NB-08 owns startup, current hash/template/flags,
live RU/EN/five-turn smoke, CPU/RAM/token/cost monitoring, access verification and shutdown.

## Targeted verification / Functional DoD

~~~bash
python3 -m pytest -c pyproject.toml tests -q
python3 -m ruff check .
python3 -m ruff format --check .
git diff --check
~~~

Socket tests need permission to bind the fake; never skip them silently.
D1 HTTP history; D2 schema/import61-session contract; D3 leakage/direct-only; D4 seeded plans;
D5 interruption/recovery/immutability; D6 targeted tests; D7 CLI handoff; D8 isolated branch.
The format-only importer unit fixture is synthetic, not the authoritative corpus. Actual import
receipts are separate private evidence. No Full Regression, production suites or self-acceptance.
