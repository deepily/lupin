#!/bin/bash
#################################################################
# deploy-cloud-test.sh
#
# Purpose: Repeatable, provenance-stamped code-sync of a COMMITTED
#   git ref onto the GCP cloud-test VM (lupin-host-test), replacing
#   the manual bundle->SCP->sudo-pull->chown->restart flow.
#   Implements task d8c699aa (design: src/rnd/v0.1.9/2026.06.23-gcp-code-sync-to-runtime-design.md).
#
# TWO AXES (auto-detected):
#   AXIS A (code): only src/ changed -> bind-mount sync + docker restart.
#                  ⚠️ REQUIRES the target container to bind /var/lupin/src. The
#                  cloud-TEST container does NOT (the ./src mount was removed
#                  2026-07-07 so it cannot shadow the baked image), so this axis
#                  ABORTS with a named error rather than silently deploying
#                  nothing — bug be706f10. Asserted against the LIVE container via
#                  docker inspect, not this repo's compose file, which is not what
#                  the VM runs.
#                  ⚠️ THAT SENTENCE IS ABOUT CLOUD-TEST AND ONLY CLOUD-TEST (row
#                  5f1532d1). It used to read "It does NOT today", which invited
#                  the reader to carry it across venues. Measured on lupin-host-test
#                  2026-08-24, the cloud-GPU container DOES bind it:
#                      /mnt/lupin-data/lupin/src -> /var/lupin/src
#                  so on that VM the fast code path is exactly what works, and this
#                  abort would refuse it. That is not a contradiction to fix by
#                  loosening the abort — it is why the venue guard below stops this
#                  script before it ever reaches an assertion written for somewhere
#                  else. On cloud-GPU, use `lupin-vm.sh deploy`.
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
REST_CONTAINER="lupin-rest-cloud-test"               # container_name — for `docker restart|inspect`
# COMPOSE SERVICE name, which is NOT the container name. `docker compose pull|up` resolves
# SERVICES; handed a container_name it exits "no such service: lupin-rest-cloud-test" (measured
# on compose v2.19.1, both verbs). AXIS-B passed $REST_CONTAINER to both and so aborted at the
# `pull` under `set -e` — it was broken by construction and had never completed. Two names
# because they are two namespaces: `docker restart` at :104/:156 and `docker inspect` at :141
# take the CONTAINER, compose takes the SERVICE. Collapsing them back into one variable
# re-breaks whichever half loses.
REST_SERVICE="lupin-rest"                            # docker-compose.cloud-test.yml:78
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

