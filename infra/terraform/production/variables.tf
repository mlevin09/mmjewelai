variable "project_id" {
  type        = string
  description = "Existing billed GCP production project."
}

variable "region" {
  type        = string
  description = "Cloud Run, Cloud SQL, queue, and Artifact Registry region."
  default     = "us-central1"
}

variable "asset_location" {
  type        = string
  description = "Private Asset bucket location."
  default     = "US-CENTRAL1"
}

variable "web_domain" {
  type        = string
  description = "Exact public web hostname without scheme."
  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])$", var.web_domain)) && !strcontains(var.web_domain, "..")
    error_message = "web_domain must be an exact lower-case DNS hostname without scheme, path, or whitespace."
  }
}

variable "api_domain" {
  type        = string
  description = "Exact public API hostname without scheme."
  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])$", var.api_domain)) && !strcontains(var.api_domain, "..")
    error_message = "api_domain must be an exact lower-case DNS hostname without scheme, path, or whitespace."
  }
}

variable "dns_managed_zone" {
  type        = string
  description = "Existing Cloud DNS managed-zone name; null or empty leaves records to the operator."
  default     = null
  nullable    = true

  validation {
    condition = (
      var.dns_managed_zone == null ||
      var.dns_managed_zone == "" ||
      can(regex("^(?:[a-z]|[a-z][a-z0-9-]{0,61}[a-z0-9])$", var.dns_managed_zone))
    )
    error_message = "dns_managed_zone must be null, empty, or an exact lower-case Cloud DNS managed-zone name."
  }
}

variable "auth0_domain" {
  type        = string
  description = "Existing Auth0 tenant domain without scheme. Provider credentials come only from protected environment secrets."
  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])$", var.auth0_domain)) && !strcontains(var.auth0_domain, "..")
    error_message = "auth0_domain must be an exact lower-case tenant hostname without scheme, slash, or whitespace."
  }
}

variable "allow_self_signup" {
  type        = bool
  description = "Enable Auth0 database-connection self-signup. Controlled alpha defaults closed."
  default     = false
}

variable "api_image" {
  type        = string
  description = "API Artifact Registry image pinned by sha256 digest."
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.api_image))
    error_message = "api_image must be an immutable sha256 digest reference."
  }
}

variable "worker_image" {
  type        = string
  description = "Worker Artifact Registry image pinned by sha256 digest."
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.worker_image))
    error_message = "worker_image must be an immutable sha256 digest reference."
  }
}

variable "web_image" {
  type        = string
  description = "Web Artifact Registry image pinned by sha256 digest."
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.web_image))
    error_message = "web_image must be an immutable sha256 digest reference."
  }
}

variable "asset_bucket_name" {
  type        = string
  description = "Globally unique private Asset bucket name."
}

variable "artifact_registry_repository" {
  type        = string
  default     = "jewelai-production"
  description = "Bootstrap-created Docker repository ID."
}

variable "database_tier" {
  type        = string
  default     = "db-custom-2-7680"
  description = "Explicit production Cloud SQL machine tier."
}

variable "database_availability_type" {
  type    = string
  default = "REGIONAL"
  validation {
    condition     = contains(["REGIONAL", "ZONAL"], var.database_availability_type)
    error_message = "database_availability_type must be REGIONAL or ZONAL."
  }
}

variable "database_disk_size_gb" {
  type    = number
  default = 20
}

variable "database_disk_autoresize_limit_gb" {
  type    = number
  default = 100
}

variable "database_max_connections" {
  type        = number
  default     = 100
  description = "Must exceed max instances × (pool size + overflow) with operator headroom."
}

variable "database_maintenance_day" {
  type    = number
  default = 7
}

variable "database_maintenance_hour" {
  type    = number
  default = 5
}

variable "db_pool_size" {
  type    = number
  default = 5
}

variable "db_max_overflow" {
  type    = number
  default = 2
}

variable "api_max_instances" {
  type    = number
  default = 5
  validation {
    condition     = var.api_max_instances >= 1 && var.api_max_instances <= 20
    error_message = "api_max_instances must be between 1 and 20."
  }
}

