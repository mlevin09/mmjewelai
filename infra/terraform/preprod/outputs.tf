output "web_url" {
  value       = local.web_origin
  description = "Public HTTPS web URL."
}

output "api_url" {
  value       = local.api_origin
  description = "Public HTTPS API URL."
}

output "load_balancer_ip" {
  value       = google_compute_global_address.production.address
  description = "Create A records for web_domain and api_domain when DNS management is disabled."
}

output "dns_records_managed" {
  value       = local.dns_records_enabled
  description = "True when this stack manages the required public DNS A records."
}

output "required_dns_a_records" {
  value = {
    web = {
      name    = "${var.web_domain}."
      type    = "A"
      ttl     = 300
      rrdatas = [google_compute_global_address.production.address]
    }
    api = {
      name    = "${var.api_domain}."
      type    = "A"
      ttl     = 300
      rrdatas = [google_compute_global_address.production.address]
    }
  }
  description = "Required public A records for an operator-managed DNS handoff."
}

output "managed_certificate_name" {
  value       = google_compute_managed_ssl_certificate.production.name
  description = "Google-managed certificate polled by the deployment readiness check."
}

output "worker_service_name" {
  value = google_cloud_run_v2_service.worker.name
}

output "identity_platform_issuer" {
  value = local.identity_platform_issuer
}

output "identity_platform_project_id" {
  value = var.project_id
}

output "identity_platform_web_app_id" {
  value = google_firebase_web_app.jewelai.app_id
}

output "asset_bucket_name" {
  value = google_storage_bucket.assets.name
}

output "cloud_sql_instance" {
  value = google_sql_database_instance.production.name
}

output "generation_queue_name" {
  value = google_cloud_tasks_queue.generation.name
}

output "migration_job_name" {
  value = google_cloud_run_v2_job.migration.name
}

output "operational_job_names" {
  value = values(local.scheduled_jobs)
}
