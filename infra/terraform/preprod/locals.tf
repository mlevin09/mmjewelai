locals {
  prefix                   = "jewelai-preprod"
  web_origin               = "https://${var.web_domain}"
  api_origin               = "https://${var.api_domain}"
  identity_platform_issuer = "https://securetoken.google.com/${var.project_id}"

  dns_records_enabled       = var.dns_managed_zone != null && var.dns_managed_zone != ""
  generation_profiles       = jsondecode(var.generation_profiles_json)
  openai_generation_enabled = var.openai_allowed_models != ""
  openai_allowed_models     = local.openai_generation_enabled ? split(",", var.openai_allowed_models) : []
  google_generation_enabled = var.google_generative_language_allowed_models != ""
  google_allowed_models     = local.google_generation_enabled ? split(",", var.google_generative_language_allowed_models) : []

  services = toset([
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudtasks.googleapis.com",
    "compute.googleapis.com",
    "dns.googleapis.com",
    "firebase.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "identitytoolkit.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
    "storage.googleapis.com",
  ])

  service_accounts = {
    web       = "Static web runtime; no Google API permissions"
    api       = "Authenticated API runtime"
    worker    = "Private generation worker runtime"
    signer    = "Dedicated V4 signed-read identity"
    task      = "Cloud Tasks delivery identity"
    migration = "Database migration job"
    outbox    = "Generation dispatch outbox redrive job"
    stale     = "Stale GenerationRun recovery job"
    reconcile = "Generated Asset metadata reconciliation job"
    cleanup   = "Failed-run orphan cleanup job"
    scheduler = "Cloud Scheduler operational job invoker"
  }

  database_env = {
    DB_POOL_SIZE            = tostring(var.db_pool_size)
    DB_MAX_OVERFLOW         = tostring(var.db_max_overflow)
    DB_POOL_TIMEOUT_SECONDS = "30"
    DB_POOL_RECYCLE_SECONDS = "1800"
  }
}

resource "google_project_service" "production" {
  for_each           = local.services
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
