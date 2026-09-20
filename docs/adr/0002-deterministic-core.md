# ADR 0002: One deterministic core with role adapters

Status: Accepted. Date: 2026-09-20.

## Context
Users with different expertise need consistent design constraints and appropriate questions.

## Decision
Version schema, roles, dictionary, questions and rules separately. Select semantic questions in code.
Use LLMs for language parsing and optional wording through validated interfaces, never as the authority for locks or readiness.
Knowledge estimates carry provenance and uncertainty.

## Alternatives
Six role-specific engines duplicate logic. Prompt-only orchestration cannot guarantee repeatable question selection.

## Consequences
Catalogs require expert review. Offline tests must establish deterministic behavior before provider integration.

## Validation
Identical input state and artifact versions produce the same decisions; locked updates and unsupported estimates are rejected.
