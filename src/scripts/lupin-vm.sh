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
APP_PORT=7999                                    # in-VM app port (docker compose lupin-rest)
# The :8001 arbiter is NOT a compose service — it runs HOST-side as a `systemd --user` unit
# (provision-arbiter-on-vm.sh), out-of-band so an app-container bounce never takes it down.
# It is reload=False by design (a watcher must not hot-reload itself), so a code refresh needs
# an explicit restart. `deploy` bounces it after checkout.
ARBITER_SERVICE="lupin-arbiter-app.service"      # host systemd --user unit for the :8001 arbiter
ARBITER_PORT=8001                                # in-VM arbiter port (host systemd --user)

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

Sibling repos (the VM has no git creds — archive+SCP a LOCAL checkout):
  push-repo <local-path> [dest-name]
                         copy a local git repo (tracked files @ HEAD) to /mnt/lupin-data/<dest-name>,
                         a sibling of lupin. e.g. push-repo ../planning-is-prompting

Update lupin ON the VM (refresh its bundle 'remote' from THIS dev checkout):
  push-bundle [branch] [--checkout]
                         rebuild /mnt/lupin-data/lupin-wip.bundle from this repo's <branch>
                         (default: current branch) + git fetch on the VM. Add --checkout to also
                         point the VM working tree at the branch (else refs update, tree unchanged).
                         Code-sync ONLY — does NOT restart the servers.

Full deploy (bundle -> checkout -> restart BOTH servers -> verify) — RUN FROM THE DEV BOX:
  deploy [branch]        one-shot: push-bundle --checkout, then force-recreate :$APP_PORT $REST_SERVICE
                         (compose) + restart :$ARBITER_PORT arbiter (systemd --user), then probe
                         /health on both. Neither server hot-reloads on the VM, so both are bounced.
                         Build the bundle here where the checkout + GitHub live; the other
                         subcommands (shell/tunnel/svc) are what the laptops run against the VM.
                         COMMITTED work only — the bundle ships the branch's last commit, NOT your
                         working tree. Commit first, or uncommitted/staged/untracked files stay behind.

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

