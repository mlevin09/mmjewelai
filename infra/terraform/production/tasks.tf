resource "google_cloud_tasks_queue" "generation" {
  project  = var.project_id
  name     = "${local.prefix}-generation"
  location = var.region

  rate_limits {
    max_dispatches_per_second = var.task_max_dispatches_per_second
    max_concurrent_dispatches = var.task_max_concurrent_dispatches
  }

  retry_config {
    max_attempts       = var.task_max_attempts
    max_retry_duration = "1800s"
    min_backoff        = "30s"
    max_backoff        = "300s"
    max_doublings      = 3
  }

  depends_on = [google_project_service.production]
}
