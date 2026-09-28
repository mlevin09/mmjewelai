variable "project_id" {
  description = "Exact GCP project for the isolated JewelAI preproduction bootstrap."
  type        = string
  default     = "mmjewellai-preprod"

  validation {
    condition     = var.project_id == "mmjewellai-preprod"
    error_message = "The preprod bootstrap can target only mmjewellai-preprod."
  }
}

variable "region" {
  description = "Exact region for preproduction bootstrap resources."
  type        = string
  default     = "europe-west1"

  validation {
    condition     = var.region == "europe-west1"
    error_message = "The preprod bootstrap requires region=europe-west1."
  }
}

variable "state_bucket_name" {
  description = "Globally unique private bucket for preproduction Terraform state and exact plans."
  type        = string
  default     = "mmjewellai-preprod-tfstate"

  validation {
    condition = (
      var.state_bucket_name == "mmjewellai-preprod-tfstate" ||
      can(regex("^mmjewellai-preprod-tfstate-[0-9]{6,20}$", var.state_bucket_name))
    )
    error_message = "Use the preferred preprod state bucket name or its deterministic project-number suffix."
  }
}

variable "asset_bucket_name" {
  description = "Validated input reserved for the main preproduction stack; this bootstrap does not create it."
  type        = string
  default     = "mmjewellai-preprod-assets"

  validation {
    condition = (
      var.asset_bucket_name == "mmjewellai-preprod-assets" ||
      can(regex("^mmjewellai-preprod-assets-[0-9]{6,20}$", var.asset_bucket_name))
    )
    error_message = "Use the preferred preprod Asset bucket name or its deterministic project-number suffix."
  }
}

variable "artifact_registry_repository" {
  description = "Exact preproduction Docker repository ID."
  type        = string
  default     = "jewelai-preprod"

  validation {
    condition     = var.artifact_registry_repository == "jewelai-preprod"
    error_message = "The preprod bootstrap requires artifact_registry_repository=jewelai-preprod."
  }
}

variable "github_repository" {
  description = "Exact GitHub owner/repository allowed to federate."
  type        = string
  default     = "mlevin09/mmjewelai"

  validation {
    condition     = var.github_repository == "mlevin09/mmjewelai"
    error_message = "The preprod bootstrap permits only mlevin09/mmjewelai."
  }
}

variable "github_deploy_branch" {
  description = "Exact branch ref allowed to assume the preproduction deployment identity."
  type        = string
  default     = "refs/heads/jewelai-v2"

  validation {
    condition     = var.github_deploy_branch == "refs/heads/jewelai-v2"
    error_message = "The preprod bootstrap permits only refs/heads/jewelai-v2."
  }
}

variable "operator_members" {
  description = "Explicit IAM members allowed to administer preproduction Terraform state objects."
  type        = set(string)
  default     = []
}
