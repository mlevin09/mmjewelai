resource "google_storage_bucket" "assets" {
  project                     = var.project_id
  name                        = var.asset_bucket_name
  location                    = var.asset_location
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = false
  }

  depends_on = [google_project_service.production]
}
