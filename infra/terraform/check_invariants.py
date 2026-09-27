"""Focused static guardrails for security relationships Terraform cannot validate alone."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRODUCTION = ROOT / "production"
BOOTSTRAP = ROOT / "bootstrap"


def _read(name: str) -> str:
    return (PRODUCTION / name).read_text(encoding="utf-8")


def _read_bootstrap(name: str) -> str:
    return (BOOTSTRAP / name).read_text(encoding="utf-8")


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


def _variable(text: str, name: str) -> str:
    marker = f'variable "{name}"'
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f"Missing Terraform variable: {name}")
    end = text.find('\nvariable "', start + len(marker))
    return text[start:] if end < 0 else text[start:end]


iam = _read("iam.tf")
locals = _read("locals.tf")
networking = _read("networking.tf")
services = _read("services.tf")
storage = _read("storage.tf")
tasks = _read("tasks.tf")
variables = _read("variables.tf")
deploy_workflow = (ROOT.parents[1] / ".github/workflows/deploy-production.yml").read_text(
    encoding="utf-8"
)
plan_job_start = deploy_workflow.find("\n  plan:\n")
apply_job_start = deploy_workflow.find("\n  apply:\n")
if plan_job_start < 0 or apply_job_start < 0 or apply_job_start <= plan_job_start:
    raise SystemExit("Missing split production plan/apply jobs")
plan_job = deploy_workflow[plan_job_start:apply_job_start]
apply_job = deploy_workflow[apply_job_start:]
review_upload_start = plan_job.find("- name: Upload redacted plan review")
if review_upload_start < 0:
    raise SystemExit("Missing redacted plan review upload")
review_upload_step = plan_job[review_upload_start:]
bootstrap = _read_bootstrap("main.tf")

_require(storage, 'public_access_prevention    = "enforced"', "GCS public access prevention")
_require(storage, "uniform_bucket_level_access = true", "uniform bucket IAM")
_require(storage, "enabled = false", "Asset object versioning disabled")
_require(iam, 'for_each = toset(["api", "worker"])', "create/read limited to API and worker")
_require(iam, 'runtime["cleanup"].email', "separate cleanup delete authority")
_require(
    services,
    'ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"',
    "private worker ingress",
)
_require(
    services,
    'member   = "serviceAccount:${google_service_account.runtime["task"].email}"',
    "task-only worker invoker",
)
_forbid(
    services,
    "name     = google_cloud_run_v2_service.worker.name\n"
    '  role     = "roles/run.invoker"\n'
    '  member   = "allUsers"',
    "public worker invoker",
)
_require(tasks, "max_attempts       = var.task_max_attempts", "finite queue attempts")
_require(services, "max_instance_count = var.worker_max_instances", "bounded worker instances")
_require(
    services,
    "contains(local.openai_allowed_models, profile.model)",
    "API generation profiles constrained to worker model allowlist",
)

generation_profiles = _variable(variables, "generation_profiles_json")
allowed_models = _variable(variables, "openai_allowed_models")
stale_recovery = _variable(variables, "stale_recovery_seconds")
_forbid(generation_profiles, "\n  default", "implicit production generation profile")
_forbid(allowed_models, "\n  default", "implicit production worker model allowlist")
_require(stale_recovery, "default = 1800", "accepted 1800-second stale recovery default")
_require(
    deploy_workflow,
    "TF_VAR_generation_profiles_json: ${{ vars.GENERATION_PROFILES_JSON }}",
    "protected generation profile configuration",
)
_require(
    deploy_workflow,
    "TF_VAR_openai_allowed_models: ${{ vars.OPENAI_ALLOWED_MODELS }}",
    "protected worker model allowlist configuration",
)
_require(deploy_workflow, "actions: read", "environment protection API permission")

_require(
    locals,
    'var.dns_managed_zone != null && var.dns_managed_zone != ""',
    "null and empty DNS configuration disable managed records",
)
_require(networking, "count        = local.dns_records_enabled ? 1 : 0", "optional DNS records")
_forbid(networking, "var.dns_managed_zone == null ? 0 : 1", "empty DNS zone treated as enabled")

_require(plan_job, "environment: production-plan", "separate production plan environment")
_require(plan_job, "terraform -chdir=infra/terraform/production plan", "saved Terraform plan")
_require(
    plan_job,
    "/environments/${environment_name}",
    "deployment environment protection API lookup",
)
_require(
    plan_job,
    "\n          verify_environment production-plan\n",
    "actual plan-environment protection check",
)
_require(
    plan_job,
    "\n          verify_environment production\n",
    "actual apply-environment protection check",
)
_require(plan_job, '.type == "required_reviewers"', "mandatory deployment reviewers")
_require(plan_job, "(.reviewers | length) > 0", "at least one deployment reviewer")
_require(plan_job, ".prevent_self_review == true", "mandatory deployment self-review block")
_require(plan_job, ".deployment_branch_policy != null", "mandatory deployment branch policy")
environment_checks_end = plan_job.find("          verify_environment production\n")
cloud_auth_start = plan_job.find("google-github-actions/auth@v2")
terraform_plan_start = plan_job.find("terraform -chdir=infra/terraform/production plan")
if not 0 <= environment_checks_end < cloud_auth_start < terraform_plan_start:
    raise SystemExit(
        "Missing production invariant: deployment environment checks before cloud authentication "
        "and Terraform plan"
    )
_require(plan_job, "gcloud storage cp --if-generation-match=0", "create-only private plan upload")
_require(plan_job, "deployment-plans/", "private per-run plan-object namespace")
_require(review_upload_step, "actions/upload-artifact@v4", "redacted plan review artifact")
_require(review_upload_step, "production-plan-redacted.txt", "redacted review output only")
_require(review_upload_step, "retention-days: 1", "short-lived redacted review artifact")
_forbid(review_upload_step, "production.tfplan", "binary Terraform plan in GitHub artifact")
_forbid(
    plan_job,
    "terraform -chdir=infra/terraform/production apply",
    "Terraform apply before protected production approval",
)
_require(apply_job, "needs: plan", "apply waits for completed plan")
_require(apply_job, "environment: production", "protected production apply environment")
_forbid(apply_job, "actions/download-artifact", "binary plan download from GitHub artifacts")
_require(apply_job, 'gcloud storage cp "${plan_object}"', "private exact-plan download")
_require(apply_job, "EXPECTED_PLAN_SHA256", "exact plan checksum binding")
_require(apply_job, "EXPECTED_PLAN_GENERATION", "exact private object generation binding")
_require(apply_job, "EXPECTED_DEPLOYMENT_CONFIG_SHA256", "exact plan configuration binding")
_require(
    apply_job,
    "apply -input=false -auto-approve production.tfplan",
    "exact saved-plan apply",
)
_require(apply_job, 'gcloud storage rm "${plan_object}"', "private exact-plan cleanup")
_require(
    apply_job,
    '--if-generation-match="${EXPECTED_PLAN_GENERATION}"',
    "generation-conditional private plan cleanup",
)
_forbid(apply_job, " plan -", "re-planning after protected approval")
_require(apply_job, "required_dns_a_records", "external DNS record handoff")
_require(apply_job, '"${dns_managed}" != "true"', "external DNS readiness bypass")
_require(apply_job, "for attempt in $(seq 1 120)", "bounded HTTPS readiness polling")
_require(apply_job, 'certificate_status}" == "ACTIVE"', "managed certificate readiness")

_require(bootstrap, 'matches_prefix = ["deployment-plans/"]', "plan-object lifecycle isolation")
_require(bootstrap, "age            = 1", "one-day private plan-object retention")
_require(bootstrap, 'public_access_prevention    = "enforced"', "private plan storage")

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
