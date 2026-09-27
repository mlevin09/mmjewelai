resource "google_logging_metric" "generation_failures" {
  project     = var.project_id
  name        = "jewelai/generation_task_failures"
  description = "Count of redacted structured generation_task_failed worker events."
  filter      = <<-EOT
    resource.type="cloud_run_revision"
    resource.labels.service_name="${google_cloud_run_v2_service.worker.name}"
    jsonPayload.event="generation_task_failed"
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

resource "google_monitoring_uptime_check_config" "web" {
  project      = var.project_id
  display_name = "JewelAI production web HTTPS"
  timeout      = "10s"
  period       = "60s"

  selected_regions = ["USA", "EUROPE", "ASIA_PACIFIC"]
  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = var.web_domain
    }
  }
  http_check {
    path         = "/health"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }
}

resource "google_monitoring_uptime_check_config" "api" {
  project      = var.project_id
  display_name = "JewelAI production API HTTPS"
  timeout      = "10s"
  period       = "60s"

  selected_regions = ["USA", "EUROPE", "ASIA_PACIFIC"]
  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = var.api_domain
    }
  }
  http_check {
    path         = "/health"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }
}

locals {
  threshold_alerts = {
    api_5xx = {
      name      = "JewelAI API elevated 5xx"
      filter    = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.api.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
      threshold = 5
      aligner   = "ALIGN_RATE"
      reducer   = "REDUCE_SUM"
      duration  = "300s"
    }
    api_latency = {
      name      = "JewelAI API high p95 latency"
      filter    = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.api.name}\" AND metric.type=\"run.googleapis.com/request_latencies\""
      threshold = 5000
      aligner   = "ALIGN_PERCENTILE_95"
      reducer   = "REDUCE_MAX"
      duration  = "300s"
    }
    web_5xx = {
      name      = "JewelAI web elevated 5xx"
      filter    = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.web.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
      threshold = 5
      aligner   = "ALIGN_RATE"
      reducer   = "REDUCE_SUM"
      duration  = "300s"
    }
    task_backlog = {
      name      = "JewelAI generation queue backlog"
      filter    = "resource.type=\"cloud_tasks_queue\" AND resource.labels.queue_id=\"${google_cloud_tasks_queue.generation.name}\" AND metric.type=\"cloudtasks.googleapis.com/queue/depth\""
      threshold = 20
      aligner   = "ALIGN_MAX"
      reducer   = "REDUCE_MAX"
      duration  = "300s"
    }
    sql_disk = {
      name      = "JewelAI Cloud SQL disk utilization high"
      filter    = "resource.type=\"cloudsql_database\" AND resource.labels.database_id=\"${var.project_id}:${google_sql_database_instance.production.name}\" AND metric.type=\"cloudsql.googleapis.com/database/disk/utilization\""
      threshold = 0.8
      aligner   = "ALIGN_MAX"
      reducer   = "REDUCE_MAX"
      duration  = "600s"
    }
    sql_cpu = {
      name      = "JewelAI Cloud SQL CPU sustained high"
      filter    = "resource.type=\"cloudsql_database\" AND resource.labels.database_id=\"${var.project_id}:${google_sql_database_instance.production.name}\" AND metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\""
      threshold = 0.8
      aligner   = "ALIGN_MEAN"
      reducer   = "REDUCE_MAX"
      duration  = "600s"
    }
    generation_failures = {
      name      = "JewelAI generation business failures"
      filter    = "resource.type=\"cloud_run_revision\" AND metric.type=\"logging.googleapis.com/user/${google_logging_metric.generation_failures.name}\""
      threshold = 3
      aligner   = "ALIGN_RATE"
      reducer   = "REDUCE_SUM"
      duration  = "300s"
    }
  }
}

