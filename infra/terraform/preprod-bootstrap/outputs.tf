output "state_bucket_name" {
  value       = google_storage_bucket.terraform_state.name
  description = "Use as the preproduction stack's GCS backend bucket."
}

output "artifact_registry_repository" {
  value       = google_artifact_registry_repository.docker.repository_id
  description = "Use as the preproduction Artifact Registry repository ID."
}

output "workload_identity_provider" {
  value       = google_iam_workload_identity_pool_provider.github.name
  description = "Use with google-github-actions/auth for preproduction deployments."
}

output "deployment_service_account" {
  value       = google_service_account.preprod_deployer.email
  description = "Keyless preproduction deployment service account."
}

output "asset_bucket_name" {
  value       = var.asset_bucket_name
  description = "Validated GCS_ASSET_BUCKET input reserved for the main preproduction stack."
}
