# cloud-sql-pg16 — managed PostgreSQL 16, PRIVATE IP only, PITR + daily backup.
#
# Matches the database.py unix-socket contract: the module's connection_name output
# feeds CLOUD_SQL_CONNECTION_NAME on the VM (with LUPIN_CLOUD_BACKED=true). The DB
# password is read from Secret Manager at apply — never in tfvars or as a plaintext
# input. Schema is created by the pre-deploy Alembic step (NOT auto-on-startup).

data "google_secret_manager_secret_version" "db_password" {
  count   = var.create_instance ? 1 : 0
  project = var.project_id
  secret  = var.db_password_secret_id
  version = "latest"
}

resource "google_sql_database_instance" "pg16" {
  count = var.create_instance ? 1 : 0

  project             = var.project_id
  name                = "lupin-pg16-${var.environment}"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = var.deletion_protection

  settings {
    tier              = var.tier
    availability_type = var.availability_type

    ip_configuration {
      ipv4_enabled    = false
      private_network = var.network_self_link
    }

    backup_configuration {
      enabled                        = true
      start_time                     = "02:00"
      point_in_time_recovery_enabled = true
      backup_retention_settings {
        retained_backups = 7
      }
    }

    database_flags {
      name  = "max_connections"
      value = "100"
    }

    database_flags {
      name  = "log_min_duration_statement"
      value = "500"
    }
  }
}

resource "google_sql_database" "app_db" {
  count    = var.create_instance ? 1 : 0
  project  = var.project_id
  name     = var.db_name
  instance = google_sql_database_instance.pg16[0].name
}

resource "google_sql_user" "app_user" {
  count    = var.create_instance ? 1 : 0
  project  = var.project_id
  name     = var.db_user
  instance = google_sql_database_instance.pg16[0].name
  password = data.google_secret_manager_secret_version.db_password[0].secret_data
}
