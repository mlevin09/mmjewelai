"""Focused static guardrails for security relationships Terraform cannot validate alone."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRODUCTION = ROOT / "production"
PREPROD = ROOT / "preprod"
BOOTSTRAP = ROOT / "bootstrap"
PREPROD_BOOTSTRAP = ROOT / "preprod-bootstrap"


def _read(name: str) -> str:
    return (PRODUCTION / name).read_text(encoding="utf-8")


def _read_bootstrap(name: str) -> str:
    return (BOOTSTRAP / name).read_text(encoding="utf-8")


def _read_preprod(name: str) -> str:
    return (PREPROD / name).read_text(encoding="utf-8")


def _read_preprod_bootstrap(name: str) -> str:
    return (PREPROD_BOOTSTRAP / name).read_text(encoding="utf-8")


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
secrets = _read("secrets.tf")
storage = _read("storage.tf")
tasks = _read("tasks.tf")
variables = _read("variables.tf")
preprod_iam = _read_preprod("iam.tf")
preprod_locals = _read_preprod("locals.tf")
preprod_services = _read_preprod("services.tf")
preprod_secrets = _read_preprod("secrets.tf")
preprod_storage = _read_preprod("storage.tf")
preprod_tasks = _read_preprod("tasks.tf")
preprod_variables = _read_preprod("variables.tf")
preprod_versions = _read_preprod("versions.tf")
preprod_identity = _read_preprod("identity_platform.tf")
preprod_tfvars_example = _read_preprod("terraform.tfvars.example")
deploy_workflow = (ROOT.parents[1] / ".github/workflows/deploy-production.yml").read_text(
    encoding="utf-8"
)
preprod_workflow = (ROOT.parents[1] / ".github/workflows/deploy-preprod.yml").read_text(
    encoding="utf-8"
)
preprod_deployment_request = (
    ROOT.parents[1] / ".github/preprod-deployment-request.json"
).read_text(encoding="utf-8")
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
preprod_bootstrap = _read_preprod_bootstrap("main.tf")
preprod_bootstrap_variables = _read_preprod_bootstrap("variables.tf")
preprod_bootstrap_outputs = _read_preprod_bootstrap("outputs.tf")

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
    '(profile.provider == "openai" && contains(local.openai_allowed_models, profile.model))',
    "OpenAI generation profiles constrained to worker model allowlist",
)
_require(
    services,
    '(profile.provider == "google" && contains(local.google_allowed_models, profile.model))',
    "Google generation profiles constrained to worker model allowlist",
)

generation_profiles = _variable(variables, "generation_profiles_json")
allowed_models = _variable(variables, "openai_allowed_models")
google_allowed_models = _variable(variables, "google_generative_language_allowed_models")
preprod_deployment_environment = _variable(preprod_variables, "deployment_environment")
preprod_project_id = _variable(preprod_variables, "project_id")
preprod_region = _variable(preprod_variables, "region")
preprod_asset_location = _variable(preprod_variables, "asset_location")
preprod_openai_allowed_models = _variable(preprod_variables, "openai_allowed_models")
preprod_google_allowed_models = _variable(
    preprod_variables, "google_generative_language_allowed_models"
)
preprod_google_secret_id = _variable(preprod_variables, "google_generative_language_secret_id")
stale_recovery = _variable(variables, "stale_recovery_seconds")
_forbid(generation_profiles, "\n  default", "implicit production generation profile")
_forbid(allowed_models, "\n  default", "implicit production worker model allowlist")
_require(
    google_allowed_models,
    'default     = ""',
    "Google provider disabled unless explicitly configured",
)
for google_model in (
    "gemini-3.1-flash-lite-image",
    "gemini-3.1-flash-image",
    "gemini-3-pro-image",
):
    _require(google_allowed_models, google_model, f"Google model allowlist: {google_model}")
_require(stale_recovery, "default = 1800", "accepted 1800-second stale recovery default")
_require(
    preprod_deployment_environment,
    'default     = "preprod"',
    "fixed preprod deployment identity",
)
_require(
    preprod_project_id,
    'var.project_id == "mmjewellai-preprod"',
    "Terraform-level exact preprod project guard",
)
_require(preprod_region, 'default     = "europe-west1"', "fixed preprod Europe region")
_require(
    preprod_asset_location,
    'default     = "EUROPE-WEST1"',
    "fixed preprod Europe Asset location",
)
_require(
    preprod_tfvars_example,
    "europe-west1-docker.pkg.dev/mmjewellai-preprod/jewelai-preprod/",
    "preprod Europe Artifact Registry example",
)
_forbid(preprod_tfvars_example, "us-central1", "US Central preprod example dependency")
_forbid(preprod_tfvars_example, "US-CENTRAL1", "US Central preprod Asset dependency")
_require(
    preprod_google_secret_id,
    'default     = "jewelai-preprod-google-generative-language-api-key"',
    "exact existing preprod Google secret ID",
)
_require(
    preprod_openai_allowed_models,
    'default     = ""',
    "OpenAI independently optional in preprod",
)
_require(
    preprod_identity,
    'resource "google_identity_platform_config" "preprod"',
    "preprod Identity Platform configuration",
)
_require(preprod_identity, "enabled           = true", "preprod email/password sign-in")
_require(
    preprod_identity,
    "authorized_domains = distinct([",
    "preprod authorized browser domains",
)
_forbid(preprod_versions, "auth0/auth0", "Auth0 provider in preprod")
_forbid(preprod_workflow, "AUTH0_", "Auth0 credentials in preprod workflow")
_forbid(preprod_workflow, "TF_VAR_auth0_domain", "Auth0 domain in preprod fingerprint")
_require(
    preprod_workflow,
    "- .github/preprod-deployment-request.json",
    "auditable preprod push trigger",
)
_require(
    preprod_workflow,
    "github.event_name == 'push' || inputs.confirm_sha == github.sha",
    "exact manual or branch-push deployment SHA guard",
)
_require(
    preprod_workflow,
    "jq -cS . .github/preprod-deployment-request.json",
    "validated preprod deployment request",
)
_require(preprod_deployment_request, '"environment": "preprod"', "preprod request environment")
_require(
    preprod_deployment_request,
    '"verify_external_dns_https": false',
    "initial external-DNS deployment request",
)
_require(
    preprod_workflow,
    "Verify Identity Platform configuration",
    "preprod Identity Platform readiness check",
)
_require(
    preprod_services,
    'AUTH_PROVIDER                         = "identity_platform"',
    "preprod API Identity Platform verifier selection",
)
_require(
    preprod_services,
    'authProvider               = "identity_platform"',
    "preprod web Identity Platform selection",
)
for google_model in (
    "gemini-3.1-flash-lite-image",
    "gemini-3.1-flash-image",
    "gemini-3-pro-image",
):
    _require(
        preprod_google_allowed_models,
        google_model,
        f"preprod Google model allowlist: {google_model}",
    )
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
_require(
    deploy_workflow,
    "TF_VAR_google_generative_language_allowed_models: "
    "${{ vars.GOOGLE_GENERATIVE_LANGUAGE_ALLOWED_MODELS }}",
    "protected optional Google model allowlist configuration",
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

preprod_plan_start = preprod_workflow.find("\n  plan:\n")
preprod_apply_start = preprod_workflow.find("\n  apply:\n")
if preprod_plan_start < 0 or preprod_apply_start <= preprod_plan_start:
    raise SystemExit("Missing split preprod plan/apply jobs")
preprod_plan = preprod_workflow[preprod_plan_start:preprod_apply_start]
preprod_apply = preprod_workflow[preprod_apply_start:]
preprod_review_start = preprod_plan.find("- name: Upload redacted plan review")
if preprod_review_start < 0:
    raise SystemExit("Missing preprod redacted plan review upload")
preprod_review = preprod_plan[preprod_review_start:]

_require(preprod_workflow, "group: preprod-deployment", "isolated preprod concurrency")
_require(
    preprod_workflow, 'test "${PROJECT_ID}" = "mmjewellai-preprod"', "exact preprod project guard"
)
_require(preprod_workflow, "TF_VAR_deployment_environment: preprod", "preprod runtime identity")
_require(
    preprod_workflow,
    "GOOGLE_GENERATIVE_LANGUAGE_ALLOWED_MODELS: "
    "gemini-3.1-flash-lite-image,gemini-3.1-flash-image,gemini-3-pro-image",
    "exact preprod Google model allowlist",
)
_require(
    preprod_secrets,
    'data "google_secret_manager_secret" "google_generative_language_api_key"',
    "existing Google secret metadata lookup",
)
_require(
    preprod_services,
    "GOOGLE_GENERATIVE_LANGUAGE_ALLOWED_MODELS  = var.google_generative_language_allowed_models",
    "Google allowlist passed to the worker",
)
_require(
    preprod_services,
    "for_each = local.openai_generation_enabled ? [1] : []",
    "conditional preprod OpenAI secret mount",
)
_require(
    preprod_services,
    'name = "GOOGLE_GENERATIVE_LANGUAGE_API_KEY"',
    "Google API key mounted only as worker secret environment",
)
_require(
    preprod_workflow,
    "TF_VAR_google_generative_language_secret_id: "
    "jewelai-preprod-google-generative-language-api-key",
    "existing preprod Google secret ID",
)
_require(preprod_plan, "environment: preprod", "single preprod environment for plan")
_require(preprod_apply, "environment: preprod", "protected preprod apply environment")
_require(preprod_plan, "verify_environment preprod", "preprod environment protection check")
_require(preprod_plan, ".deployment_branch_policy != null", "preprod branch policy")
_forbid(preprod_plan, '.type == "required_reviewers"', "preprod required-reviewer gate")
_forbid(preprod_plan, ".prevent_self_review", "preprod prevent-self-review gate")
_forbid(preprod_workflow, "preprod-plan", "separate preprod-plan environment concept")
preprod_environment_checks_end = preprod_plan.find("          verify_environment preprod\n")
preprod_cloud_auth_start = preprod_plan.find("google-github-actions/auth@v2")
preprod_plan_start_command = preprod_plan.find("terraform -chdir=infra/terraform/preprod plan")
if not 0 <= preprod_environment_checks_end < preprod_cloud_auth_start < preprod_plan_start_command:
    raise SystemExit(
        "Missing preprod invariant: environment checks before cloud authentication and plan"
    )
_require(preprod_workflow, '-backend-config="prefix=preprod/platform"', "isolated preprod state")
_require(
    preprod_plan, "gcloud storage cp --if-generation-match=0", "create-only preprod plan upload"
)
_require(preprod_plan, "deployment-plans/preprod/", "isolated private preprod plan namespace")
_require(preprod_review, "actions/upload-artifact@v4", "preprod redacted review artifact")
_require(preprod_review, "preprod-terraform-plan-redacted.txt", "preprod redacted output only")
_forbid(preprod_review, "preprod.tfplan", "binary preprod plan in GitHub artifact")
_require(preprod_apply, "EXPECTED_PLAN_SHA256", "preprod exact-plan checksum binding")
_require(preprod_apply, "EXPECTED_PLAN_GENERATION", "preprod plan-object generation binding")
_require(
    preprod_apply,
    "EXPECTED_DEPLOYMENT_CONFIG_SHA256",
    "preprod plan configuration binding",
)
_require(
    preprod_apply,
    "apply -input=false -auto-approve preprod.tfplan",
    "exact generated preprod plan apply",
)
_forbid(preprod_apply, " plan -", "preprod re-planning after exact plan generation")
_forbid(preprod_workflow, "environment: production", "production GitHub Environment use")
_forbid(
    preprod_workflow,
    "jewelai-production-google-generative-language-api-key",
    "production Google secret use",
)
_forbid(deploy_workflow, "mmjewellai-preprod", "preprod project in production workflow")
_require(preprod_versions, 'prefix = "preprod/platform"', "preprod backend state prefix")
_require(
    preprod_locals, 'prefix                   = "jewelai-preprod"', "preprod resource namespace"
)
_require(
    preprod_storage,
    'public_access_prevention    = "enforced"',
    "preprod GCS public access prevention",
)
_require(preprod_storage, "uniform_bucket_level_access = true", "preprod uniform bucket IAM")
_require(
    preprod_tasks, "max_attempts       = var.task_max_attempts", "preprod finite queue attempts"
)
_require(
    preprod_services,
    'ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"',
    "preprod private worker ingress",
)
_require(
    preprod_iam,
    'runtime["cleanup"].email',
    "preprod separate cleanup delete authority",
)
_forbid(
    preprod_secrets,
    'resource "google_secret_manager_secret" "google_generative_language_api_key"',
    "preprod recreation of existing Google secret",
)

_require(bootstrap, 'matches_prefix = ["deployment-plans/"]', "plan-object lifecycle isolation")
_require(bootstrap, "age            = 1", "one-day private plan-object retention")
_require(bootstrap, 'public_access_prevention    = "enforced"', "private plan storage")
_forbid(bootstrap, "mmjewellai-preprod", "preprod identity in production bootstrap")

preprod_bootstrap_project = _variable(preprod_bootstrap_variables, "project_id")
preprod_bootstrap_region = _variable(preprod_bootstrap_variables, "region")
preprod_bootstrap_state_bucket = _variable(preprod_bootstrap_variables, "state_bucket_name")
preprod_bootstrap_asset_bucket = _variable(preprod_bootstrap_variables, "asset_bucket_name")
preprod_bootstrap_repository = _variable(
    preprod_bootstrap_variables, "artifact_registry_repository"
)
preprod_bootstrap_github_repository = _variable(preprod_bootstrap_variables, "github_repository")
preprod_bootstrap_github_branch = _variable(preprod_bootstrap_variables, "github_deploy_branch")
_require(
    preprod_bootstrap_project,
    'default     = "mmjewellai-preprod"',
    "hard-bound preprod bootstrap project default",
)
_require(
    preprod_bootstrap_project,
    'var.project_id == "mmjewellai-preprod"',
    "hard-bound preprod bootstrap project validation",
)
_require(
    preprod_bootstrap_region,
    'default     = "europe-west1"',
    "hard-bound preprod bootstrap region default",
)
_require(
    preprod_bootstrap_region,
    'var.region == "europe-west1"',
    "hard-bound preprod bootstrap region validation",
)
_require(
    preprod_bootstrap,
    'workload_identity_pool_id = "jewelai-preprod-github"',
    "isolated preprod WIF pool",
)
_require(
    preprod_bootstrap,
    'workload_identity_pool_provider_id = "github-oidc"',
    "preprod GitHub OIDC provider",
)
_require(
    preprod_bootstrap,
    "assertion.repository == '${var.github_repository}' && "
    "assertion.ref == '${var.github_deploy_branch}'",
    "preprod exact repository and branch federation condition",
)
_require(
    preprod_bootstrap_state_bucket,
    'default     = "mmjewellai-preprod-tfstate"',
    "preferred deterministic preprod state bucket",
)
_require(
    preprod_bootstrap_asset_bucket,
    'default     = "mmjewellai-preprod-assets"',
    "preferred deterministic preprod Asset bucket",
)
_require(
    preprod_bootstrap_repository,
    'default     = "jewelai-preprod"',
    "exact preprod Artifact Registry repository",
)
_require(
    preprod_bootstrap_github_repository,
    'default     = "mlevin09/mmjewelai"',
    "preprod exact GitHub repository",
)
_require(
    preprod_bootstrap_github_branch,
    'default     = "refs/heads/jewelai-v2"',
    "preprod exact deployment branch",
)
_require(
    preprod_bootstrap,
    'account_id   = "jewelai-preprod-deployer"',
    "isolated preprod deployer",
)
_forbid(preprod_bootstrap, "jewelai-prod-deployer", "production deployer in preprod bootstrap")
_forbid(preprod_bootstrap, '"roles/owner"', "Owner role in preprod bootstrap")
_forbid(preprod_bootstrap, '"roles/editor"', "Editor role in preprod bootstrap")
_require(
    preprod_bootstrap,
    '"roles/firebase.editor"',
    "preprod deployer Firebase management role",
)
_require(
    preprod_bootstrap,
    '"roles/identitytoolkit.editor"',
    "preprod deployer Identity Platform management role",
)
_forbid(
    preprod_bootstrap,
    'resource "google_storage_bucket" "assets"',
    "Asset bucket creation outside main preprod stack",
)
_require(
    preprod_bootstrap,
    'matches_prefix = ["deployment-plans/"]',
    "preprod exact-plan lifecycle isolation",
)
_require(
    preprod_bootstrap,
    'public_access_prevention    = "enforced"',
    "private preprod state storage",
)
_require(
    preprod_bootstrap,
    'role = "roles/storage.admin"',
    "bucket-scoped state IAM administration for repeatable bootstrap plans",
)
_forbid(
    preprod_bootstrap,
    'role = "roles/storage.legacyBucketReader"',
    "legacy state bucket IAM role that cannot refresh the authoritative policy",
)
_require(preprod_bootstrap, "force_destroy               = false", "durable preprod state bucket")
for output_name in (
    "state_bucket_name",
    "artifact_registry_repository",
    "workload_identity_provider",
    "deployment_service_account",
    "asset_bucket_name",
):
    _require(
        preprod_bootstrap_outputs,
        f'output "{output_name}"',
        f"preprod bootstrap {output_name} output",
    )

openai_access = _resource(iam, "google_secret_manager_secret_iam_member", "openai_key")
_require(openai_access, 'runtime["worker"].email', "OpenAI secret limited to worker")
_forbid(openai_access, 'runtime["api"].email', "API OpenAI secret access")

google_access = _resource(
    iam,
    "google_secret_manager_secret_iam_member",
    "google_generative_language_key",
)
_require(google_access, 'runtime["worker"].email', "Google secret limited to worker")
_forbid(google_access, 'runtime["api"].email', "API Google secret access")

preprod_google_access = _resource(
    preprod_iam,
    "google_secret_manager_secret_iam_member",
    "google_generative_language_key",
)
_require(
    preprod_google_access,
    'runtime["worker"].email',
    "preprod Google secret limited to worker",
)
_forbid(preprod_google_access, 'runtime["api"].email', "preprod API Google secret access")

cleanup_access = _resource(iam, "google_storage_bucket_iam_member", "asset_cleanup")
_require(cleanup_access, 'runtime["cleanup"].email', "cleanup object-delete identity")
_forbid(cleanup_access, 'runtime["api"].email', "API object delete")
_forbid(cleanup_access, 'runtime["worker"].email', "worker object delete")

database_access = _resource(iam, "google_secret_manager_secret_iam_member", "database_url")
_forbid(database_access, '"web"', "web Secret Manager access")
_forbid(database_access, '"task"', "task-delivery Secret Manager access")

print("Production, preprod bootstrap, and preprod Terraform safety invariants passed")
