terraform {
  required_version = ">= 1.14.0, < 1.17.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 7.10.0, < 8.0.0"
    }
  }
}
