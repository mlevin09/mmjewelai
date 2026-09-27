output "state_bucket_name" {
  value       = google_storage_bucket.terraform_state.name
  description = "Use as the production stack's GCS backend bucket."
}

output "artifact_registry_repository" {
  value       = google_artifact_registry_repository.docker.name
  description = "Regional Docker repository resource name."
}

output "workload_identity_provider" {
  value       = google_iam_workload_identity_pool_provider.github.name
  description = "GitHub Actions google-github-actions/auth workload identity provider."
}

output "deployment_service_account" {
  value       = google_service_account.production_deployer.email
  description = "Keyless production deployment service account."
}
