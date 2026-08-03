# cloud-run-model-server module — Terraform core version floor.
#
# Floor is 1.9 (not the repo-wide 1.5): the vpc_subnetwork variable validation in
# variables.tf uses a CROSS-VARIABLE condition (references var.vpc_network) to fail
# loud on the network-set-with-subnetwork-empty misconfig. Cross-variable validation
# refs are legal only since Terraform 1.9 — on 1.5–1.8 `terraform init` errors with
# "condition ... can only refer to the variable itself". Declaring the floor HERE (at
# the source of the 1.9-gated feature, not only in the env caller) fails loud for ANY
# caller of this module. See task cb0e145a + R&D docs 06/07.
terraform {
  required_version = ">= 1.9"
}
