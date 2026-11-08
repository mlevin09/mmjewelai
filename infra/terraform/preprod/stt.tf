# Disabled until an Owner-approved image digest AND cost/resource reference are supplied.
# Uses the existing preprod state/plan/apply boundary; never apply this file independently.
variable "stt_image" {
  type        = string
  default     = ""
  description = "Optional reviewed offline STT image; empty provisions no STT resources."
  validation {
    condition = var.stt_image == "" || can(regex(
      "^europe-west1-docker\\.pkg\\.dev/mmjewellai-preprod/jewelai-preprod/jewelai-stt@sha256:[0-9a-f]{64}$",
      var.stt_image
    ))
    error_message = "STT must use an immutable image in the exact preprod registry."
  }
}

variable "stt_resource_approval_reference" {
  type        = string
  default     = ""
  description = "Explicit Owner approval of the one-L4 configuration and recurring costs."
}

locals {
  stt_enabled = var.stt_image != ""
}

# Two networks prevent STT's DNS sink policy from breaking existing API provider calls.
resource "google_compute_network" "stt" {
  for_each                = local.stt_enabled ? toset(["caller", "inference"]) : toset([])
  project                 = var.project_id
  name                    = "jewelai-preprod-stt-${each.key}"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  lifecycle {
    precondition {
      condition     = length(trimspace(var.stt_resource_approval_reference)) > 0
      error_message = "Explicit Owner STT resource/cost approval is required before provisioning."
    }
  }
}

resource "google_compute_subnetwork" "stt" {
  for_each                 = google_compute_network.stt
  project                  = var.project_id
  name                     = each.value.name
  region                   = var.region
  network                  = each.value.id
  ip_cidr_range            = each.key == "caller" ? "10.90.0.0/26" : "10.90.1.0/26"
  private_ip_google_access = each.key == "caller"
  stack_type               = "IPV4_ONLY"
}

resource "google_compute_firewall" "stt_deny_ipv4" {
  count              = local.stt_enabled ? 1 : 0
  project            = var.project_id
  name               = "jewelai-preprod-stt-deny-egress-v4"
  network            = google_compute_network.stt["inference"].id
  direction          = "EGRESS"
  priority           = 100
  target_tags        = ["jewelai-stt-isolated"]
  destination_ranges = ["0.0.0.0/0"]
  deny { protocol = "all" }
}

resource "google_compute_firewall" "stt_deny_ipv6" {
  count              = local.stt_enabled ? 1 : 0
  project            = var.project_id
  name               = "jewelai-preprod-stt-deny-egress-v6"
  network            = google_compute_network.stt["inference"].id
  direction          = "EGRESS"
  priority           = 100
  target_tags        = ["jewelai-stt-isolated"]
  destination_ranges = ["::/0"]
  deny { protocol = "all" }
}

# Only the caller network resolves run.app to the restricted Google VIP. PRIVATE_RANGES_ONLY
# routes this special range via Direct VPC while preserving API's existing Internet egress.
resource "google_dns_managed_zone" "stt_caller" {
  count      = local.stt_enabled ? 1 : 0
  project    = var.project_id
  name       = "jewelai-preprod-stt-caller"
  dns_name   = "run.app."
  visibility = "private"
  private_visibility_config {
    networks { network_url = google_compute_network.stt["caller"].id }
  }
}

resource "google_dns_record_set" "stt_caller" {
  count        = local.stt_enabled ? 1 : 0
  project      = var.project_id
  managed_zone = google_dns_managed_zone.stt_caller[0].name
  name         = "*.run.app."
  type         = "A"
  ttl          = 60
  rrdatas      = ["199.36.153.4", "199.36.153.5", "199.36.153.6", "199.36.153.7"]
}

# Metadata DNS traffic is not governed by VPC firewalls. This policy sinks A/AAAA;
# the authoritative private root below prevents recursion for all other query types.
resource "google_dns_response_policy" "stt" {
  count                = local.stt_enabled ? 1 : 0
  project              = var.project_id
  response_policy_name = "jewelai-preprod-stt-no-recursion"
  networks { network_url = google_compute_network.stt["inference"].id }
}

resource "google_dns_response_policy_rule" "stt" {
  count           = local.stt_enabled ? 1 : 0
  project         = var.project_id
  response_policy = google_dns_response_policy.stt[0].response_policy_name
  rule_name       = "sink-external-names"
  dns_name        = "*."
  local_data {
    local_datas {
      name    = "*."
      type    = "A"
      ttl     = 60
      rrdatas = ["127.0.0.1"]
    }
    local_datas {
      name    = "*."
      type    = "AAAA"
      ttl     = 60
      rrdatas = ["::1"]
    }
  }
}

# The response policy only answers configured RR types. Live qualification showed that
# TXT/MX otherwise fall through to public recursion. This authoritative private root
# supplies negative answers for every unmatched name/type, only on the inference VPC.
# Keep caller DNS separate: it still needs Google identity and provider connectivity.
resource "google_dns_managed_zone" "stt_inference_root" {
  count       = local.stt_enabled ? 1 : 0
  project     = var.project_id
  name        = "jewelai-preprod-stt-offline-root"
  dns_name    = "."
  description = "Authoritative empty root: no public DNS fallback for offline STT."
  visibility  = "private"
  private_visibility_config {
    networks { network_url = google_compute_network.stt["inference"].id }
  }
}

resource "google_service_account" "stt" {
  count        = local.stt_enabled ? 1 : 0
  project      = var.project_id
  account_id   = "jewelai-preprod-stt"
  display_name = "Offline STT; no project roles, secrets, database or Assets"
}

resource "google_cloud_run_v2_service" "stt" {
  count                = local.stt_enabled ? 1 : 0
  project              = var.project_id
  location             = var.region
  name                 = "jewelai-preprod-stt"
  ingress              = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  invoker_iam_disabled = false
  deletion_protection  = true

  template {
    service_account                  = google_service_account.stt[0].email
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"
    gpu_zonal_redundancy_disabled    = true
    max_instance_request_concurrency = 1
    timeout                          = "60s"
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    node_selector { accelerator = "nvidia-l4" }
    vpc_access {
      egress = "ALL_TRAFFIC"
      network_interfaces {
        network    = google_compute_network.stt["inference"].name
        subnetwork = google_compute_subnetwork.stt["inference"].name
        tags       = ["jewelai-stt-isolated"]
      }
    }
    containers {
      image = var.stt_image
      ports { container_port = 8080 }
      resources {
        limits   = { cpu = "4", memory = "16Gi", "nvidia.com/gpu" = "1" }
        cpu_idle = false
      }
      startup_probe {
        period_seconds    = 10
        timeout_seconds   = 2
        failure_threshold = 24
        http_get { path = "/health" }
      }
      liveness_probe {
        period_seconds    = 10
        timeout_seconds   = 2
        failure_threshold = 3
        http_get { path = "/health" }
      }
    }
  }
  depends_on = [
    google_compute_firewall.stt_deny_ipv4, google_compute_firewall.stt_deny_ipv6,
    google_dns_response_policy_rule.stt, google_dns_managed_zone.stt_inference_root,
    google_project_service.production,
  ]
}

resource "google_cloud_run_v2_service_iam_binding" "stt_invoker" {
  count    = local.stt_enabled ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.stt[0].name
  role     = "roles/run.invoker"
  members  = ["serviceAccount:${google_service_account.runtime["api"].email}"]
}

output "stt_service_url" {
  value       = local.stt_enabled ? google_cloud_run_v2_service.stt[0].uri : null
  description = "Server-only IAM audience and endpoint; internal ingress, not browser-callable."
}
