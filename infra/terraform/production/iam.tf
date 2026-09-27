resource "google_service_account" "runtime" {
  for_each     = local.service_accounts
  project      = var.project_id
  account_id   = "jewelai-${each.key}"
  display_name = "JewelAI ${each.key}"
  description  = each.value
  depends_on   = [google_project_service.production]
}

resource "google_project_iam_custom_role" "asset_create_read" {
  project     = var.project_id
  role_id     = "jewelaiAssetCreateRead"
  title       = "JewelAI Asset create and exact read"
  permissions = ["storage.objects.create", "storage.objects.get"]
}

resource "google_project_iam_custom_role" "asset_read" {
  project     = var.project_id
  role_id     = "jewelaiAssetRead"
  title       = "JewelAI exact Asset metadata/read"
  permissions = ["storage.objects.get"]
}

resource "google_project_iam_custom_role" "asset_cleanup" {
  project     = var.project_id
  role_id     = "jewelaiAssetCleanup"
  title       = "JewelAI version-conditional Asset cleanup"
  permissions = ["storage.objects.get", "storage.objects.delete"]
}

resource "google_project_iam_custom_role" "task_enqueue" {
  project     = var.project_id
  role_id     = "jewelaiGenerationEnqueue"
  title       = "JewelAI generation task enqueue"
  permissions = ["cloudtasks.tasks.create", "cloudtasks.tasks.get"]
}

resource "google_project_iam_custom_role" "asset_sign" {
  project     = var.project_id
  role_id     = "jewelaiAssetSign"
  title       = "JewelAI Asset signBlob"
  permissions = ["iam.serviceAccounts.signBlob"]
}

resource "google_project_iam_member" "cloudsql_client" {
  for_each = toset(["api", "worker", "migration", "outbox", "stale", "reconcile", "cleanup"])
  project  = var.project_id
  role     = "roles/cloudsql.client"
  member   = "serviceAccount:${google_service_account.runtime[each.value].email}"
}

resource "google_storage_bucket_iam_member" "asset_create_read" {
  for_each = toset(["api", "worker"])
  bucket   = google_storage_bucket.assets.name
  role     = google_project_iam_custom_role.asset_create_read.name
  member   = "serviceAccount:${google_service_account.runtime[each.value].email}"
}

resource "google_storage_bucket_iam_member" "asset_read" {
  for_each = toset(["signer", "reconcile"])
  bucket   = google_storage_bucket.assets.name
  role     = google_project_iam_custom_role.asset_read.name
  member   = "serviceAccount:${google_service_account.runtime[each.value].email}"
}

resource "google_storage_bucket_iam_member" "asset_cleanup" {
  bucket = google_storage_bucket.assets.name
  role   = google_project_iam_custom_role.asset_cleanup.name
  member = "serviceAccount:${google_service_account.runtime["cleanup"].email}"
}

resource "google_secret_manager_secret_iam_member" "database_url" {
  for_each  = toset(["api", "worker", "migration", "outbox", "stale", "reconcile", "cleanup"])
  project   = var.project_id
  secret_id = google_secret_manager_secret.database_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime[each.value].email}"
}

resource "google_secret_manager_secret_iam_member" "openai_key" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.openai_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime["worker"].email}"
}

resource "google_service_account_iam_member" "api_signer" {
  service_account_id = google_service_account.runtime["signer"].name
  role               = google_project_iam_custom_role.asset_sign.name
  member             = "serviceAccount:${google_service_account.runtime["api"].email}"
}

resource "google_cloud_tasks_queue_iam_member" "api_enqueue" {
  project  = var.project_id
  location = google_cloud_tasks_queue.generation.location
  name     = google_cloud_tasks_queue.generation.name
  role     = google_project_iam_custom_role.task_enqueue.name
  member   = "serviceAccount:${google_service_account.runtime["api"].email}"
}

resource "google_cloud_tasks_queue_iam_member" "outbox_enqueue" {
  project  = var.project_id
  location = google_cloud_tasks_queue.generation.location
  name     = google_cloud_tasks_queue.generation.name
  role     = google_project_iam_custom_role.task_enqueue.name
  member   = "serviceAccount:${google_service_account.runtime["outbox"].email}"
}

resource "google_service_account_iam_member" "task_oidc_user_api" {
  service_account_id = google_service_account.runtime["task"].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.runtime["api"].email}"
}

resource "google_service_account_iam_member" "task_oidc_user_outbox" {
  service_account_id = google_service_account.runtime["task"].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.runtime["outbox"].email}"
}
