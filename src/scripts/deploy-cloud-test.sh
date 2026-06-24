#!/bin/bash
#################################################################
# deploy-cloud-test.sh
#
# Purpose: Repeatable, provenance-stamped code-sync of a COMMITTED
#   git ref onto the GCP cloud-test VM (lupin-host-test), replacing
#   the manual bundle->SCP->sudo-pull->chown->restart flow.
#   Implements task d8c699aa (design: src/rnd/2026.06.23-gcp-code-sync-to-runtime-design.md).
#
# TWO AXES (auto-detected):
#   AXIS A (code): only src/ changed -> bind-mount sync + docker restart.
#   AXIS B (deps): pyproject.toml / uv.lock changed -> image rebuild path
#                  (build->push->pull->force-recreate). NEVER a silent restart.
#
# Usage:
#   ./src/scripts/deploy-cloud-test.sh [--ref <git-ref>] [--deps] [--dry-run] [--allow-dirty]
#     --ref         git ref to deploy (default: HEAD). Must be committed.
#     --deps        acknowledge + take the AXIS-B image path when deps changed.
#     --dry-run     print the plan; touch nothing on the VM.
#     --allow-dirty skip the clean-working-tree guard (NOT recommended).
#
# Safety: provenance stamp (.deployed-ref), prior-src kept as .bak-<stamp>,
#   health-gate with auto-rollback. cloud-TEST only.
#################################################################

set -euo pipefail

# ---- config (cloud-test VM) ----------------------------------------------
VM_NAME="lupin-host-test"
VM_ZONE="us-central1-a"
VM_ROOT="/mnt/lupin-data/lupin"                      # UID-1001-owned on-VM checkout
REST_CONTAINER="lupin-rest-cloud-test"
COMPOSE_FILE="docker-compose.cloud-test.yml"
ENV_FILE="cloud-test.env"
DEPLOYED_REF_FILE="$VM_ROOT/.deployed-ref"
SSH=( gcloud compute ssh "$VM_NAME" --zone="$VM_ZONE" --tunnel-through-iap --command )
DEP_PATHS=( pyproject.toml uv.lock )

# ---- pure helpers (unit-tested in src/tests/unit/test_deploy_cloud_test_lib.py) ----
DCTL_DEP_PATHS=( "${DEP_PATHS[@]}" )                 # lib reads this for axis-detect/clean-check
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# shellcheck source=lib/deploy-cloud-test-lib.sh
source "$SCRIPT_DIR/lib/deploy-cloud-test-lib.sh"

# ---- args ----------------------------------------------------------------
dctl_parse_args "$@" || exit 2

log() { echo "[deploy-cloud-test] $*"; }
die() { echo "[deploy-cloud-test] FATAL: $*" >&2; exit 1; }

# ---- resolve + validate the ref ------------------------------------------
SHA="$( dctl_resolve_sha "$REF" )" || die "ref '$REF' is not a valid commit"
SHORT="${SHA:0:8}"
log "target ref $REF -> $SHORT"

if [ "$ALLOW_DIRTY" -eq 0 ]; then
    # refuse if src/ or the dep files differ from the committed ref (provenance).
    if ! dctl_check_clean "$SHA"; then
        die "working tree differs from $SHORT under src/ or deps — commit first (or --allow-dirty)."
    fi
fi

# ---- read the VM's currently-deployed ref --------------------------------
PREV_SHA="$( "${SSH[@]}" "cat $DEPLOYED_REF_FILE 2>/dev/null | awk '{print \$1}'" 2>/dev/null || true )"
PREV_SHA="$( dctl_sanitize_sha "$PREV_SHA" )"
[ -n "$PREV_SHA" ] && log "VM currently at ${PREV_SHA:0:8}" || log "VM has no .deployed-ref (first deploy)"

# ---- AXIS DETECT (empty prev OR dep-file delta -> deps; else code) --------
AXIS="$( dctl_detect_axis "$PREV_SHA" "$SHA" )"
log "axis = $AXIS  (pyproject.toml/uv.lock $( [ "$AXIS" = deps ] && echo CHANGED || echo unchanged ) vs deployed)"

if [ "$AXIS" = "deps" ] && [ "$TAKE_DEPS" -eq 0 ]; then
    die "AXIS-B (dependency) change detected — a bind-mount restart will NOT load new deps.
     Re-run with --deps to take the image-rebuild path (build->push->pull->force-recreate),
     or deploy a code-only ref. (This guard is the firebase-admin lesson: never silent-restart on a deps change.)"
fi

STAMP="$( dctl_compute_stamp "$SHA" )"

if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY-RUN plan:"
    log "  axis=$AXIS ref=$SHORT prev=${PREV_SHA:0:8}"
    [ "$AXIS" = code ] && log "  would: git archive src/ -> SCP -> sudo cp -> chown 1001:1001 -> docker restart $REST_CONTAINER -> health-gate" \
                       || log "  would: cloud-run-build.sh <tag> -> push AR -> compose pull -> up --force-recreate $REST_CONTAINER -> health-gate"
    log "  would stamp $DEPLOYED_REF_FILE = '$SHA $(date -u +%FT%TZ) $AXIS'; keep prior src/ as src.bak-$STAMP"
    exit 0
