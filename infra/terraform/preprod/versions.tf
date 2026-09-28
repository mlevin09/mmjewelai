terraform {
  required_version = ">= 1.14.0, < 1.17.0"

  backend "gcs" {
    prefix = "preprod/platform"
  }

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 7.10.0, < 8.0.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 7.10.0, < 8.0.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.9.0, < 4.0.0"
    }
  }
}