# ---- bundle + fetch (+optional checkout) — the shared code-sync primitive -
# Rebuilds the VM's bundle 'remote' from THIS dev checkout, git-fetches on the VM, and (when
# arg 2 == "checkout") points the VM working tree at the branch. Single source of truth for the
# sync: both `push-bundle` and `deploy` call it, so the plumbing never drifts between them.
# MUST run from inside the lupin checkout (it builds a local `git bundle`), i.e. FROM THE DEV BOX.
#
# COMMITTED WORK ONLY: `git bundle create <file> <branch>` packs the branch's committed tip.
# Working-tree edits, staged-but-uncommitted changes, and untracked files are EXCLUDED by
# construction — nothing in-motion ever ships. ⇒ commit before you deploy, or the VM gets the
# branch's LAST COMMIT, not your live editor state.
#   $1 branch        (empty ⇒ this repo's current branch)
#   $2 "checkout"    (anything else ⇒ fetch-only: refs update, working tree unchanged)
do_push_bundle() {
    local branch="$1" do_checkout="$2"
    require_project
    local repo_root
    repo_root="$( git -C "$( dirname "${BASH_SOURCE[0]}" )" rev-parse --show-toplevel 2>/dev/null )" \
        || die "must run from inside the lupin git checkout (bundle is built here, on the dev box)"
    [ -n "$branch" ] || branch="$( git -C "$repo_root" rev-parse --abbrev-ref HEAD )"
    local vm_bundle="/mnt/lupin-data/lupin-wip.bundle"
    local safe="-c safe.directory=$VM_ROOT"        # root's gitconfig lacks the 1001-owned-repo exception
    log "bundling branch '$branch' from $repo_root"
    if [ "$DRY_RUN" -eq 1 ]; then
        log "(dry-run) git bundle create <tmp> $branch; scp -> VM:/tmp; cp -> $vm_bundle; sudo git fetch origin $branch; chown 1001 .git$( [ "$do_checkout" = checkout ] && echo "; sudo git checkout -B $branch FETCH_HEAD; chown 1001 tree" )"
        return 0
    fi
    local bundle_tmp
    bundle_tmp="$( mktemp -t lupin-bundle-XXXXXX.bundle )"
    git -C "$repo_root" bundle create "$bundle_tmp" "$branch" || die "git bundle failed"
    log "scp bundle -> $VM_NAME:/tmp/lupin-wip.bundle"
    gcloud compute scp "$bundle_tmp" "$VM_NAME:/tmp/lupin-wip.bundle" \
        --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap
    rm -f "$bundle_tmp"
    # Overwrite the bundle in place (admin owns the file), fetch as root with an inline
    # safe.directory, restore .git ownership to 1001. Optional working-tree checkout.
    local rcmd="cp /tmp/lupin-wip.bundle $vm_bundle && rm -f /tmp/lupin-wip.bundle && cd $VM_ROOT && sudo git $safe fetch origin $branch && sudo chown -R 1001:1001 .git && echo FETCHED && git $safe log --oneline -1 FETCH_HEAD"
    if [ "$do_checkout" = checkout ]; then
        rcmd="$rcmd && sudo git $safe checkout -B $branch FETCH_HEAD && sudo chown -R 1001:1001 . && echo CHECKED_OUT && git $safe rev-parse --abbrev-ref HEAD"
    fi
    log "refreshing bundle + fetch on VM$( [ "$do_checkout" = checkout ] && echo ' (+checkout)' )"
    gcloud compute ssh "$VM_NAME" \
        --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap \
        --command "$rcmd"
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

    push-repo)
        # Copy a LOCAL git checkout onto the VM data disk as a sibling of lupin, via archive+SCP
        # (the same auth-free pattern lupin itself was deployed with). The VM has no git creds /
        # SSH key, so a direct `git clone` of a private repo can't work there — this side-steps that.
        # Captures tracked files at HEAD (no .git, no untracked). Lands at /mnt/lupin-data/<name>.
        LOCAL_PATH="${1:-}"
        [ -n "$LOCAL_PATH" ] || die "push-repo needs a local repo path:  lupin-vm.sh push-repo /path/to/repo [dest-name]"
        [ -d "$LOCAL_PATH/.git" ] || die "$LOCAL_PATH is not a git checkout (no .git)"
        DEST_NAME="${2:-$( basename "$LOCAL_PATH" )}"
        DATA_ROOT="/mnt/lupin-data"
        require_project
        TARBALL="$( mktemp -t "lupin-pushrepo-XXXXXX.tar.gz" )"
        log "archiving $LOCAL_PATH @ HEAD -> $DEST_NAME.tar.gz"
        if [ "$DRY_RUN" -eq 1 ]; then
            log "(dry-run) would: git archive HEAD | gzip; gcloud compute scp -> VM:/tmp; sudo tar -xz -C $DATA_ROOT; chown 1001"
        else
            git -C "$LOCAL_PATH" archive --format=tar --prefix="$DEST_NAME/" HEAD | gzip > "$TARBALL" \
                || die "git archive failed"
            log "scp -> $VM_NAME:/tmp/$DEST_NAME.tar.gz"
            gcloud compute scp "$TARBALL" "$VM_NAME:/tmp/$DEST_NAME.tar.gz" \
                --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap
            log "extracting on VM -> $DATA_ROOT/$DEST_NAME (owner 1001)"
            gcloud compute ssh "$VM_NAME" \
                --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap \
                --command "sudo mkdir -p $DATA_ROOT && sudo rm -rf $DATA_ROOT/$DEST_NAME && sudo tar -xzf /tmp/$DEST_NAME.tar.gz -C $DATA_ROOT && sudo chown -R 1001:1001 $DATA_ROOT/$DEST_NAME && rm -f /tmp/$DEST_NAME.tar.gz && echo INSTALLED $DATA_ROOT/$DEST_NAME && ls -ld $DATA_ROOT/$DEST_NAME"
            rm -f "$TARBALL"
        fi
        ;;

    push-bundle)
        # Refresh the VM's git "remote" (a local bundle file) from THIS dev checkout, so a plain
        # `git fetch`/`pull` on the VM sees current commits. The VM has no GitHub creds, so its origin
        # is /mnt/lupin-data/lupin-wip.bundle — a portable, offline stand-in for a remote. We rebuild
        # that file here (where GitHub + the current code live) and ship it over.
        #
        #   push-bundle [branch] [--checkout]
        #     branch     defaults to this repo's current branch
        #     --checkout ALSO points the VM working tree at the branch (git checkout -B). WITHOUT it,
        #                the fetch only updates refs — the VM's working tree/branch is UNCHANGED
        #                (answering "does the branch get checked out?": no, not unless you ask).
        #
        # NOTE: push-bundle syncs CODE only; it does NOT restart the servers. For a full
        # code-and-restart cycle (checkout + bounce :7999 + :8001 + verify), use `deploy`.
        DO_CHECKOUT=""
        BRANCH=""
        for a in "$@"; do
            case "$a" in
                --checkout) DO_CHECKOUT="checkout" ;;
                --*)        die "push-bundle: unknown flag $a" ;;
                *)          [ -z "$BRANCH" ] && BRANCH="$a" ;;
            esac
        done
        do_push_bundle "$BRANCH" "$DO_CHECKOUT"
        ;;

    deploy)
        # FULL deploy — the one-shot code-and-restart cycle. Runs FROM THE DEV BOX (it builds a
        # local `git bundle`, which needs the checkout + GitHub that live here). Steps:
        #   1. bundle THIS branch -> ship -> git fetch + checkout on the VM (moves the bind-mounted
        #      ./src that both servers serve),
        #   2. restart :7999 lupin-rest (docker compose force-recreate) — LUPIN_ENV=testing means
        #      uvicorn --reload is OFF on the VM, so a checkout alone does NOT pick up new code,
        #   3. restart :8001 arbiter (host `systemd --user` unit — reload=False by design),
        #   4. verify: print the checked-out HEAD and probe /health on :7999 and :8001.
        #
        #   deploy [branch]        branch defaults to this repo's current branch
        require_project
        DEPLOY_BRANCH="${1:-}"
        # 1. sync code + move the working tree
        do_push_bundle "$DEPLOY_BRANCH" "checkout"
        # 2-4. restart both servers, then verify. `systemctl --user` needs XDG_RUNTIME_DIR wired
        #      up for the non-interactive SSH session; the arbiter bounce is best-effort (a failure
        #      is warned, not fatal) and the :8001 /health probe is the real proof it came back.
        RESTART_CMD="set -e
