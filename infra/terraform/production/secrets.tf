resource "google_secret_manager_secret" "database_url" {
  project   = var.project_id
  secret_id = "jewelai-production-database-url"
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
  project   = var.project_id
  secret_id = "jewelai-production-openai-api-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.production]
}

resource "google_secret_manager_secret" "google_generative_language_api_key" {
  count     = local.google_generation_enabled ? 1 : 0
  project   = var.project_id
  secret_id = "jewelai-production-google-generative-language-api-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.production]
}