variable "worker_max_instances" {
  type    = number
  default = 2
  validation {
    condition     = var.worker_max_instances >= 1 && var.worker_max_instances <= 10
    error_message = "worker_max_instances must be between 1 and 10."
  }
}

variable "web_max_instances" {
  type    = number
  default = 3
  validation {
    condition     = var.web_max_instances >= 1 && var.web_max_instances <= 20
    error_message = "web_max_instances must be between 1 and 20."
  }
}

variable "api_min_instances" {
  type    = number
  default = 0
}

variable "worker_min_instances" {
  type    = number
  default = 0
}

variable "web_min_instances" {
  type    = number
  default = 0
}

variable "api_concurrency" {
  type    = number
  default = 40
}

variable "web_concurrency" {
  type    = number
  default = 80
}

variable "asset_upload_max_bytes" {
  type        = number
  default     = 20971520
  description = "Validated Asset policy limit (20 MiB by default)."
}

variable "http_max_request_bytes" {
  type        = number
  default     = 22020096
  description = "Raw HTTP body limit; includes 1 MiB of multipart envelope headroom."
}

variable "worker_request_timeout_seconds" {
  type    = number
  default = 300
}

variable "stale_recovery_seconds" {
  type    = number
  default = 1800
}

variable "orphan_retention_seconds" {
  type    = number
  default = 604800
}

variable "task_max_attempts" {
  type    = number
  default = 5
  validation {
    condition     = var.task_max_attempts >= 1 && var.task_max_attempts <= 10
    error_message = "task_max_attempts must be finite and between 1 and 10."
  }
}

variable "task_max_dispatches_per_second" {
  type    = number
  default = 1
  validation {
    condition     = var.task_max_dispatches_per_second > 0 && var.task_max_dispatches_per_second <= 10
    error_message = "task_max_dispatches_per_second must be greater than zero and at most 10."
  }
}

variable "task_max_concurrent_dispatches" {
  type    = number
  default = 2
  validation {
    condition     = var.task_max_concurrent_dispatches >= 1 && var.task_max_concurrent_dispatches <= 10
    error_message = "task_max_concurrent_dispatches must be between 1 and 10."
  }
}

variable "outbox_schedule" {
  type    = string
  default = "* * * * *"
}

variable "stale_recovery_schedule" {
  type    = string
  default = "*/5 * * * *"
}

variable "asset_reconciliation_schedule" {
  type    = string
  default = "*/5 * * * *"
}

variable "orphan_cleanup_schedule" {
  type    = string
  default = "17 3 * * *"
}

variable "scheduler_time_zone" {
  type    = string
  default = "Etc/UTC"
}

variable "notification_channel_ids" {
  type        = list(string)
  default     = []
  description = "Pre-existing Cloud Monitoring notification-channel resource IDs."
}

variable "api_rate_limit_requests" {
  type    = number
  default = 300
}

variable "api_rate_limit_interval_seconds" {
  type    = number
  default = 60
}

variable "generation_profiles_json" {
  type        = string
  description = "Required non-secret bounded generation profile registry consumed by the API."

  validation {
    condition = (
      can([for profile in jsondecode(var.generation_profiles_json) : tostring(profile.model)]) &&
      length(try(jsondecode(var.generation_profiles_json), [])) > 0
    )
    error_message = "generation_profiles_json must be a non-empty JSON array whose entries contain model identifiers."
  }
}

variable "openai_allowed_models" {
  type        = string
  description = "Required comma-separated server-side OpenAI image model allowlist."

  validation {
    condition = (
      can(regex("^[A-Za-z0-9][A-Za-z0-9._-]*(?:,[A-Za-z0-9][A-Za-z0-9._-]*)*$", var.openai_allowed_models)) &&
      length(split(",", var.openai_allowed_models)) == length(toset(split(",", var.openai_allowed_models)))
    )
    error_message = "openai_allowed_models must contain unique comma-separated exact model identifiers without whitespace."
  }
}
