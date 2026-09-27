"""Focused static guardrails for security relationships Terraform cannot validate alone."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRODUCTION = ROOT / "production"


def _read(name: str) -> str:
    return (PRODUCTION / name).read_text(encoding="utf-8")


def _require(text: str, fragment: str, description: str) -> None:
    if fragment not in text:
        raise SystemExit(f"Missing production invariant: {description}")


def _forbid(text: str, fragment: str, description: str) -> None:
    if fragment in text:
        raise SystemExit(f"Forbidden production configuration: {description}")


def _resource(text: str, resource_type: str, name: str) -> str:
    marker = f'resource "{resource_type}" "{name}"'
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f"Missing Terraform resource: {resource_type}.{name}")
    end = text.find('\nresource "', start + len(marker))
    return text[start:] if end < 0 else text[start:end]


iam = _read("iam.tf")
services = _read("services.tf")
storage = _read("storage.tf")
tasks = _read("tasks.tf")

_require(storage, 'public_access_prevention    = "enforced"', "GCS public access prevention")
_require(storage, "uniform_bucket_level_access = true", "uniform bucket IAM")
_require(storage, "enabled = false", "Asset object versioning disabled")
_require(iam, 'for_each = toset(["api", "worker"])', "create/read limited to API and worker")
_require(iam, 'runtime["cleanup"].email', "separate cleanup delete authority")
_require(services, 'ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"', "private worker ingress")
_require(services, 'member   = "serviceAccount:${google_service_account.runtime["task"].email}"', "task-only worker invoker")
_forbid(services, 'name     = google_cloud_run_v2_service.worker.name\n  role     = "roles/run.invoker"\n  member   = "allUsers"', "public worker invoker")
_require(tasks, "max_attempts       = var.task_max_attempts", "finite queue attempts")
_require(services, "max_instance_count = var.worker_max_instances", "bounded worker instances")

openai_access = _resource(iam, "google_secret_manager_secret_iam_member", "openai_key")
_require(openai_access, 'runtime["worker"].email', "OpenAI secret limited to worker")
_forbid(openai_access, 'runtime["api"].email', "API OpenAI secret access")

cleanup_access = _resource(iam, "google_storage_bucket_iam_member", "asset_cleanup")
_require(cleanup_access, 'runtime["cleanup"].email', "cleanup object-delete identity")
_forbid(cleanup_access, 'runtime["api"].email', "API object delete")
_forbid(cleanup_access, 'runtime["worker"].email', "worker object delete")

database_access = _resource(iam, "google_secret_manager_secret_iam_member", "database_url")
_forbid(database_access, '"web"', "web Secret Manager access")
_forbid(database_access, '"task"', "task-delivery Secret Manager access")

print("Production Terraform safety invariants passed")
