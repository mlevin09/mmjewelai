locals {
  api_environment = merge(local.database_env, {
    JEWELAI_ENVIRONMENT                   = var.deployment_environment
    JEWELAI_REPOSITORY_ROOT               = "/app"
    GCP_PROJECT_ID                        = var.project_id
    GCS_ASSET_BUCKET                      = google_storage_bucket.assets.name
    GCS_SIGNING_SERVICE_ACCOUNT_EMAIL     = google_service_account.runtime["signer"].email
    AUTH_PROVIDER                         = "identity_platform"
    IDENTITY_PLATFORM_PROJECT_ID          = var.project_id
    WEB_ALLOWED_ORIGINS                   = local.web_origin
    ASSET_UPLOAD_MAX_BYTES                = tostring(var.asset_upload_max_bytes)
    HTTP_MAX_REQUEST_BYTES                = tostring(var.http_max_request_bytes)
    CLOUD_TASKS_PROJECT_ID                = var.project_id
    CLOUD_TASKS_LOCATION                  = var.region
    CLOUD_TASKS_QUEUE_ID                  = google_cloud_tasks_queue.generation.name
    GENERATION_WORKER_TASK_URL            = "${google_cloud_run_v2_service.worker.uri}/internal/generation-tasks/execute"
    GENERATION_TASK_SERVICE_ACCOUNT_EMAIL = google_service_account.runtime["task"].email
    GENERATION_TASK_OIDC_AUDIENCE         = google_cloud_run_v2_service.worker.uri
    GENERATION_PROFILES_JSON              = var.generation_profiles_json
    }, local.google_generation_enabled ? {
    TEXT_UNDERSTANDING_PROVIDER               = "google"
    GOOGLE_TEXT_UNDERSTANDING_MODEL           = "gemini-3.1-flash-lite"
    GOOGLE_TEXT_UNDERSTANDING_TIMEOUT_SECONDS = "30"
  } : {})

  worker_environment = merge(local.database_env, {
    JEWELAI_ENVIRONMENT = var.deployment_environment
    GCP_PROJECT_ID      = var.project_id
    GCS_ASSET_BUCKET    = google_storage_bucket.assets.name
    }, local.openai_generation_enabled ? {
    OPENAI_IMAGE_ALLOWED_MODELS  = var.openai_allowed_models
    OPENAI_IMAGE_TIMEOUT_SECONDS = "180"
    } : {}, local.google_generation_enabled ? {
    GOOGLE_GENERATIVE_LANGUAGE_ALLOWED_MODELS  = var.google_generative_language_allowed_models
    GOOGLE_GENERATIVE_LANGUAGE_TIMEOUT_SECONDS = "180"
  } : {})

  web_runtime_config = jsonencode({
    apiBaseUrl                 = local.api_origin
    authProvider               = "identity_platform"
    identityPlatformApiKey     = data.google_firebase_web_app_config.jewelai.api_key
    identityPlatformAuthDomain = data.google_firebase_web_app_config.jewelai.auth_domain
    identityPlatformProjectId  = var.project_id
    identityPlatformAppId      = google_firebase_web_app.jewelai.app_id
  })
}

