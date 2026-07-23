#!/usr/bin/env bash
#
# lupin-vm.sh — SSH / service-control / tunnel wrapper for the cloud-test VM (lupin-host-test).
#
# One wrapper over `gcloud` for the four things Rick does with the remote VM:
#   1. instance lifecycle   (vm-status / vm-start / vm-stop)   — the VM is suspended-by-default
#   2. interactive SSH       (shell / run)                      — over IAP (no public IP)
#   3. app service control   (svc up|down|restart|status|logs)  — docker compose on the VM
#   4. local tunnel          (tunnel [PORT])                    — bind localhost:PORT -> VM :7999
#
# Access is IAP-only (no public IP), identical to deploy-cloud-test.sh for SSH. NOTE: the `tunnel`
# subcommand forwards IAP TCP to port 7999, which needs a VPC firewall rule allowing the IAP range
# 35.235.240.0/20 -> tcp:7999 (SSH works because tcp:22 already has one; 7999 may not). See runbook
# §"Tunnel firewall" for the one-time `gcloud compute firewall-rules create`.
#
# Runbook: src/rnd/2026.07.22-lupin-host-test-ssh-tunnel-automation.md
#
# Usage:
#   src/scripts/lupin-vm.sh <subcommand> [args]
#   src/scripts/lupin-vm.sh --dry-run <subcommand> [args]   # echo the gcloud line, run nothing
#
# Env:
#   LUPIN_GCP_PROJECT_ID   REQUIRED — GCP project id (no default; abort if unset). e.g. hello-world-foo-423219
#   LUPIN_VM_NAME          optional — instance name (default: lupin-host-test)
#   LUPIN_VM_ZONE          optional — zone          (default: us-central1-a)

set -euo pipefail

# ---- config (overridable via env) ----------------------------------------
VM_NAME="${LUPIN_VM_NAME:-lupin-host-test}"
VM_ZONE="${LUPIN_VM_ZONE:-us-central1-a}"
VM_ROOT="/mnt/lupin-data/lupin"                 # UID-1001-owned on-VM checkout (deploy-cloud-test.sh:31)
# The CPU VM (post GPU→CPU downgrade) runs the cloud-GPU topology: model-server on Cloud Run,
# NO local nvidia container. Using cloud-test.yml here recreates a local GPU model-server that
# cannot start on the CPU VM ("could not select device driver nvidia"). Source of truth:
# docker-compose.cloud-gpu.yml + src/rnd/2026.07.08-cpu-vm-app-restore-runbook.md §3.
COMPOSE_FILE="docker-compose.cloud-gpu.yml"     # CPU VM: Cloud Run model-server, no nvidia
ENV_FILE="cloud-gpu.env"                         # requires LUPIN_MODEL_SERVER_URL (on the VM, git-ignored)
# `docker compose logs/up <name>` take the SERVICE name, NOT the container_name. The service is
# `lupin-rest` (container_name lupin-rest-cloud-gpu) — passing the container name gives
# "no such service". Compose subcommands here use REST_SERVICE.
REST_SERVICE="lupin-rest"                        # compose service name (container_name = lupin-rest-cloud-gpu)
APP_PORT=7999                                    # in-VM app port

DRY_RUN=0

log()  { echo "[lupin-vm] $*"; }
die()  { echo "[lupin-vm] FATAL: $*" >&2; exit 1; }

usage() {
    cat >&2 <<EOF
lupin-vm.sh — SSH / service / tunnel wrapper for $VM_NAME ($VM_ZONE)

Usage: lupin-vm.sh [--dry-run] <subcommand> [args]

Instance lifecycle:
  vm-status              show RUNNING / STOPPED / SUSPENDED
  vm-start               start the instance (needed before SSH; VM is suspended-by-default)
  vm-stop                stop the instance (cost control)

SSH:
  shell                  interactive SSH session (over IAP)
  run "<cmd>"            run one command remotely

App services (docker compose in $VM_ROOT):
  svc status             docker compose ps
  svc up                 up -d
  svc down               down
  svc restart            up -d --force-recreate $REST_SERVICE
  svc logs               logs -f --tail=200 $REST_SERVICE

Tunnel:
  tunnel [PORT]          bind localhost:PORT -> VM :$APP_PORT (default PORT=$APP_PORT)
                         leave running; browse http://localhost:PORT ; Ctrl-C to end

Firewall (one-time — the tunnel needs IAP allowed to :$APP_PORT):
  firewall status        list all VPC firewall rules (scan sourceRanges for 35.235.240.0/20)
  firewall open [PORT]   allow IAP range -> tcp:PORT (default $APP_PORT); network auto-derived

Env: LUPIN_GCP_PROJECT_ID (required), LUPIN_VM_NAME, LUPIN_VM_ZONE

Self-contained: no repo dependencies — copy this one file to any machine with gcloud + IAP access.
EOF
}

# ---- flags ---------------------------------------------------------------
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
    shift
fi

SUBCMD="${1:-}"
[ -n "$SUBCMD" ] || { usage; exit 2; }
shift || true

