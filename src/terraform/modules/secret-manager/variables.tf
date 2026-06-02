# secret-manager module — inputs
# Creates the secret INVENTORY (empty secrets). Values are populated out-of-band
# (never in tfvars). Per-secret accessor bindings live in the iam module to avoid
# a module dependency cycle.

variable "project_id" {
  type        = string
  description = "GCP project ID. No default — must be supplied by the caller."
}

variable "secret_ids" {
  type        = list(string)
  description = "Secret Manager secret IDs to create (the verified inventory)."
  default = [
    "lupin-jwt-secret-key",
    "lupin-db-password",
    "lupin-anthropic-api-key-firewalled",
    "lupin-openai-api-key",
    "lupin-groq-api-key",
    "lupin-google-api-key",
    "lupin-gemini-api-key",
    "lupin-mistral-api-key",
    "lupin-elevenlabs-api-key",
    "lupin-kagi-api-key",
    "lupin-hf-token",
    "lupin-notification-api-key",
    "lupin-smtp-username",
    "lupin-smtp-password",
  ]
}