resource "google_cloud_run_v2_service" "api" {
  project              = var.project_id
  name                 = "${local.prefix}-api"
  location             = var.region
  ingress              = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  default_uri_disabled = true
  deletion_protection  = true

  template {
    service_account                  = google_service_account.runtime["api"].email
    timeout                          = "60s"
    max_instance_request_concurrency = var.api_concurrency

    scaling {
      min_instance_count = var.api_min_instances
      max_instance_count = var.api_max_instances
    }

    containers {
      image = var.api_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.api_environment
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }

      dynamic "env" {
        for_each = local.google_generation_enabled ? [1] : []
        content {
          name = "GOOGLE_GENERATIVE_LANGUAGE_API_KEY"
          value_source {
            secret_key_ref {
              secret  = local.google_generative_language_secret_resource_id
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      startup_probe {
        initial_delay_seconds = 2
        timeout_seconds       = 2
        period_seconds        = 5
        failure_threshold     = 12
        http_get {
          path = "/health"
          port = 8080
        }
      }

      liveness_probe {
        timeout_seconds   = 2
        period_seconds    = 10
        failure_threshold = 3
        http_get {
          path = "/health"
          port = 8080
        }
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.production.connection_name]
      }
    }
  }

  lifecycle {
    precondition {
      condition     = (var.api_max_instances + var.worker_max_instances + 5) * (var.db_pool_size + var.db_max_overflow) <= var.database_max_connections - 10
      error_message = "API, worker, and five job pool capacity must leave at least ten Cloud SQL connections for operators."
    }

    precondition {
      condition = alltrue([
        for profile in local.generation_profiles :
        try(
          (profile.provider == "openai" && contains(local.openai_allowed_models, profile.model)) ||
          (profile.provider == "google" && contains(local.google_allowed_models, profile.model)),
          false
        )
      ])
      error_message = "Every generation profile must use an enabled provider and an exactly allowlisted model."
    }
  }

  depends_on = [google_project_service.production]
}

resource "google_cloud_run_v2_service" "worker" {
  project             = var.project_id
  name                = "${local.prefix}-generation-worker"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = true

  template {
    service_account                  = google_service_account.runtime["worker"].email
    timeout                          = "${var.worker_request_timeout_seconds}s"
    max_instance_request_concurrency = 1

    scaling {
      min_instance_count = var.worker_min_instances
      max_instance_count = var.worker_max_instances
    }

    containers {
      image = var.worker_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.worker_environment
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }

      dynamic "env" {
        for_each = local.openai_generation_enabled ? [1] : []
        content {
          name = "OPENAI_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.openai_api_key[0].secret_id
              version = "latest"
            }
          }
        }
      }

      dynamic "env" {
        for_each = local.google_generation_enabled ? [1] : []
        content {
          name = "GOOGLE_GENERATIVE_LANGUAGE_API_KEY"
          value_source {
            secret_key_ref {
              secret  = local.google_generative_language_secret_resource_id
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      startup_probe {
        initial_delay_seconds = 2
        timeout_seconds       = 2
        period_seconds        = 5
        failure_threshold     = 12
        http_get {
          path = "/health"
          port = 8080
        }
      }

      liveness_probe {
        timeout_seconds   = 2
        period_seconds    = 10
        failure_threshold = 3
        http_get {
          path = "/health"
          port = 8080
        }
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.production.connection_name]
      }
    }
  }

  depends_on = [google_project_service.production]
}

resource "google_cloud_run_v2_service" "web" {
  project              = var.project_id
  name                 = "${local.prefix}-web"
  location             = var.region
  ingress              = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  default_uri_disabled = true
  deletion_protection  = true

  template {
    service_account                  = google_service_account.runtime["web"].email
    timeout                          = "30s"
    max_instance_request_concurrency = var.web_concurrency

    scaling {
      min_instance_count = var.web_min_instances
      max_instance_count = var.web_max_instances
    }

    containers {
      image = var.web_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "256Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name  = "JEWELAI_WEB_CONFIG_JSON"
        value = local.web_runtime_config
      }

      startup_probe {
        timeout_seconds   = 2
        period_seconds    = 5
        failure_threshold = 12
        http_get {
          path = "/health"
          port = 8080
        }
      }

      liveness_probe {
        timeout_seconds   = 2
        period_seconds    = 10
        failure_threshold = 3
        http_get {
          path = "/health"
          port = 8080
        }
      }
    }
  }

  depends_on = [google_project_service.production]
}

resource "google_cloud_run_v2_service_iam_member" "public_api" {
  project  = var.project_id
  location = google_cloud_run_v2_service.api.location
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "public_web" {
  project  = var.project_id
  location = google_cloud_run_v2_service.web.location
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "task_worker" {
  project  = var.project_id
  location = google_cloud_run_v2_service.worker.location
  name     = google_cloud_run_v2_service.worker.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.runtime["task"].email}"
}