resource "google_monitoring_alert_policy" "threshold" {
  for_each              = local.threshold_alerts
  project               = var.project_id
  display_name          = each.value.name
  combiner              = "OR"
  notification_channels = var.notification_channel_ids

  conditions {
    display_name = each.value.name
    condition_threshold {
      filter          = each.value.filter
      comparison      = "COMPARISON_GT"
      threshold_value = each.value.threshold
      duration        = each.value.duration
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = each.value.aligner
        cross_series_reducer = each.value.reducer
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }
}

resource "google_monitoring_alert_policy" "uptime" {
  project               = var.project_id
  display_name          = "JewelAI production uptime failure"
  combiner              = "OR"
  notification_channels = var.notification_channel_ids

  conditions {
    display_name = "Web or API HTTPS check failed"
    condition_threshold {
      filter          = "resource.type=\"uptime_url\" AND metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\""
      comparison      = "COMPARISON_LT"
      threshold_value = 1
      duration        = "180s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_FRACTION_TRUE"
      }
    }
  }
}

resource "google_monitoring_dashboard" "production" {
  project = var.project_id
  dashboard_json = jsonencode({
    displayName = "JewelAI production"
    mosaicLayout = {
      columns = 12
      tiles = [
        for index, chart in [
          { title = "Web requests", filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.web.name}\" AND metric.type=\"run.googleapis.com/request_count\"" },
          { title = "Web 5xx", filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.web.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\"" },
          { title = "Web latency", filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.web.name}\" AND metric.type=\"run.googleapis.com/request_latencies\"" },
          { title = "API requests", filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.api.name}\" AND metric.type=\"run.googleapis.com/request_count\"" },
          { title = "API 4xx", filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.api.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"4xx\"" },
          { title = "API 5xx", filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.api.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\"" },
          { title = "API latency", filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.api.name}\" AND metric.type=\"run.googleapis.com/request_latencies\"" },
          { title = "API instances", filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.api.name}\" AND metric.type=\"run.googleapis.com/container/instance_count\"" },
          { title = "Worker requests", filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.worker.name}\" AND metric.type=\"run.googleapis.com/request_count\"" },
          { title = "Worker 5xx", filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.worker.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\"" },
          { title = "Worker latency", filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.worker.name}\" AND metric.type=\"run.googleapis.com/request_latencies\"" },
          { title = "Worker instances", filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.worker.name}\" AND metric.type=\"run.googleapis.com/container/instance_count\"" },
          { title = "Cloud Tasks queue depth", filter = "resource.type=\"cloud_tasks_queue\" AND metric.type=\"cloudtasks.googleapis.com/queue/depth\"" },
          { title = "Cloud Tasks attempts", filter = "resource.type=\"cloud_tasks_queue\" AND metric.type=\"cloudtasks.googleapis.com/queue/task_attempt_count\"" },
          { title = "Cloud Tasks oldest age", filter = "resource.type=\"cloud_tasks_queue\" AND metric.type=\"cloudtasks.googleapis.com/queue/oldest_task_age\"" },
          { title = "Cloud SQL CPU", filter = "resource.type=\"cloudsql_database\" AND metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\"" },
          { title = "Cloud SQL memory", filter = "resource.type=\"cloudsql_database\" AND metric.type=\"cloudsql.googleapis.com/database/memory/utilization\"" },
          { title = "Cloud SQL connections", filter = "resource.type=\"cloudsql_database\" AND metric.type=\"cloudsql.googleapis.com/database/network/connections\"" },
          { title = "Cloud SQL disk", filter = "resource.type=\"cloudsql_database\" AND metric.type=\"cloudsql.googleapis.com/database/disk/utilization\"" },
          { title = "Cloud SQL storage", filter = "resource.type=\"cloudsql_database\" AND metric.type=\"cloudsql.googleapis.com/database/disk/bytes_used\"" },
          { title = "Generation failures", filter = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.generation_failures.name}\"" },
          ] : {
          xPos   = (index % 2) * 6
          yPos   = floor(index / 2) * 4
          width  = 6
          height = 4
          widget = {
            title = chart.title
            xyChart = {
              dataSets = [{
                plotType   = "LINE"
                targetAxis = "Y1"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = chart.filter
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
              }]
            }
          }
        }
      ]
    }
  })
}
