variable "project_id" {
  description = "Existing billed GCP project for JewelAI production."
  type        = string
}

variable "region" {
  description = "Primary production region."
  type        = string
  default     = "us-central1"
}

variable "state_bucket_name" {
  description = "Globally unique bucket name for sensitive Terraform state."
  type        = string
}

variable "artifact_registry_repository" {
  description = "Regional Docker repository name."
  type        = string
  default     = "jewelai-production"
}

variable "github_repository" {
  description = "Exact GitHub owner/repository allowed to federate."
  type        = string
  default     = "mlevin09/mmjewelai"
}

variable "github_deploy_branch" {
  description = "Only this exact branch may assume the deployment identity."
  type        = string
  default     = "refs/heads/jewelai-v2"
}

variable "operator_members" {
  description = "Explicit IAM members allowed to administer Terraform state objects."
  type        = set(string)
  default     = []
}
