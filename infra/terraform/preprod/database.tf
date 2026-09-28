resource "random_password" "database" {
  length           = 40
  special          = true
  override_special = "-_~"
}

resource "google_sql_database_instance" "production" {
  project             = var.project_id
  name                = "${local.prefix}-postgres"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = true

  settings {
    edition                     = "ENTERPRISE"
    tier                        = var.database_tier
    availability_type           = var.database_availability_type
    disk_type                   = "PD_SSD"
    disk_size                   = var.database_disk_size_gb
    disk_autoresize             = true
    disk_autoresize_limit       = var.database_disk_autoresize_limit_gb
    deletion_protection_enabled = true

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "03:00"
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 14
        retention_unit   = "COUNT"
      }
    }

    ip_configuration {
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"
    }

    maintenance_window {
      day          = var.database_maintenance_day
      hour         = var.database_maintenance_hour
      update_track = "stable"
    }

    database_flags {
      name  = "max_connections"
      value = tostring(var.database_max_connections)
    }
  }

  depends_on = [google_project_service.production]
}

resource "google_sql_database" "jewelai" {
  project  = var.project_id
  name     = "jewelai"
  instance = google_sql_database_instance.production.name
}

resource "google_sql_user" "application" {
  project  = var.project_id
  name     = "jewelai_app"
  instance = google_sql_database_instance.production.name
  password = random_password.database.result
}

locals {
  database_url = "postgresql+psycopg://jewelai_app:${urlencode(random_password.database.result)}@/jewelai?host=/cloudsql/${google_sql_database_instance.production.connection_name}"
}
