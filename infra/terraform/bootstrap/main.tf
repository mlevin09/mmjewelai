locals {
  bootstrap_services = toset([
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "serviceusage.googleapis.com",
    "sts.googleapis.com",
    "storage.googleapis.com",
  ])
  deployer_roles = toset([
    "roles/artifactregistry.admin",
    "roles/cloudscheduler.admin",
    "roles/cloudsql.admin",
    "roles/cloudtasks.admin",
    "roles/compute.admin",
    "roles/dns.admin",
    "roles/iam.securityAdmin",
    "roles/iam.serviceAccountAdmin",
    "roles/iam.serviceAccountUser",
    "roles/logging.admin",
    "roles/monitoring.admin",
    "roles/resourcemanager.projectIamAdmin",
    "roles/run.admin",
    "roles/secretmanager.admin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/storage.admin",
  ])
}

resource "google_project_service" "bootstrap" {
  for_each           = local.bootstrap_services
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_storage_bucket" "terraform_state" {
  name                        = var.state_bucket_name
  project                     = var.project_id
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  depends_on = [google_project_service.bootstrap]
}

resource "google_artifact_registry_repository" "docker" {
  project       = var.project_id
  location      = var.region
  repository_id = var.artifact_registry_repository
  description   = "Immutable JewelAI production container images"
  format        = "DOCKER"

  depends_on = [google_project_service.bootstrap]
}

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "jewelai-github"
  display_name              = "JewelAI GitHub Actions"
  description               = "Keyless deployment identity for the protected production workflow"
  disabled                  = false

  depends_on = [google_project_service.bootstrap]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  attribute_condition = "assertion.repository == '${var.github_repository}' && assertion.ref == '${var.github_deploy_branch}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "production_deployer" {
  project      = var.project_id
  account_id   = "jewelai-prod-deployer"
  display_name = "JewelAI production Terraform deployer"
  description  = "Assumed only by the protected jewelai-v2 GitHub deployment workflow"
  depends_on   = [google_project_service.bootstrap]
}

resource "google_service_account_iam_member" "github_deployer" {
  service_account_id = google_service_account.production_deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

resource "google_project_iam_member" "deployer" {
  for_each = local.deployer_roles
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.production_deployer.email}"
}

data "google_iam_policy" "terraform_state" {
  binding {
    role = "roles/storage.objectAdmin"
    members = concat(
      ["serviceAccount:${google_service_account.production_deployer.email}"],
      tolist(var.operator_members),
    )
  }
  binding {
    role = "roles/storage.legacyBucketReader"
    members = concat(
      ["serviceAccount:${google_service_account.production_deployer.email}"],
      tolist(var.operator_members),
    )
  }
}

resource "google_storage_bucket_iam_policy" "terraform_state" {
  bucket      = google_storage_bucket.terraform_state.name
  policy_data = data.google_iam_policy.terraform_state.policy_data
}
