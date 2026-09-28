resource "google_secret_manager_secret" "database_url" {
  project   = var.project_id
  secret_id = "jewelai-${var.deployment_environment}-database-url"
  replication {
    auto {}
  }
  depends_on = [google_project_service.production]
}

resource "google_secret_manager_secret_version" "database_url" {
  secret      = google_secret_manager_secret.database_url.id
  secret_data = local.database_url
}

resource "google_secret_manager_secret" "openai_api_key" {
  count     = local.openai_generation_enabled ? 1 : 0
  project   = var.project_id
  secret_id = "jewelai-${var.deployment_environment}-openai-api-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.production]
}

data "google_secret_manager_secret" "google_generative_language_api_key" {
  count     = local.google_generation_enabled ? 1 : 0
  project   = var.project_id
  secret_id = var.google_generative_language_secret_id
}


locals {
  google_generative_language_secret_resource_id = local.google_generation_enabled ? data.google_secret_manager_secret.google_generative_language_api_key[0].secret_id : null
}
