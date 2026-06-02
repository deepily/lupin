# gce-gpu-vm — the Milestone-1 compute host (g2-standard-8 + bundled L4).
#
# g2 machine types ship the L4 attached (no guest_accelerator block). GPU VMs
# require on_host_maintenance=TERMINATE. The data disk is a SEPARATE persistent
# disk with prevent_destroy so a VM recreate never wipes LanceDB/io. Runs as
# runtime-sa (least-priv), not the default Compute SA.

resource "google_compute_disk" "data" {
  project = var.project_id
  name    = "lupin-data-${var.environment}"
  type    = "pd-ssd"
  zone    = var.zone
  size    = var.data_disk_gb

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_compute_instance" "vm" {
  project      = var.project_id
  name         = "lupin-host-${var.environment}"
  machine_type = var.machine_type
  zone         = var.zone

  # GPU VMs cannot live-migrate.
  scheduling {
    on_host_maintenance = "TERMINATE"
    automatic_restart   = true
  }

  boot_disk {
    initialize_params {
      image = var.boot_image
      size  = var.boot_disk_gb
      type  = "pd-ssd"
    }
  }

  attached_disk {
    source      = google_compute_disk.data.id
    device_name = "lupin-data"
  }

  network_interface {
    subnetwork = var.subnet_self_link

    dynamic "access_config" {
      for_each = var.assign_external_ip ? [1] : []
      content {}
    }
  }

  service_account {
    email  = var.runtime_sa_email
    scopes = ["cloud-platform"]
  }

  metadata_startup_script = var.startup_script

  allow_stopping_for_update = true
}
