"""Bounded metadata-only reconciliation and failed-run orphan cleanup."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from jewelai_assets import (
    Asset,
    AssetConflictError,
    AssetContentType,
    AssetIngestionRequest,
    AssetKind,
    AssetStatus,
    AssetStorageConflictError,
    AssetStorageError,
    PrivateObjectMaintenance,
    PrivateObjectMetadata,
    PrivateObjectMetadataReader,
    adopt_stored_asset,
    build_object_key,
    generated_asset_id,
    validate_asset_object_key,
)
from jewelai_persistence import PersistenceRepository
from pydantic import BaseModel, ConfigDict

DEFAULT_RECONCILIATION_GRACE_SECONDS = 300
MIN_RECONCILIATION_GRACE_SECONDS = 60
MAX_RECONCILIATION_GRACE_SECONDS = 86_400
DEFAULT_ORPHAN_RETENTION_SECONDS = 604_800
MIN_ORPHAN_RETENTION_SECONDS = 86_400
MAX_ORPHAN_RETENTION_SECONDS = 7_776_000
DEFAULT_MAINTENANCE_BATCH_SIZE = 25
MAX_MAINTENANCE_BATCH_SIZE = 100


class MaintenanceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AssetReconciliationSummary(MaintenanceSummary):
    runs_inspected: int = 0
    runs_completed: int = 0
    assets_already_ready: int = 0
    assets_adopted: int = 0
    assets_completed_from_pending: int = 0
    objects_missing: int = 0
    conflicts: int = 0
    storage_failures: int = 0


class OrphanCleanupSummary(MaintenanceSummary):
    runs_inspected: int = 0
    runs_completed: int = 0
    objects_absent: int = 0
    objects_would_delete: int = 0
    objects_deleted: int = 0
    objects_referenced: int = 0
    objects_too_recent: int = 0
    conflicts: int = 0
    storage_failures: int = 0
    apply: bool


def reconcile_generated_assets(
    repository: PersistenceRepository,
    *,
    object_reader: PrivateObjectMetadataReader,
    grace_seconds: int = DEFAULT_RECONCILIATION_GRACE_SECONDS,
    batch_size: int = DEFAULT_MAINTENANCE_BATCH_SIZE,
    clock: Callable[[], datetime] | None = None,
) -> AssetReconciliationSummary:
    _bounded_int(
        "grace_seconds",
        grace_seconds,
        MIN_RECONCILIATION_GRACE_SECONDS,
        MAX_RECONCILIATION_GRACE_SECONDS,
    )
    _bounded_int("batch_size", batch_size, 1, MAX_MAINTENANCE_BATCH_SIZE)
    now = (clock or (lambda: datetime.now(UTC)))()
    cutoff = now - timedelta(seconds=grace_seconds)
    counts = AssetReconciliationSummary().model_dump()
    candidates = repository.list_generation_runs_for_asset_reconciliation(cutoff, batch_size)
    for candidate in candidates:
        counts["runs_inspected"] += 1
        run = candidate.run
        run_complete = True
        for output in run.result.outputs:
            asset_id = generated_asset_id(run.generation_run_id, output.ordinal)
            existing = repository.find_asset(asset_id, candidate.organization_id)
            if existing is not None:
                try:
                    _validate_generated_asset(
                        existing,
                        candidate.organization_id,
                        candidate.project_id,
                        run.session_id,
                        run.generation_run_id,
                        output.ordinal,
                        output.provider_output_id,
                    )
                except (AssetConflictError, ValueError):
                    counts["conflicts"] += 1
                    run_complete = False
                    continue
                if existing.status is AssetStatus.READY:
                    counts["assets_already_ready"] += 1
                    continue
                if existing.status is AssetStatus.FAILED:
                    counts["conflicts"] += 1
                    run_complete = False
                    continue
                try:
                    metadata = object_reader.inspect(existing.object_key)
                except AssetStorageConflictError:
                    counts["conflicts"] += 1
                    run_complete = False
                    continue
                except AssetStorageError:
                    counts["storage_failures"] += 1
                    run_complete = False
                    continue
                if metadata is None:
                    counts["objects_missing"] += 1
                    run_complete = False
                    continue
                if not _metadata_matches_asset(metadata, existing):
                    counts["conflicts"] += 1
                    run_complete = False
                    continue
                try:
                    adopt_stored_asset(
                        request=_request_for_output(
                            candidate.organization_id,
                            candidate.project_id,
                            run.session_id,
                            run.generation_run_id,
                            output.ordinal,
                            output.provider_output_id,
                            asset_id,
                            metadata.content_type,
                        ),
                        stored_metadata=metadata,
                        repository=repository,
                        clock=lambda: now,
                    )
                except AssetConflictError:
                    counts["conflicts"] += 1
                    run_complete = False
                    continue
                counts["assets_completed_from_pending"] += 1
                continue

            discovered, outcome = _discover_one_object(
                object_reader,
                candidate.organization_id,
                candidate.project_id,
                asset_id,
            )
            if outcome == "missing":
                counts["objects_missing"] += 1
                run_complete = False
                continue
            if outcome == "conflict":
                counts["conflicts"] += 1
                run_complete = False
                continue
            if outcome == "storage_failure":
                counts["storage_failures"] += 1
                run_complete = False
                continue
            try:
                adopt_stored_asset(
                    request=_request_for_output(
                        candidate.organization_id,
                        candidate.project_id,
                        run.session_id,
                        run.generation_run_id,
                        output.ordinal,
                        output.provider_output_id,
                        asset_id,
                        discovered.content_type,
                    ),
                    stored_metadata=discovered,
                    repository=repository,
                    clock=lambda: now,
                )
            except AssetConflictError:
                counts["conflicts"] += 1
                run_complete = False
                continue
            counts["assets_adopted"] += 1
        if run_complete and repository.mark_generation_assets_reconciled(
            run.generation_run_id, now
        ):
            counts["runs_completed"] += 1
    return AssetReconciliationSummary(**counts)


def cleanup_failed_generation_orphans(
    repository: PersistenceRepository,
    *,
    object_maintenance: PrivateObjectMaintenance,
    retention_seconds: int = DEFAULT_ORPHAN_RETENTION_SECONDS,
    batch_size: int = DEFAULT_MAINTENANCE_BATCH_SIZE,
    apply: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> OrphanCleanupSummary:
    _bounded_int(
        "retention_seconds",
        retention_seconds,
        MIN_ORPHAN_RETENTION_SECONDS,
        MAX_ORPHAN_RETENTION_SECONDS,
    )
    _bounded_int("batch_size", batch_size, 1, MAX_MAINTENANCE_BATCH_SIZE)
    if not isinstance(apply, bool):
        raise ValueError("apply must be a boolean")
    now = (clock or (lambda: datetime.now(UTC)))()
    cutoff = now - timedelta(seconds=retention_seconds)
    counts = OrphanCleanupSummary(apply=apply).model_dump()
    candidates = repository.list_failed_generation_runs_for_orphan_cleanup(cutoff, batch_size)
    for candidate in candidates:
        counts["runs_inspected"] += 1
        run = candidate.run
        run_clean = True
        for ordinal in range(1, run.configuration.output_count + 1):
            asset_id = generated_asset_id(run.generation_run_id, ordinal)
            if repository.find_asset(asset_id, candidate.organization_id) is not None:
                counts["objects_referenced"] += 1
                run_clean = False
                continue
            discovered, outcome = _discover_one_object(
                object_maintenance,
                candidate.organization_id,
                candidate.project_id,
                asset_id,
            )
            if outcome == "missing":
                counts["objects_absent"] += 1
                continue
            if outcome == "conflict":
                counts["conflicts"] += 1
                run_clean = False
                continue
            if outcome == "storage_failure":
                counts["storage_failures"] += 1
                run_clean = False
                continue
            if discovered.created_at > cutoff:
                counts["objects_too_recent"] += 1
                run_clean = False
                continue
            if not apply:
                counts["objects_would_delete"] += 1
                run_clean = False
                continue
            try:
                deleted = object_maintenance.delete_if_version(
                    discovered.object_key, discovered.version_token
                )
            except AssetStorageConflictError:
                counts["conflicts"] += 1
                run_clean = False
                continue
            except AssetStorageError:
                counts["storage_failures"] += 1
                run_clean = False
                continue
            if deleted:
                counts["objects_deleted"] += 1
            else:
                counts["objects_absent"] += 1
        if (
            apply
            and run_clean
            and repository.mark_generation_orphan_cleanup_completed(run.generation_run_id, now)
        ):
            counts["runs_completed"] += 1
    return OrphanCleanupSummary(**counts)


def _discover_one_object(reader, organization_id, project_id, asset_id):
    found = []
    try:
        for content_type in AssetContentType:
            metadata = reader.inspect(
                build_object_key(organization_id, project_id, asset_id, content_type)
            )
            if metadata is not None:
                found.append(metadata)
    except AssetStorageConflictError:
        return None, "conflict"
    except AssetStorageError:
        return None, "storage_failure"
    if not found:
        return None, "missing"
    if len(found) != 1:
        return None, "conflict"
    return found[0], "found"


def _request_for_output(
    organization_id,
    project_id,
    session_id,
    generation_run_id,
    ordinal,
    provider_output_id,
    asset_id,
    content_type,
):
    return AssetIngestionRequest(
        asset_id=asset_id,
        organization_id=organization_id,
        project_id=project_id,
        session_id=session_id,
        kind=AssetKind.GENERATED,
        declared_content_type=content_type,
        generation_run_id=generation_run_id,
        generation_output_ordinal=ordinal,
        provider_output_id=provider_output_id,
    )


def _validate_generated_asset(
    asset: Asset,
    organization_id,
    project_id,
    session_id,
    generation_run_id,
    ordinal,
    provider_output_id,
) -> None:
    validate_asset_object_key(asset)
    expected = (
        organization_id,
        project_id,
        session_id,
        AssetKind.GENERATED,
        generation_run_id,
        ordinal,
        provider_output_id,
    )
    actual = (
        asset.organization_id,
        asset.project_id,
        asset.session_id,
        asset.kind,
        asset.generation_run_id,
        asset.generation_output_ordinal,
        asset.provider_output_id,
    )
    if actual != expected:
        raise AssetConflictError("Generated Asset lineage conflicts with GenerationResult")


def _metadata_matches_asset(metadata: PrivateObjectMetadata, asset: Asset) -> bool:
    return (
        metadata.object_key,
        metadata.content_type,
        metadata.content_hash,
        metadata.byte_size,
    ) == (asset.object_key, asset.content_type, asset.content_hash, asset.byte_size)


def _bounded_int(name: str, value: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value
