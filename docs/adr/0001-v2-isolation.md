# ADR 0001: Preserve V1 and isolate V2

Status: Accepted. Date: 2026-09-20.

## Context
The same repository must host V2 without breaking main or deleting existing files.

## Decision
Archive remote main at legacy-v1 and archive/v1. Add the foundation to jewelai-v2.
Subsequent work uses issue → feature branch → PR targeting jewelai-v2. Promotion to main is a separate release decision.

## Alternatives
A new repository loses continuity. An orphan branch loses convenient ancestry. An immediate main rewrite risks existing users.

## Consequences
V1 files remain in place and may describe unavailable code. The audit and V2 baseline distinguish target behavior from actual contents.
Archive refs must not be moved. Repository rulesets can enforce this later with admin access.

## Validation
All archive refs resolve to the original main commit; original blobs remain identical.
