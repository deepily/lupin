terraform {
  # Floor is 1.9 (not 1.5): the cloud-run-model-server module's vpc_subnetwork
  # validation uses a CROSS-VARIABLE condition (references var.vpc_network),
  # legal only since Terraform 1.9 — on 1.5–1.8 `terraform init` errors with
  # "condition ... can only refer to the variable itself". See task cb0e145a
  # + modules/cloud-run-model-server/versions.tf (same floor at the source).
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
