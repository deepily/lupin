# cloud-sql-pg16 module — inputs

variable "project_id" {
  type        = string
  description = "GCP project ID. No default — must be supplied by the caller."
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "environment" {
  type        = string
  description = "Composes the instance name and selects the DB-name default."
}

variable "network_self_link" {
  type        = string
  description = "VPC self_link for the private IP (from the vpc-vpn module)."
}

variable "tier" {
  type        = string
  description = "Cloud SQL machine tier."
  default     = "db-custom-2-7680"
}

variable "availability_type" {
  type    = string
  default = "ZONAL"
}

variable "db_name" {
  type        = string
  description = "Application database name (Milestone-1 target is lupin_db_test)."
  default     = "lupin_db_test"
}

variable "db_user" {
  type    = string
  default = "lupin_app"
}

variable "db_password_secret_id" {
  type        = string
  description = "Secret Manager secret holding the DB password (read at apply; never stored in tfvars/state inputs)."
  default     = "lupin-db-password"
}

variable "create_instance" {
  type        = bool
  description = "False supports reuse of an existing instance (skip-create guard). Phase-0 V5 found none → default true."
  default     = true
}

variable "deletion_protection" {
  type    = bool
  default = true
}