# ---- project id (fail loud — a silent default can act on the wrong project) ----
# Mirrors deploy-cloud-test.sh:115. VM lifecycle + IAP both take an explicit --project so nothing
# rides on the ambient `gcloud config` project, which may point elsewhere.
require_project() {
    : "${LUPIN_GCP_PROJECT_ID:?Set LUPIN_GCP_PROJECT_ID (e.g. export LUPIN_GCP_PROJECT_ID=hello-world-foo-423219)}"
}

# ---- run-or-echo ---------------------------------------------------------
# Prints the exact command, then either runs it (normal) or stops (--dry-run).
runit() {
    log "+ $*"
    if [ "$DRY_RUN" -eq 1 ]; then
        log "(dry-run) not executed"
        return 0
    fi
    "$@"
}

# ---- remote compose helper ----------------------------------------------
# Builds the `cd $VM_ROOT && sudo docker compose ...` command run over IAP SSH.
remote_compose() {
    local compose_args="$*"
    require_project
    runit gcloud compute ssh "$VM_NAME" \
        --zone="$VM_ZONE" \
        --project="$LUPIN_GCP_PROJECT_ID" \
        --tunnel-through-iap \
        --command "cd $VM_ROOT && sudo docker compose -f $COMPOSE_FILE --env-file $ENV_FILE $compose_args"
}

# ---- dispatch ------------------------------------------------------------
case "$SUBCMD" in
    vm-status)
        require_project
        runit gcloud compute instances describe "$VM_NAME" \
            --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" \
            --format='value(status)'
        ;;

    vm-start)
        require_project
        runit gcloud compute instances start "$VM_NAME" \
            --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID"
        ;;

    vm-stop)
        require_project
        runit gcloud compute instances stop "$VM_NAME" \
            --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID"
        ;;

    shell)
        require_project
        runit gcloud compute ssh "$VM_NAME" \
            --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap
        ;;

    run)
        [ -n "${1:-}" ] || die "run needs a command:  lupin-vm.sh run \"docker ps\""
        require_project
        runit gcloud compute ssh "$VM_NAME" \
            --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap \
            --command "$1"
        ;;

    svc)
        action="${1:-}"
        case "$action" in
            status)  remote_compose "ps" ;;
            up)      remote_compose "up -d" ;;
            down)    remote_compose "down" ;;
            restart) remote_compose "up -d --force-recreate $REST_SERVICE" ;;
            logs)    remote_compose "logs -f --tail=200 $REST_SERVICE" ;;
            *)       die "svc needs one of: status | up | down | restart | logs" ;;
        esac
        ;;

    tunnel)
        local_port="${1:-$APP_PORT}"
        require_project
        # Bind IPv4 127.0.0.1, NOT localhost. On macOS `localhost` resolves to IPv6 ::1 first, and
        # the IAP tunnel mishandles the ::1 local socket -> "OSError: [Errno 9] Bad file descriptor"
        # on every browser connection. Pinning 127.0.0.1 avoids the IPv6 path. Browse http://127.0.0.1:PORT.
        log "tunnel: 127.0.0.1:$local_port -> $VM_NAME:$APP_PORT  (browse http://127.0.0.1:$local_port ; Ctrl-C to end)"
        runit gcloud compute start-iap-tunnel "$VM_NAME" "$APP_PORT" \
            --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" \
            --local-host-port="127.0.0.1:$local_port"
        ;;

    firewall)
        # IAP TCP forwarding to :7999 needs a VPC rule allowing the IAP range 35.235.240.0/20
        # -> tcp:PORT. SSH works because tcp:22 already has one. The network is auto-derived from
        # the VM (no manual --network paste); the rule is untagged so it applies to every instance
        # in that network — safe, since the source range is only Google's IAP forwarders.
        action="${1:-status}"
        require_project
        # read-only lookup of the VM's network (basename of the network URL); fine to run in dry-run
        NETWORK="$( gcloud compute instances describe "$VM_NAME" \
            --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" \
            --format='value(networkInterfaces[0].network)' 2>/dev/null )"
        NETWORK="${NETWORK##*/}"
        case "$action" in
            status)
                # NOTE: no server-side sourceRanges filter — a CIDR like 35.235.240.0/20 is an
                # invalid list-filter expression. List all rules; scan the sourceRanges column by eye.
                runit gcloud compute firewall-rules list --project="$LUPIN_GCP_PROJECT_ID" \
                    --format="table(name,network,direction,sourceRanges.list(),allowed[].map().firewall_rule().list(),targetTags.list())"
                ;;
            open)
                port="${2:-$APP_PORT}"
                [ -n "$NETWORK" ] || die "could not derive the VM network (is $VM_NAME running / correct project?)"
                log "opening IAP -> tcp:$port on network '$NETWORK'"
                runit gcloud compute firewall-rules create "lupin-iap-$port" \
                    --project="$LUPIN_GCP_PROJECT_ID" --network="$NETWORK" \
                    --direction=INGRESS --action=ALLOW --rules="tcp:$port" \
                    --source-ranges=35.235.240.0/20
                ;;
            *) die "firewall needs: status | open [PORT]" ;;
        esac
        ;;

    -h|--help|help)
        usage
        ;;

    *)
        die "unknown subcommand: $SUBCMD  (try: lupin-vm.sh --help)"
        ;;
esac
