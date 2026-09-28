resource "google_firebase_project" "preprod" {
  provider = google-beta
  project  = var.project_id

  depends_on = [google_project_service.production]
}

resource "google_firebase_web_app" "jewelai" {
  provider        = google-beta
  project         = var.project_id
  display_name    = "JewelAI Preprod Web"
  deletion_policy = "ABANDON"

  depends_on = [google_firebase_project.preprod]
}

data "google_firebase_web_app_config" "jewelai" {
  provider   = google-beta
  project    = var.project_id
  web_app_id = google_firebase_web_app.jewelai.app_id
}

resource "google_identity_platform_config" "preprod" {
  project = var.project_id

  sign_in {
    allow_duplicate_emails = false

    email {
      enabled           = true
      password_required = true
    }

    anonymous {
      enabled = false
    }
  }

  authorized_domains = distinct([
    var.web_domain,
    data.google_firebase_web_app_config.jewelai.auth_domain,
  ])

  depends_on = [google_project_service.production]
}
