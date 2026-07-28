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

    # Consumer B's own credential, split out 2026-07-28 (rows 574fd1dc / 6cc52525).
    #
    # DO NOT re-merge this with lupin-notification-api-key. They look
    # interchangeable and are not: lupin-notification-api-key is validated
    # against a PER-DEPLOYMENT `api_keys` table, so its correct value differs on
    # every host; this one is mounted into Cloud Run and bcrypt-hashed at boot,
    # so its correct value is IDENTICAL everywhere. Sharing one secret between
    # those two authorities is what produced a 38-hour 100% 401 outage on
    # /embeddings/generate — the VM's key matched NEITHER secret version because
    # it had been minted into the VM's own database, which was correct for the
    # other consumer.
    #
    # src/rnd/v0.1.9/2026.07.28-model-server-api-key-decoupling.md
    "lupin-model-server-api",
  ]
}
