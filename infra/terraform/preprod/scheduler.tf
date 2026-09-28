locals {
  job_database_environment = merge(local.database_env, {
    JEWELAI_ENVIRONMENT = var.deployment_environment
    GCP_PROJECT_ID      = var.project_id
  })
  job_queue_environment = merge(local.job_database_environment, {
    CLOUD_TASKS_PROJECT_ID                = var.project_id
    CLOUD_TASKS_LOCATION                  = var.region
    CLOUD_TASKS_QUEUE_ID                  = google_cloud_tasks_queue.generation.name
    GENERATION_WORKER_TASK_URL            = "${google_cloud_run_v2_service.worker.uri}/internal/generation-tasks/execute"
    GENERATION_TASK_SERVICE_ACCOUNT_EMAIL = google_service_account.runtime["task"].email
    GENERATION_TASK_OIDC_AUDIENCE         = google_cloud_run_v2_service.worker.uri
  })
  scheduled_jobs = {
    outbox    = google_cloud_run_v2_job.outbox.name
    stale     = google_cloud_run_v2_job.stale.name
    reconcile = google_cloud_run_v2_job.reconcile.name
    cleanup   = google_cloud_run_v2_job.cleanup.name
  }
  schedules = {
    outbox    = var.outbox_schedule
    stale     = var.stale_recovery_schedule
    reconcile = var.asset_reconciliation_schedule
    cleanup   = var.orphan_cleanup_schedule
  }
}

resource "google_cloud_run_v2_job" "migration" {
  project             = var.project_id
  name                = "${local.prefix}-migration"
  location            = var.region
  deletion_protection = true

  template {
    task_count = 1
    template {
      service_account = google_service_account.runtime["migration"].email
      timeout         = "600s"
      max_retries     = 0

      containers {
        image   = var.api_image
        command = ["alembic"]
        args    = ["-c", "packages/persistence/alembic.ini", "upgrade", "head"]

        dynamic "env" {
          for_each = local.job_database_environment
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
        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.production.connection_name]
        }
      }
    }
  }
}

resource "google_cloud_run_v2_job" "outbox" {
  project             = var.project_id
  name                = "${local.prefix}-outbox-redrive"
  location            = var.region
  deletion_protection = true

  template {
    task_count = 1
    template {
      service_account = google_service_account.runtime["outbox"].email
      timeout         = "300s"
      max_retries     = 0
      containers {
        image   = var.api_image
        command = ["python", "-m", "jewelai_api.dispatch_pending"]
        args    = ["--batch-size", "100"]
        dynamic "env" {
          for_each = local.job_queue_environment
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
        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.production.connection_name]
        }
      }
    }
  }
}

resource "google_cloud_run_v2_job" "stale" {
  project             = var.project_id
  name                = "${local.prefix}-stale-recovery"
  location            = var.region
  deletion_protection = true

  template {
    task_count = 1
    template {
      service_account = google_service_account.runtime["stale"].email
      timeout         = "300s"
      max_retries     = 0
      containers {
        image   = var.worker_image
        command = ["python", "-m", "jewelai_persistence.recover_stale"]
        args    = ["--batch-size", "100", "--stale-after-seconds", tostring(var.stale_recovery_seconds)]
        dynamic "env" {
          for_each = local.job_database_environment
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
        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.production.connection_name]
        }
      }
    }
  }
}

resource "google_cloud_run_v2_job" "reconcile" {
  project             = var.project_id
  name                = "${local.prefix}-asset-reconcile"
  location            = var.region
  deletion_protection = true

  template {
    task_count = 1
    template {
      service_account = google_service_account.runtime["reconcile"].email
      timeout         = "600s"
      max_retries     = 0
      containers {
        image   = var.worker_image
        command = ["python", "-m", "jewelai_generation.reconcile_assets"]
        args    = ["--batch-size", "100"]
        dynamic "env" {
          for_each = merge(local.job_database_environment, {
            GCS_ASSET_BUCKET = google_storage_bucket.assets.name
          })
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
        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.production.connection_name]
        }
      }
    }
  }
}

resource "google_cloud_run_v2_job" "cleanup" {
  project             = var.project_id
  name                = "${local.prefix}-orphan-cleanup"
  location            = var.region
  deletion_protection = true

  template {
    task_count = 1
    template {
      service_account = google_service_account.runtime["cleanup"].email
      timeout         = "600s"
      max_retries     = 0
      containers {
        image   = var.worker_image
        command = ["python", "-m", "jewelai_generation.cleanup_orphans"]
        args = [
          "--apply",
          "--batch-size", "100",
          "--retention-seconds", tostring(var.orphan_retention_seconds),
        ]
        dynamic "env" {
          for_each = merge(local.job_database_environment, {
            GCS_ASSET_BUCKET = google_storage_bucket.assets.name
          })
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
        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.production.connection_name]
        }
      }
    }
  }
}

resource "google_cloud_run_v2_job_iam_member" "scheduler" {
  for_each = local.scheduled_jobs
  project  = var.project_id
  location = var.region
  name     = each.value
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.runtime["scheduler"].email}"
}

resource "google_cloud_scheduler_job" "maintenance" {
  for_each         = local.schedules
  project          = var.project_id
  region           = var.region
  name             = "${local.prefix}-${each.key}"
  description      = "Invoke the private JewelAI ${each.key} maintenance job."
  schedule         = each.value
  time_zone        = var.scheduler_time_zone
  attempt_deadline = "320s"

  retry_config {
    retry_count          = 2
    min_backoff_duration = "30s"
    max_backoff_duration = "300s"
    max_doublings        = 2
  }

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${local.scheduled_jobs[each.key]}:run"

    oauth_token {
      service_account_email = google_service_account.runtime["scheduler"].email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.scheduler]
}
