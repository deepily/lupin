# artifact-registry module — inputs

variable "project_id" {
  type        = string
  description = "GCP project ID. No default — must be supplied by the caller."
}

variable "region" {
  type        = string
  description = "Repository location."
  default     = "us-central1"
}

variable "repository_id" {
  type        = string
  description = "Artifact Registry Docker repository ID."
  default     = "lupin-images"
}

variable "keep_versions" {
  type        = number
  description = "Number of most-recent image versions to retain per image (caps storage for the large rest + model-server images)."
  default     = 10
}
