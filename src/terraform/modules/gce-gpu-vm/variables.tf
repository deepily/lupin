# gce-gpu-vm module — inputs

variable "project_id" {
  type        = string
  description = "GCP project ID. No default — must be supplied by the caller."
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "zone" {
  type    = string
  default = "us-central1-a"
}

variable "environment" {
  type        = string
  description = "Composes the VM + data-disk names."
}

variable "machine_type" {
  type        = string
  description = "g2 family bundles 1x L4 with the machine type (no guest_accelerator needed)."
  default     = "g2-standard-8"
}

variable "subnet_self_link" {
  type        = string
  description = "Subnet for the VM NIC (from the vpc-vpn module)."
}

variable "runtime_sa_email" {
  type        = string
  description = "Runtime service account email (from the iam module) — NOT the default Compute SA."
}

variable "boot_image" {
  type    = string
  default = "ubuntu-os-cloud/ubuntu-2204-lts"
}

variable "boot_disk_gb" {
  type    = number
  default = 100
}

variable "data_disk_gb" {
  type    = number
  default = 200
}

variable "assign_external_ip" {
  type        = bool
  description = "Keep an external IP for operator SSH/ingress on Milestone 1."
  default     = true
}

variable "startup_script" {
  type        = string
  description = "Provisioning startup-script (driver + Container Toolkit + docker). compose-up is the bash deploy wrapper's job, not Terraform's."
  default     = <<-EOT
    #!/bin/bash
    set -euxo pipefail
    # NVIDIA driver (>= 535, validated floor) + Container Toolkit + Docker.
    if ! command -v docker > /dev/null 2>&1; then
      apt-get update
      apt-get install -y ca-certificates curl gnupg
      install -m 0755 -d /etc/apt/keyrings
      curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
      apt-get update
      apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    fi
    # GPU driver via the GCE installer helper.
    if ! command -v nvidia-smi > /dev/null 2>&1; then
      curl -fsSL https://raw.githubusercontent.com/GoogleCloudPlatform/compute-gpu-installation/main/linux/install_gpu_driver.py -o /tmp/install_gpu_driver.py
      python3 /tmp/install_gpu_driver.py || true
    fi
    # NVIDIA Container Toolkit.
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' > /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt-get update && apt-get install -y nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=docker && systemctl restart docker
    # docker compose up is performed by the bash deploy wrapper (gce-vm-deploy.sh).
  EOT
}