# ---- VENUE GUARD: is the venue this script is hardcoded to even HERE? ----
#
# ROW 5f1532d1. Every config value at the top of this file names the cloud-TEST
# venue: lupin-rest-cloud-test / docker-compose.cloud-test.yml / cloud-test.env.
# The one and only VM runs the cloud-GPU venue. Measured on lupin-host-test
# 2026-08-24: `lupin-rest-cloud-test` does not exist in ANY state, not even
# stopped, so every `docker restart` and `docker inspect` below addresses nothing.
#
# NOBODY IS BROKEN TODAY — the working path is `lupin-vm.sh deploy`, which targets
# cloud-gpu correctly and carries the --no-deps fix (bug 70794d58). The hazard this
# guard removes is a READER: this file is named deploy-cloud-test.sh but reads like
# THE deploy script, and without the guard its failures teach the wrong lesson —
# "the container is missing" or "code deploys are impossible on this VM" — when the
# truth is only that this script is pointed at a venue that is not here.
#
# BOTH compose files and BOTH env files ARE present on the VM, so their presence
# proves nothing about which venue is live. The container is the fact that decides
# it, which is why this asks docker and not the filesystem.
#
# RUNS BEFORE EVERYTHING, --dry-run INCLUDED. A dry-run that prints a confident
# plan for a container that does not exist is precisely the misleading output this
# guard exists to prevent, and a dry-run already reads the VM over ssh two lines
# below, so this adds no class of access it did not already have.
assert_target_venue_exists() {
    log "venue guard: is $REST_CONTAINER present on $VM_NAME?"
    local names
    names="$( "${SSH[@]}" "sudo docker ps -a --format '{{.Names}}'" 2>/dev/null || true )"
    dctl_venue_present "$REST_CONTAINER" "$names"
    case $? in
        0) log "venue OK — $REST_CONTAINER is present" ;;
        2) die "cannot list containers on $VM_NAME — the venue guard could not ask its question.
     This is NOT a verdict that the container is absent; the probe itself failed.
     Check: gcloud auth, the VM is running, and that sudo docker works over ssh." ;;
        *) local running
           running="$( "${SSH[@]}" "sudo docker ps --format '{{.Names}}'" 2>/dev/null | tr '\n' ' ' || true )"
           die "WRONG VENUE — this script is not the deploy path for $VM_NAME.

  This script is hardcoded to the cloud-TEST venue:
      container $REST_CONTAINER   compose $COMPOSE_FILE   env $ENV_FILE
  and $REST_CONTAINER does not exist on $VM_NAME in any state, not even stopped.
  What is actually running there: ${running:-<nothing>}

  Nothing is broken and nothing is missing. This VM runs the cloud-GPU venue, and
  its deploy path is:

      src/scripts/lupin-vm.sh deploy

  which targets docker-compose.cloud-gpu.yml / cloud-gpu.env and carries the
  --no-deps fix (bug 70794d58) that this script's venue also needs.

  Do NOT 'fix' this by repointing the config at the top of this file at cloud-gpu.
  The two venues differ in more than names — see the AXIS-A note in the header,
  whose premise is true of cloud-test and false of cloud-gpu. Repointing would
  carry cloud-test's assumptions onto a venue they do not describe, which is the
  same class of error as the one this guard just caught."
           ;;
    esac
}
assert_target_venue_exists

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
    [ "$AXIS" = code ] && log "  would: ASSERT $REST_CONTAINER binds /var/lupin/src (be706f10; ABORTS if not) -> git archive src/ -> SCP -> sudo cp -> chown 1001:1001 -> docker restart $REST_CONTAINER -> health-gate" \
                       || log "  would: cloud-run-build.sh <tag> -> push AR -> compose pull -> up -d --no-deps --force-recreate $REST_SERVICE -> health-gate"
    log "  would stamp $DEPLOYED_REF_FILE = '$SHA $(date -u +%FT%TZ) $AXIS'; keep prior src/ as src.bak-$STAMP"
    exit 0
fi

# ---- AXIS A: code-only bind-mount sync -----------------------------------
#
# PRECONDITION (bug be706f10). This axis is a BIND-MOUNT SYNC: it extracts src/
# onto the VM's disk and `docker restart`s, which only deploys code if the
# container actually binds that directory. `docker-compose.cloud-test.yml` stopped
# mounting `./src` on 2026-07-07 (deliberately — a live bind would SHADOW the
# self-consistent baked image for the v0.2.0 pgvector leg), and this script was
# never swept. Without the check below, AXIS-A extracts code the container cannot
# see, restarts the SAME baked image, and the health-gate goes GREEN — because the
# container IS healthy; it is merely running the old code.
#
# ⚠️ ASSERTED AGAINST THE LIVE CONTAINER, NOT THE REPO'S COMPOSE FILE. The repo
# file is not what the VM runs; a VM-side copy may legitimately differ, and reading
# the repo to answer a question about the VM is the exact failure this lane keeps
# finding. `docker inspect` asks the process that will actually serve the code.
#
# This also transitively protects `rollback_code`, which restores src.bak-$STAMP
# and restarts under the SAME assumption: it runs only after deploy_code, and
# deploy_code now dies here under `set -euo pipefail` before the health-gate.
#
# ⚠️ BEHAVIOUR CHANGE, stated plainly: code-only deploys that previously reported
# SUCCESS will now FAIL. They were not deploying anything; the green was the bug.
assert_container_binds_src() {
    log "precondition: does $REST_CONTAINER actually bind /var/lupin/src?"
    local bound
    bound="$( "${SSH[@]}" "sudo docker inspect -f '{{range .Mounts}}{{println .Destination}}{{end}}' $REST_CONTAINER 2>/dev/null | grep -Fx '/var/lupin/src' || true" )"
    if [ -z "$bound" ]; then
        die "AXIS-A cannot work against $REST_CONTAINER: it has NO bind mount at /var/lupin/src.
  This axis syncs src/ to the VM's disk and restarts — with no mount, the container
  never sees the new code, keeps running the baked image, and the health-gate passes
  anyway (bug be706f10). The ./src mount was removed from docker-compose.cloud-test.yml
  on 2026-07-07 on purpose, so that a live bind cannot SHADOW the baked image.
  REMEDY: deploy via the image axis instead — re-run with --deps, which builds and
  pushes a new image rather than syncing a directory nothing reads.
  Do NOT 'fix' this by restoring the ./src mount; that re-arms the shadow trap."
    fi
    log "precondition OK — /var/lupin/src is bind-mounted; the sync can land"
}

