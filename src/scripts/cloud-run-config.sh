#!/bin/bash
#################################################################
# cloud-run-config.sh
#
# Shared GCP configuration resolver, SOURCED by every cloud-run-*.sh
# script. It reads an optional git-ignored cloud-run.env (copied from
# cloud-run.env.example), allows environment-variable override, and
# FAILS LOUD if the project ID is unset — the sandbox project ID can
# never silently leak into a real deploy.
#
# Resolves (for the sourcing script):
#   PROJECT_ID  <- LUPIN_GCP_PROJECT_ID   (REQUIRED — no sandbox default)
#   REGION      <- LUPIN_GCP_REGION        (default: us-central1)
#   REGISTRY    <- LUPIN_GCP_REGISTRY      (default: us-central1-docker.pkg.dev)
#   AR_REPO     <- LUPIN_GCP_AR_REPO       (default: lupin)
#
# Usage (top of each cloud-run-*.sh, after `set -e`):
#   source "$( dirname "$0" )/cloud-run-config.sh"
#################################################################

# Source the optional env file living beside this script (if present).
_CR_CONFIG_DIR="$( cd "$( dirname "${BASH_SOURCE[0]:-$0}" )" && pwd )"
_CR_ENV_FILE="$_CR_CONFIG_DIR/cloud-run.env"
[ -f "$_CR_ENV_FILE" ] && source "$_CR_ENV_FILE"

# Fail loud if the project is unset (the bash analogue of the fail-loud doctrine).
PROJECT_ID="${LUPIN_GCP_PROJECT_ID:?Set LUPIN_GCP_PROJECT_ID (no sandbox default — copy src/scripts/cloud-run.env.example to cloud-run.env)}"
REGION="${LUPIN_GCP_REGION:-us-central1}"
REGISTRY="${LUPIN_GCP_REGISTRY:-us-central1-docker.pkg.dev}"
AR_REPO="${LUPIN_GCP_AR_REPO:-lupin}"
