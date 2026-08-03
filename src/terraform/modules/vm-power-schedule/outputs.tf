# vm-power-schedule module — outputs

output "suspend_job_name" {
  value       = try(google_cloud_scheduler_job.suspend[0].name, null)
  description = "Name of the weekday suspend Cloud Scheduler job (null when disabled)."
}

output "resume_job_name" {
  value       = try(google_cloud_scheduler_job.resume[0].name, null)
  description = "Name of the weekday resume Cloud Scheduler job (null when disabled)."
}
