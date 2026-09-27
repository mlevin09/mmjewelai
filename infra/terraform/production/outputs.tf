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

output "worker_service_name" {
  value = google_cloud_run_v2_service.worker.name
}

output "auth0_spa_client_id" {
  value = auth0_client.jewelai_web.client_id
}

output "oidc_issuer" {
  value = local.oidc_issuer
}

output "oidc_audience" {
  value = local.oidc_audience
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
