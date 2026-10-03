# Knowledge Library durable artifacts

This directory is the repository-owned durable storage boundary for versioned Knowledge Library
validation fixtures and release metadata.

Rules:

- Git is authoritative for executable/versioned Knowledge Library artifacts used by CI.
- Google Drive is a human-facing synchronized copy, not the runtime source of truth.
- A Drive copy must preserve the repository path, Git commit SHA, artifact version and SHA-256 where
  applicable. Drive edits never silently replace Git artifacts.
- Production ACTIVE promotion remains governed by ADR 0028 and requires an exact runtime hash plus a
  complete all-PASS validation report.
- External evidence remains reference/provenance data; customer content and secrets must not be
  copied here.
- A new vertical slice must prove stable parameter targets and fail-closed behavior without changing
  the frozen Contract v1.0.0 architecture.

The first post-solitaire validation fixture is
`validation/three-stone-v1.0.0.json`. It validates the collection-scoped `{group_id}` contract
against a three-stone ring with one center stone and one side stone per side.

Google Drive synchronization is operationally separate from CI. Repository merge is allowed without
Drive connectivity; the sync record must not claim success until the external copy is actually
verified.
