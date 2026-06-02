# secret-manager — the secret inventory.
#
# One Secret Manager secret per inventory entry, automatic replication. NO secret
# VERSIONS are created here: values are seeded out-of-band (e.g. from src/conf/keys/*
# via the setup-secrets wrapper) so plaintext never lands in .tf/.tfvars or state.
# The consuming app pins a specific version at read time (never :latest in prod).

resource "google_secret_manager_secret" "secrets" {
  for_each = toset(var.secret_ids)

  project   = var.project_id
  secret_id = each.value

  replication {
    auto {}
  }
}
