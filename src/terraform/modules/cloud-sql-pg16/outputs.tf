# cloud-sql-pg16 module — outputs

output "connection_name" {
  value       = var.create_instance ? google_sql_database_instance.pg16[0].connection_name : ""
  description = "Cloud SQL connection name → CLOUD_SQL_CONNECTION_NAME for database.py's unix-socket URL."
}

output "instance_name" {
  value       = var.create_instance ? google_sql_database_instance.pg16[0].name : ""
  description = "Cloud SQL instance name."
}
