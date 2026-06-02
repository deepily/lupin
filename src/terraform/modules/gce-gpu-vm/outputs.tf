# gce-gpu-vm module — outputs

output "vm_name" {
  value       = google_compute_instance.vm.name
  description = "GCE instance name."
}

output "internal_ip" {
  value       = google_compute_instance.vm.network_interface[0].network_ip
  description = "VM internal IP."
}

output "external_ip" {
  value       = var.assign_external_ip ? google_compute_instance.vm.network_interface[0].access_config[0].nat_ip : ""
  description = "VM external IP (empty if assign_external_ip=false)."
}
