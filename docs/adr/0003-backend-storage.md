# ADR 0003: FastAPI, PostgreSQL and object storage

Status: Accepted. Date: 2026-09-20.

## Context
The eventual A/B MVP must retain lineage and reusable production foundations.

## Decision
Use FastAPI, PostgreSQL, SQLAlchemy/Alembic and GCS. Target Cloud Run/Cloud SQL when deploying.
Keep binary files in object storage and ownership/lineage metadata in PostgreSQL.
Do not provision infrastructure during foundation preparation.

## Alternatives
Image binaries in SQL add unnecessary storage coupling. A vector database cannot replace binary asset storage.

## Consequences
Authentication, signed asset access, migrations, idempotent workers, backups and retention need later implementation.
Queue selection remains open.

## Validation
Future persistence and asset issues must test tenant isolation and metadata-to-object relationships.