deploy_code() {
    assert_container_binds_src
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
    # Fail loud — a `:-` default hands a caller a project they never chose, and
    # GOOGLE_CLOUD_PROJECT/GCLOUD_PROJECT outrank ANTHROPIC_VERTEX_PROJECT_ID, so a
    # silent default here can bill the wrong project while every guard reports green.
    : "${LUPIN_GCP_PROJECT_ID:?Set LUPIN_GCP_PROJECT_ID (no sandbox default — copy src/scripts/cloud-run.env.example to cloud-run.env)}"
    export LUPIN_GCP_PROJECT_ID
    export LUPIN_GCP_AR_REPO="${LUPIN_GCP_AR_REPO:-lupin-images}"
    printf 'n\nn\n' | ./src/scripts/cloud-run-build.sh "$tag"
    log "on-VM: AR login, bump LUPIN_IMAGE -> $tag, pull, force-recreate"
    "${SSH[@]}" "
        set -e
        cd $VM_ROOT
        TOKEN=\$(curl -s -H 'Metadata-Flavor: Google' 'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token' | python3 -c 'import sys,json;print(json.load(sys.stdin)[\"access_token\"])')
        echo \"\$TOKEN\" | sudo docker login -u oauth2accesstoken --password-stdin https://us-central1-docker.pkg.dev >/dev/null
        sudo sed -i \"s#^\\(LUPIN_IMAGE=.*\\):[^:]*\$#\\1:$tag#\" $ENV_FILE
        sudo docker compose -f $COMPOSE_FILE --env-file $ENV_FILE pull $REST_SERVICE
        # --no-deps is NOT optional (bug 70794d58). docker-compose.cloud-test.yml carries the
        # SAME graph as cloud-gpu — lupin-rest(:129) -> cloud-sql-proxy service_healthy(:53-55)
        # -> cloudsql-socket-init service_completed_successfully — so recreating the app walks
        # the graph and re-runs socket-init, whose \`rm -f /cloudsql/*/.s.PGSQL.5432\` DELETES
        # the socket the ALREADY-RUNNING proxy owns. The proxy binds once and never re-creates
        # it, so every app connect then fails "No such file or directory" while \`docker ps\`
        # still reads "healthy" (the proxy healthcheck probes :9090 and never touches the socket).
        # ⚠️ This omission was LATENT, not dormant-by-luck: AXIS-B died one line up on the
        # service-name bug, so it never reached this command. Fixing that bug ALONE would have
        # ARMED this one on the cloud-test VM. They had to land together.
        sudo docker compose -f $COMPOSE_FILE --env-file $ENV_FILE up -d --no-deps --force-recreate $REST_SERVICE
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