fi

# ---- AXIS A: code-only bind-mount sync -----------------------------------
deploy_code() {
    local tar="/tmp/lupin-src-$SHORT.tar"
    log "exporting committed src/ @ $SHORT"
    git archive --format=tar "$SHA" src/ > "$tar"
    log "SCP -> VM /tmp"
    gcloud compute scp "$tar" "$VM_NAME:/tmp/" --zone="$VM_ZONE" --tunnel-through-iap >/dev/null
    log "on-VM: backup prior src/, extract, chown 1001:1001, restart"
    "${SSH[@]}" "
        set -e
        cd $VM_ROOT
        sudo cp -a src src.bak-$STAMP
        sudo tar -xf /tmp/$(basename "$tar") -C $VM_ROOT
        sudo chown -R 1001:1001 $VM_ROOT/src
        rm -f /tmp/$(basename "$tar")
        sudo docker restart $REST_CONTAINER
    "
}

# ---- AXIS B: dependency image rebuild ------------------------------------
deploy_deps() {
    local tag="1.$(date -u +%Y%m%d%H%M)"   # candidate tag, never 'latest'
    log "AXIS-B: building image $tag (deps changed) via cloud-run-build.sh"
    export LUPIN_GCP_PROJECT_ID="${LUPIN_GCP_PROJECT_ID:-hello-world-foo-423219}"
    export LUPIN_GCP_AR_REPO="${LUPIN_GCP_AR_REPO:-lupin-images}"
    printf 'n\nn\n' | ./src/scripts/cloud-run-build.sh "$tag"
    log "on-VM: AR login, bump LUPIN_IMAGE -> $tag, pull, force-recreate"
    "${SSH[@]}" "
        set -e
        cd $VM_ROOT
        TOKEN=\$(curl -s -H 'Metadata-Flavor: Google' 'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token' | python3 -c 'import sys,json;print(json.load(sys.stdin)[\"access_token\"])')
        echo \"\$TOKEN\" | sudo docker login -u oauth2accesstoken --password-stdin https://us-central1-docker.pkg.dev >/dev/null
        sudo sed -i \"s#^\\(LUPIN_IMAGE=.*\\):[^:]*\$#\\1:$tag#\" $ENV_FILE
        sudo docker compose -f $COMPOSE_FILE --env-file $ENV_FILE pull $REST_CONTAINER
        sudo docker compose -f $COMPOSE_FILE --env-file $ENV_FILE up -d --force-recreate $REST_CONTAINER
    "
}

# ---- health-gate + rollback ----------------------------------------------
health_gate() {
    log "health-gate: polling $REST_CONTAINER (up to ${HEALTH_GATE_POLLS:-72}x5s)"
    local h
    # Window default 72x5s = 360s. Was 36 (180s) — the d8c699aa live E2E proved the
    # cloud-test container's restart-to-healthy time sits NEAR/above 180s and is
    # variable, so a 180s gate FALSE-rolled-back perfectly-good deploys. 360s gives
    # ~2x headroom; override via HEALTH_GATE_POLLS for slower images.
    h="$( "${SSH[@]}" "
        for i in \$(seq 1 ${HEALTH_GATE_POLLS:-72}); do
            s=\$(sudo docker inspect --format '{{.State.Health.Status}}' $REST_CONTAINER 2>/dev/null || echo none)
            [ \"\$s\" = healthy ] && { echo healthy; exit 0; }
            sleep 5
        done
        echo \"\$s\"
    " )"
    echo "$h" | grep -q healthy
}

rollback_code() {
    log "ROLLBACK: restoring src.bak-$STAMP + restart"
    "${SSH[@]}" "
        set -e
        cd $VM_ROOT
        sudo rm -rf src && sudo mv src.bak-$STAMP src && sudo chown -R 1001:1001 src
        sudo docker restart $REST_CONTAINER
    "
}

# ---- orchestrate ---------------------------------------------------------
if [ "$AXIS" = "code" ]; then deploy_code; else deploy_deps; fi

if health_gate; then
    log "HEALTHY. stamping provenance."
    "${SSH[@]}" "echo '$SHA $(date -u +%FT%TZ) $AXIS' | sudo tee $DEPLOYED_REF_FILE >/dev/null"
    log "DONE: $REST_CONTAINER now at $SHORT (axis=$AXIS). prior src kept as src.bak-$STAMP (code axis)."
else
    log "UNHEALTHY after deploy."
    [ "$AXIS" = "code" ] && rollback_code || die "AXIS-B unhealthy — manual rollback (set LUPIN_IMAGE back + force-recreate); see runbook."
    die "deploy failed health-gate; rolled back (code axis)."
fi
