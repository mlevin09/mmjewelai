locals {
  prefix        = "jewelai-prod"
  web_origin    = "https://${var.web_domain}"
  api_origin    = "https://${var.api_domain}"
  oidc_issuer   = "https://${var.auth0_domain}/"
  oidc_jwks     = "https://${var.auth0_domain}/.well-known/jwks.json"
  oidc_audience = local.api_origin

  dns_records_enabled   = var.dns_managed_zone != null && var.dns_managed_zone != ""
  generation_profiles   = jsondecode(var.generation_profiles_json)
  openai_allowed_models = split(",", var.openai_allowed_models)

  services = toset([
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudtasks.googleapis.com",
    "compute.googleapis.com",
    "dns.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
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
