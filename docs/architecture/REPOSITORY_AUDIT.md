# Repository audit — 2026-09-20

Repository: https://github.com/mlevin09/mmjewelai
Remote main at preparation: bd58f573b33658e102c40f4956159856276bcacd.
Original local checkout: C:\Users\user\OneDrive\Документы\GitHub\mmjewelai, clean main at 3dfd247, one commit behind remote.
Preparation uses a separate clone to preserve that checkout.

Exactly five files are tracked at the archive point: Dockerfile, Fork, README.md, docker-compose.yml, pyproject.toml.
README claims a backend, provider adapters and CI tests. app/, tests/, .github/ and .env.example are absent.
Dockerfile references missing app/; packaging also targets app. Therefore no runnable backend or passing test suite can be verified from this snapshot.

All five files are retained byte-for-byte. No cleanup, rewrite, dependency install or deployment is part of this preparation.
legacy-v1 (annotated tag) and archive/v1 point to the remote main snapshot, not to a claim of a complete working V1.
jewelai-v2 starts from that snapshot and adds documentation only.
main is not a push target.

Archive refs preserve committed files only. They cannot recover source that was never committed.
Repository access through the connector reports push access but not admin access. Branch protection is not configured by this task.

Verification: compare existing-file blob IDs with legacy-v1; diff must contain additions only; check Markdown links and final remote ref IDs.
