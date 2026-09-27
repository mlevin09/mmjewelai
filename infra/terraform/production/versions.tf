terraform {
  required_version = ">= 1.14.0, < 1.17.0"

  backend "gcs" {
    prefix = "production/platform"
  }

  required_providers {
    auth0 = {
      source  = "auth0/auth0"
      version = ">= 1.56.0, < 2.0.0"
    }
    google = {
      source  = "hashicorp/google"
      version = ">= 7.10.0, < 8.0.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.9.0, < 4.0.0"
    }
  }
}
