resource "google_compute_global_address" "production" {
  project = var.project_id
  name    = "${local.prefix}-public"
}

resource "google_compute_region_network_endpoint_group" "web" {
  project               = var.project_id
  name                  = "${local.prefix}-web"
  region                = var.region
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = google_cloud_run_v2_service.web.name
  }
}

resource "google_compute_region_network_endpoint_group" "api" {
  project               = var.project_id
  name                  = "${local.prefix}-api"
  region                = var.region
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = google_cloud_run_v2_service.api.name
  }
}

resource "google_compute_security_policy" "api" {
  project     = var.project_id
  name        = "${local.prefix}-api"
  description = "Conservative source-IP rate limit; application authentication remains authoritative."
  type        = "CLOUD_ARMOR"

  rule {
    action   = "throttle"
    priority = 1000
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
      rate_limit_threshold {
        count        = var.api_rate_limit_requests
        interval_sec = var.api_rate_limit_interval_seconds
      }
    }
    description = "Bound abusive request bursts without replacing OIDC authorization."
  }

  rule {
    action   = "allow"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "Default allow after rate-limit evaluation."
  }
}

resource "google_compute_backend_service" "web" {
  project               = var.project_id
  name                  = "${local.prefix}-web"
  protocol              = "HTTP"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  timeout_sec           = 30

  backend {
    group = google_compute_region_network_endpoint_group.web.id
  }
}

resource "google_compute_backend_service" "api" {
  project               = var.project_id
  name                  = "${local.prefix}-api"
  protocol              = "HTTP"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  timeout_sec           = 60
  security_policy       = google_compute_security_policy.api.id

  backend {
    group = google_compute_region_network_endpoint_group.api.id
  }
}

resource "google_compute_url_map" "https" {
  project         = var.project_id
  name            = "${local.prefix}-https"
  default_service = google_compute_backend_service.web.id

  host_rule {
    hosts        = [var.web_domain]
    path_matcher = "web"
  }

  host_rule {
    hosts        = [var.api_domain]
    path_matcher = "api"
  }

  path_matcher {
    name            = "web"
    default_service = google_compute_backend_service.web.id
  }

  path_matcher {
    name            = "api"
    default_service = google_compute_backend_service.api.id
  }
}

resource "google_compute_managed_ssl_certificate" "production" {
  project = var.project_id
  name    = "${local.prefix}-managed"

  managed {
    domains = [var.web_domain, var.api_domain]
  }
}

resource "google_compute_target_https_proxy" "production" {
  project          = var.project_id
  name             = "${local.prefix}-https"
  url_map          = google_compute_url_map.https.id
  ssl_certificates = [google_compute_managed_ssl_certificate.production.id]
}

resource "google_compute_global_forwarding_rule" "https" {
  project               = var.project_id
  name                  = "${local.prefix}-https"
  ip_address            = google_compute_global_address.production.id
  port_range            = "443"
  target                = google_compute_target_https_proxy.production.id
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

resource "google_compute_url_map" "http_redirect" {
  project = var.project_id
  name    = "${local.prefix}-http-redirect"

  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_http_proxy" "redirect" {
  project = var.project_id
  name    = "${local.prefix}-http-redirect"
  url_map = google_compute_url_map.http_redirect.id
}

resource "google_compute_global_forwarding_rule" "http" {
  project               = var.project_id
  name                  = "${local.prefix}-http"
  ip_address            = google_compute_global_address.production.id
  port_range            = "80"
  target                = google_compute_target_http_proxy.redirect.id
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

resource "google_dns_record_set" "web" {
  count        = local.dns_records_enabled ? 1 : 0
  project      = var.project_id
  managed_zone = var.dns_managed_zone
  name         = "${var.web_domain}."
  type         = "A"
  ttl          = 300
  rrdatas      = [google_compute_global_address.production.address]
}

resource "google_dns_record_set" "api" {
  count        = local.dns_records_enabled ? 1 : 0
  project      = var.project_id
  managed_zone = var.dns_managed_zone
  name         = "${var.api_domain}."
  type         = "A"
  ttl          = 300
  rrdatas      = [google_compute_global_address.production.address]
}
