terraform {
  required_version = ">= 1.14.0, < 1.17.0"
  backend "gcs" { prefix = "research/control-plane" }
  required_providers {
    google = { source = "hashicorp/google", version = ">= 7.10.0, < 8.0.0" }
  }
}

provider "google" {
  project = "mmjewellai-preprod"
  region  = "europe-west1"
  zone    = "europe-west1-b"
}

locals {
  project = "mmjewellai-preprod"
  zone    = "europe-west1-b"
  target  = "jewelai-llm-lab"
  name    = "jewelai-research-control"
  secrets = toset(["jewelai-research-tunnel-key", "jewelai-research-ssh-key", "jewelai-research-activation"])
}

# Deliberately separate state/root: never plan/apply the application stack for this host.
resource "google_compute_network" "control" {
  name                    = local.name
  auto_create_subnetworks = false
}
resource "google_compute_subnetwork" "control" {
  name                     = local.name
  network                  = google_compute_network.control.id
  region                   = "europe-west1"
  ip_cidr_range            = "10.203.177.0/28"
  private_ip_google_access = true
}
resource "google_compute_router" "control" {
  name    = local.name
  network = google_compute_network.control.id
  region  = "europe-west1"
}
resource "google_compute_router_nat" "control" {
  name                               = local.name
  router                             = google_compute_router.control.name
  region                             = "europe-west1"
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"
  subnetwork {
    name                    = google_compute_subnetwork.control.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }
}

# No public IP, public SSH, MCP listener, or broad default-network ingress.
resource "google_compute_firewall" "iap_admin" {
  name          = "${local.name}-iap-ssh"
  network       = google_compute_network.control.name
  source_ranges = ["35.235.240.0/20"]
  target_tags   = [local.name]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_service_account" "control" {
  account_id   = "jewelai-research-control"
  display_name = "Research VM connection only"
}
resource "google_project_iam_custom_role" "target" {
  role_id     = "jewelaiResearchTarget"
  title       = "Research target lifecycle only"
  permissions = ["compute.instances.get", "compute.instances.start", "compute.instances.stop"]
}
resource "google_compute_instance_iam_member" "target" {
  project       = local.project
  zone          = local.zone
  instance_name = local.target
  role          = google_project_iam_custom_role.target.name
  member        = "serviceAccount:${google_service_account.control.email}"
}
resource "google_project_iam_custom_role" "discovery" {
  role_id = "jewelaiResearchOperationRead"
  title   = "Read operations and IAP CLI discovery"
  # gcloud start-iap-tunnel requires list; no project-level VM mutation or SSH metadata.
  permissions = ["compute.instances.list", "compute.zoneOperations.get"]
}
resource "google_project_iam_member" "discovery" {
  project = local.project
  role    = google_project_iam_custom_role.discovery.name
  member  = "serviceAccount:${google_service_account.control.email}"
}
resource "google_iap_tunnel_instance_iam_member" "target" {
  project  = local.project
  zone     = local.zone
  instance = local.target
  role     = "roles/iap.tunnelResourceAccessor"
  member   = "serviceAccount:${google_service_account.control.email}"
  condition {
    title      = "research-ssh-only"
    expression = "destination.port == 22"
  }
}

# Metadata only. Versions/payloads are supplied out of band after authorization.
resource "google_secret_manager_secret" "runtime" {
  for_each  = local.secrets
  secret_id = each.value
  replication {
    auto {}
  }
  lifecycle { prevent_destroy = true }
}
resource "google_secret_manager_secret_iam_member" "read" {
  for_each  = local.secrets
  secret_id = google_secret_manager_secret.runtime[each.value].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.control.email}"
}

resource "google_compute_instance" "control" {
  name                = local.name
  machine_type        = "e2-micro"
  zone                = local.zone
  tags                = [local.name]
  labels              = { environment = "preprod", purpose = "research-control" }
  deletion_protection = true
  boot_disk {
    auto_delete = false
    initialize_params {
      image = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64"
      size  = 10
      type  = "pd-standard"
    }
  }
  network_interface { subnetwork = google_compute_subnetwork.control.id }
  service_account {
    email  = google_service_account.control.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
  metadata = { enable-oslogin = "TRUE", block-project-ssh-keys = "TRUE" }
  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE"
  }
  lifecycle { prevent_destroy = true }
  depends_on = [google_compute_router_nat.control]
}

output "control_host" { value = google_compute_instance.control.name }
output "runtime_identity" { value = google_service_account.control.email }
