# Authorized PR #177 execution entrance only. No application/production resources.
variable "research_runner_entrance_image" {
  type        = string
  description = "Exact digest of the TLS-pinned entrance image in the existing registry."
  default     = ""
}

resource "google_service_account" "entrance" {
  account_id   = "jewelai-research-entrance"
  display_name = "Research HTTPS entrance; no GCP API roles"
}

# Direct VPC egress requires /26; the existing control /28 is preserved.
resource "google_compute_subnetwork" "entrance" {
  name                     = "jewelai-research-entrance"
  network                  = google_compute_network.control.id
  region                   = "europe-west1"
  ip_cidr_range            = "10.203.178.0/26"
  private_ip_google_access = true
}

resource "google_compute_firewall" "entrance" {
  name        = "jewelai-research-entrance"
  network     = google_compute_network.control.name
  source_tags = ["jewelai-research-entrance"]
  target_tags = [local.name]
  allow {
    protocol = "tcp"
    ports    = ["8081"]
  }
}

resource "google_cloud_run_v2_service" "entrance" {
  name                 = "jewelai-research-runner"
  location             = "europe-west1"
  deletion_protection  = true
  invoker_iam_disabled = true # Public transport; control host enforces OAuth before tools.
  template {
    service_account                  = google_service_account.entrance.email
    timeout                          = "60s"
    max_instance_request_concurrency = 8
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image = var.research_runner_entrance_image
      resources {
        limits   = { cpu = "1", memory = "256Mi" }
        cpu_idle = true
      }
      env {
        name  = "RESEARCH_BACKEND"
        value = "https://10.203.177.2:8081"
      }
      env {
        name  = "RESEARCH_PUBLIC_HOST"
        value = "jewelai-research-runner-483253159059.europe-west1.run.app"
      }
    }
    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = google_compute_network.control.name
        subnetwork = google_compute_subnetwork.entrance.name
        tags       = ["jewelai-research-entrance"]
      }
    }
  }
  lifecycle {
    precondition {
      condition     = can(regex("^europe-west1-docker.pkg.dev/mmjewellai-preprod/jewelai-preprod/.+@sha256:[a-f0-9]{64}$", var.research_runner_entrance_image))
      error_message = "Exact existing-registry image digest required."
    }
  }
}

output "runner_execution_url" { value = google_cloud_run_v2_service.entrance.uri }