cd $VM_ROOT
echo '== [1/3] restart :$APP_PORT $REST_SERVICE (docker compose) =='
sudo docker compose -f $COMPOSE_FILE --env-file $ENV_FILE up -d --force-recreate $REST_SERVICE
echo '== [2/3] restart :$ARBITER_PORT arbiter ($ARBITER_SERVICE, systemd --user) =='
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
systemctl --user restart $ARBITER_SERVICE || echo 'WARN: arbiter systemctl --user restart failed — may need an interactive login or loginctl enable-linger; check the :$ARBITER_PORT probe below'
echo '== [3/3] verify =='
echo -n 'HEAD: '; git -c safe.directory=$VM_ROOT rev-parse --short HEAD
for p in $APP_PORT $ARBITER_PORT; do
  st=DOWN
  for i in 1 2 3 4 5 6; do
    st=\$(python3 -c \"import urllib.request,sys; sys.stdout.write(str(urllib.request.urlopen('http://127.0.0.1:'+'\$p'+'/health', timeout=5).status))\" 2>/dev/null) && break
    sleep 5
  done
  echo \":\$p health -> \$st\"
done"
        if [ "$DRY_RUN" -eq 1 ]; then
            log "(dry-run) restart+verify on VM:"
            printf '%s\n' "$RESTART_CMD" >&2
        else
            log "restarting :$APP_PORT rest + :$ARBITER_PORT arbiter, then verifying"
            gcloud compute ssh "$VM_NAME" \
                --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap \
                --command "$RESTART_CMD"
        fi
        ;;

    -h|--help|help)
        usage
        ;;

    *)
        die "unknown subcommand: $SUBCMD  (try: lupin-vm.sh --help)"
        ;;
esac
