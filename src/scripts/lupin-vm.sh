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
VM_PIP_ROOT="/mnt/lupin-data/planning-is-prompting"  # sibling PIP checkout on the VM (push-env exports PLANNING_IS_PROMPTING_ROOT)
VM_DEEPILY_PROJECTS_DIR="/mnt/lupin-data"       # parent of the on-VM checkouts; push-env exports DEEPILY_PROJECTS_DIR (referenced by the shipped alias library)
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
# Keep idle SSH-over-IAP sessions alive. Without a keepalive, an idle interactive `shell` (or a
# long `svc logs -f`) gets reaped by the IAP tunnel / NAT idle timeout -> "Failed to send all data
# from [stdin]" + "Broken pipe" + exit 255 (a dropped session while you step away — NOT a stale
# server-side idle value; the gap was a MISSING client keepalive). ssh sends a probe every 60s and
# gives up after 3 unanswered (~3 min). `-oX=Y` is glued (no space) so each --ssh-flag value is a
# single shell token — safe to word-split from the unquoted expansion below.
SSH_KEEPALIVE="--ssh-flag=-oServerAliveInterval=60 --ssh-flag=-oServerAliveCountMax=3"
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

Deployment contract (task 47c4801b):
  preflight [pre|post|full]
                         assert the VM's deployment contract: env vars vs src/conf/env-contract.tsv,
                         unversioned payloads vs src/conf/vm-unversioned-manifest.tsv, compose-vs-
                         running mount sets, the Cloud SQL socket ITSELF (not the proxy's self-
                         report), and credential ACCEPTANCE with a wrong-key control.
                         Assert-only — every failure prints an executable remedy.
                         `deploy` runs the pre arm before, and the post arm after, automatically.
  push-unversioned       ship the payloads git cannot deliver (gitignored keys, personal-data maps),
                         driven by src/conf/vm-unversioned-manifest.tsv. Rows with local_path '-'
                         are VM-local and only ASSERTED, never copied.

One-off file upload (SCP a single local file anywhere on the VM):
  push-file <local-file> <remote-path>
                         e.g. push-file ./notes.md $VM_ROOT/notes.md
                              push-file ./x.sh    bin/x.sh          (relative => SSH user's \$HOME)
                              push-file ./x.md    $VM_ROOT/src/rnd/  (trailing / keeps the basename)
                         Absolute targets are staged in /tmp and sudo-installed (the SSH user cannot
                         write root/1001-owned dirs); anything under /mnt/lupin-data is chown 1001:1001.

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

Dev-box CLI parity (make the VM host feel like your dev box) — RUN FROM THE DEV BOX:
  install-cli             install Claude Code + the Claude Agent SDK on the VM HOST cli. Uses uv to
                          install Python 3.13 (matches the dev box + image), builds the SDK venv on
                          it, symlinks the bundled 'claude'. One-time OAuth is a manual 'claude' run
                          you do afterward. Idempotent.
  push-env                sync your shell env: SCP ~/.bash_aliases + ~/.bash_aliases_to_uc.py to
                          the VM, regenerate ~/.bash_aliases_uc there, wire ~/.bashrc to source
                          both AND export VM-correct LUPIN_ROOT + PLANNING_IS_PROMPTING_ROOT +
                          DEEPILY_PROJECTS_DIR + LUPIN_CC_VENV (operator-owned CC venv) +
                          LUPIN_DEV_EMAIL (notify target-user), and
                          create ~/.lupin/config (lupin CLI) if absent. Re-run anytime. Idempotent.

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
        $SSH_KEEPALIVE \
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
#   $2 mode:
#        ""          fetch-only — refs update, working tree UNCHANGED (push-bundle default)
#        "checkout"  git checkout -B — moves the tree, but ABORTS on any local drift (safe;
#                    push-bundle --checkout). Nothing is discarded.
#        "reset"     git reset --hard FETCH_HEAD then checkout -B — DRIFT-PROOF: forces the
#                    tracked tree to the branch tip, discarding local edits to tracked files and
#                    overwriting colliding untracked files. Does NOT `git clean`, so untracked
#                    non-colliding files (data store, cloud-gpu.env, keys) are PRESERVED. This is
#                    the deploy semantic — a deploy target must mirror the branch. (deploy)
do_push_bundle() {
    local branch="$1" mode="$2"
    require_project
    local repo_root
    repo_root="$( git -C "$( dirname "${BASH_SOURCE[0]}" )" rev-parse --show-toplevel 2>/dev/null )" \
        || die "must run from inside the lupin git checkout (bundle is built here, on the dev box)"
    [ -n "$branch" ] || branch="$( git -C "$repo_root" rev-parse --abbrev-ref HEAD )"
    local vm_bundle="/mnt/lupin-data/lupin-wip.bundle"
    local safe="-c safe.directory=$VM_ROOT"        # root's gitconfig lacks the 1001-owned-repo exception
    log "bundling branch '$branch' from $repo_root"
    local move_desc=""
    case "$mode" in
        checkout) move_desc="; sudo git checkout -B $branch FETCH_HEAD; chown 1001 tree" ;;
        reset)    move_desc="; sudo git reset --hard FETCH_HEAD; sudo git checkout -B $branch FETCH_HEAD; chown 1001 tree" ;;
    esac
    if [ "$DRY_RUN" -eq 1 ]; then
        log "(dry-run) git bundle create <tmp> $branch; scp -> VM:/tmp; cp -> $vm_bundle; sudo git fetch origin $branch; chown 1001 .git$move_desc"
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
    case "$mode" in
        checkout)
            rcmd="$rcmd && sudo git $safe checkout -B $branch FETCH_HEAD && sudo chown -R 1001:1001 . && echo CHECKED_OUT && git $safe rev-parse --abbrev-ref HEAD" ;;
        reset)
            # DRIFT-PROOF: reset --hard forces the tracked tree to FETCH_HEAD (discards local
            # tracked edits, overwrites colliding untracked), then checkout -B relabels HEAD onto
            # the branch (now clean, so it can't abort). No `git clean` — untracked non-colliding
            # files (data/env/keys) survive.
            rcmd="$rcmd && sudo git $safe reset --hard FETCH_HEAD && sudo git $safe checkout -B $branch FETCH_HEAD && sudo chown -R 1001:1001 . && echo RESET_CHECKED_OUT && git $safe rev-parse --abbrev-ref HEAD" ;;
    esac
    log "refreshing bundle + fetch on VM$( [ -n "$mode" ] && echo " (+$mode)" )"
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
            --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap \
            $SSH_KEEPALIVE
        ;;

    run)
        [ -n "${1:-}" ] || die "run needs a command:  lupin-vm.sh run \"docker ps\""
        require_project
        runit gcloud compute ssh "$VM_NAME" \
            --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap \
            $SSH_KEEPALIVE \
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
        # Even pinned, macOS gcloud still emits benign per-connection "[Errno 9] Bad file descriptor"
        # tracebacks + "Failed to send all data" WARNINGs as the browser opens/closes sockets — the
        # tunnel is fully working. --verbosity=critical suppresses that log spam. Override for debugging:
        #   TUNNEL_VERBOSITY=info src/scripts/lupin-vm.sh tunnel 6999
        # NOTE: a real startup failure still shows as the command exiting WITHOUT a "Listening on port"
        # line (the browser then won't load), so quieting the logger does not hide a dead tunnel.
        local_verbosity="${TUNNEL_VERBOSITY:-critical}"
        log "tunnel: 127.0.0.1:$local_port -> $VM_NAME:$APP_PORT  (browse http://127.0.0.1:$local_port ; Ctrl-C to end; TUNNEL_VERBOSITY=info for full logs)"
        runit gcloud compute start-iap-tunnel "$VM_NAME" "$APP_PORT" \
            --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" \
            --local-host-port="127.0.0.1:$local_port" \
            --verbosity="$local_verbosity"
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

    push-file)
        # One-line upload of a SINGLE local file to an arbitrary path on the VM, over the same
        # IAP-only SCP path everything else here uses. Complements push-repo (whole checkout) and
        # push-bundle (git refs): this is the "just get this one file over there" primitive.
        #
        #   push-file <local-file> <remote-path>
        #
        # Target routing — the SSH user is NOT root and NOT uid 1001, so it can only write its own
        # $HOME. Two paths, chosen by the shape of <remote-path>:
        #   relative / '~/...'  -> scp writes it DIRECTLY (lands under the SSH user's home)
        #   absolute '/...'     -> staged in /tmp, then `sudo install`ed to the target (a direct scp
        #                          to e.g. $VM_ROOT would fail "Permission denied")
        # Files landing under $VM_DEEPILY_PROJECTS_DIR get chown 1001:1001 — the UID that owns the
        # on-VM checkouts — so the app container (and the checkout's own tooling) can read them.
        # NOTE: quote a '~/...' target ('~/x.md'), else your LOCAL shell expands it to /home/<you>.
        LOCAL_FILE="${1:-}"
        REMOTE_PATH="${2:-}"
        [ -n "$LOCAL_FILE" ] && [ -n "$REMOTE_PATH" ] \
            || die "push-file needs a source AND a target:  lupin-vm.sh push-file ./notes.md $VM_ROOT/notes.md"
        [ -f "$LOCAL_FILE" ] || die "not a readable local file: $LOCAL_FILE  (push-file takes ONE file; use push-repo for a checkout)"
        require_project
        # A trailing slash means "into this directory" — keep the local basename.
        case "$REMOTE_PATH" in
            */) REMOTE_PATH="$REMOTE_PATH$( basename "$LOCAL_FILE" )" ;;
        esac
        case "$REMOTE_PATH" in
            /*)
                REMOTE_DIR="$( dirname "$REMOTE_PATH" )"
                STAGE="/tmp/lupin-pushfile-$$-$( basename "$LOCAL_FILE" )"
                # chown only under the data disk; elsewhere (/etc, /opt, ...) leave root ownership.
                CHOWN_CMD="true"
                case "$REMOTE_PATH" in
                    "$VM_DEEPILY_PROJECTS_DIR"/*) CHOWN_CMD="sudo chown 1001:1001 $REMOTE_PATH" ;;
                esac
                if [ "$DRY_RUN" -eq 1 ]; then
                    log "(dry-run) gcloud compute scp $LOCAL_FILE $VM_NAME:$STAGE; then on VM: sudo mkdir -p $REMOTE_DIR && sudo install -m 644 $STAGE $REMOTE_PATH && rm -f $STAGE && $CHOWN_CMD"
                else
                    log "scp $LOCAL_FILE -> $VM_NAME:$STAGE (staging)"
                    gcloud compute scp "$LOCAL_FILE" "$VM_NAME:$STAGE" \
                        --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap
                    log "installing -> $REMOTE_PATH"
                    gcloud compute ssh "$VM_NAME" \
                        --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap \
                        --command "sudo mkdir -p $REMOTE_DIR && sudo install -m 644 $STAGE $REMOTE_PATH && rm -f $STAGE && $CHOWN_CMD && echo UPLOADED && ls -l $REMOTE_PATH"
                fi
                ;;
            *)
                # Home-relative (or a quoted '~/...') — scp can write it directly, no sudo needed.
                log "scp $LOCAL_FILE -> $VM_NAME:$REMOTE_PATH (SSH user's home)"
                runit gcloud compute scp "$LOCAL_FILE" "$VM_NAME:$REMOTE_PATH" \
                    --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap
                ;;
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
        # 0. PRE-flight (Rick's ruling 2026-07-26 — run BOTH arms). Answers "is this VM fit
        #    to deploy onto?" BEFORE anything is touched. Skips B-parity (HEAD is about to
        #    change) and D (the server is about to restart). A blocking failure here aborts
        #    the deploy; set LUPIN_SKIP_PREFLIGHT=1 to override deliberately.
        #    Running both arms is what distinguishes "the deploy broke it" from "it was
        #    already broken" — the diagnosis that cost five minutes of bisection on 07-26.
        if [ "${LUPIN_SKIP_PREFLIGHT:-0}" != "1" ]; then
            log "PRE-deploy preflight (--phase pre)"
            if ! gcloud compute ssh "$VM_NAME" \
                    --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap \
                    $SSH_KEEPALIVE \
                    --command "cd $VM_ROOT && bash src/scripts/preflight-vm.sh --phase pre"; then
                die "PRE-deploy preflight FAILED — the VM is not fit to deploy onto. Fix the blocking items above, or re-run with LUPIN_SKIP_PREFLIGHT=1 to override."
            fi
        else
            log "PRE-deploy preflight SKIPPED (LUPIN_SKIP_PREFLIGHT=1)"
        fi
        # 1. sync code + FORCE the working tree to the branch (reset --hard; drift-proof, since a
        #    deploy target must mirror the branch and may have drifted). Preserves untracked
        #    data/env/keys — no git clean.
        do_push_bundle "$DEPLOY_BRANCH" "reset"
        # 2-4. restart both servers, then verify. `systemctl --user` needs XDG_RUNTIME_DIR wired
        #      up for the non-interactive SSH session; the arbiter bounce is best-effort (a failure
        #      is warned, not fatal) and the :8001 /health probe is the real proof it came back.
        RESTART_CMD="set -e
cd $VM_ROOT
echo '== [1/3] restart :$APP_PORT $REST_SERVICE (docker compose) =='
# --no-deps is NOT optional (bug 70794d58, took :7999 down 2026-07-26). Without it,
# compose re-runs cloudsql-socket-init, whose \`rm -f /cloudsql/*/.s.PGSQL.5432\` DELETES
# the live socket the already-running proxy owns. The proxy binds once at start and never
# re-creates it, so every app connect then fails "No such file or directory" and lupin-rest
# crash-loops — while \`docker ps\` still reads "healthy", because the proxy healthcheck
# probes :9090 and never touches the socket. The hand-run recreate on 2026-07-25 passed
# --no-deps for exactly this reason; this automated path did not, and the runbook had
# already written "Filing recommended" about it a day before it bit.
sudo docker compose -f $COMPOSE_FILE --env-file $ENV_FILE up -d --no-deps --force-recreate $REST_SERVICE
echo '== [2/3] restart :$ARBITER_PORT arbiter ($ARBITER_SERVICE, systemd --user) =='
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
systemctl --user restart $ARBITER_SERVICE || echo 'WARN: arbiter systemctl --user restart failed — may need an interactive login or loginctl enable-linger; check the :$ARBITER_PORT probe below'
echo '== [3/3] verify =='
echo -n 'HEAD: '; git -c safe.directory=$VM_ROOT rev-parse --short HEAD
# Health window: :7999 lupin-rest is a SLOW boot (config + postgres + snapshot manager +
# commons ~50-60s), so probe up to ~2min before calling it DOWN — a 30s window false-flagged a
# healthy deploy. :8001 arbiter answers on the first try. 18 tries x 8s = 144s ceiling.
for p in $APP_PORT $ARBITER_PORT; do
  st=DOWN
  for i in \$(seq 1 18); do
    st=\$(python3 -c \"import urllib.request,sys; sys.stdout.write(str(urllib.request.urlopen('http://127.0.0.1:'+'\$p'+'/health', timeout=5).status))\" 2>/dev/null) && break
    sleep 8
  done
  echo \":\$p health -> \$st (after ~\$((i*8))s)\"
done
echo '== [4/4] POST-deploy preflight (--phase post) =='
bash src/scripts/preflight-vm.sh --phase post || echo 'POST-deploy preflight reported BLOCKING failures (above). NOT rolling back — a rollback on a half-applied deploy is more dangerous than a named failure. Fix forward.'"
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

    push-unversioned)
        # Ship the payloads GIT CANNOT DELIVER, driven by src/conf/vm-unversioned-manifest.tsv.
        # This category (gitignored secrets, personal data, VM-local config) used to live in
        # somebody's head and a fresh VM rediscovered each member BY FAILING — three times in
        # one day on 2026-07-25, one of which made EVERY transcription 500. The list is data
        # so that adding a payload is a row, not a code edit.
        require_project
        MANIFEST_FILE="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )/src/conf/vm-unversioned-manifest.tsv"
        [ -r "$MANIFEST_FILE" ] || die "manifest not readable: $MANIFEST_FILE"
        DEV_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )"
        shipped=0; skipped_rows=0
        while IFS=$'\t' read -r m_local m_remote m_owner m_mode m_req; do
            case "$m_local" in ''|'#'*) continue ;; esac
            # local_path '-' means "VM-local, do NOT copy from dev" (e.g. cloud-gpu.env holds
            # VM-correct values a copy would clobber). Preflight still ASSERTS its presence.
            if [ "$m_local" = "-" ]; then
                log "skip (VM-local, assert-only): $m_remote"
                skipped_rows=$(( skipped_rows + 1 )); continue
            fi
            src_path="$m_local"
            case "$src_path" in /*) ;; *) src_path="$DEV_ROOT/$m_local" ;; esac
            if [ ! -e "${src_path%/}" ]; then
                log "WARN: local payload missing, cannot ship: $src_path"
                continue
            fi
            log "shipping $src_path -> $m_remote"
            if [ "$DRY_RUN" -eq 1 ]; then
                log "(dry-run) would push-file $src_path $m_remote (owner=$m_owner mode=$m_mode)"
            else
                case "$m_local" in
                    */) # directory: tar over the wire, then unpack with owner/mode applied
                        tarball="$( mktemp -t lupin-unversioned-XXXXXX.tgz )"
                        tar -czf "$tarball" -C "$( dirname "${src_path%/}" )" "$( basename "${src_path%/}" )"
                        gcloud compute scp "$tarball" "$VM_NAME:/tmp/lupin-unversioned.tgz" \
                            --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap
                        rm -f "$tarball"
                        gcloud compute ssh "$VM_NAME" --zone="$VM_ZONE" \
                            --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap $SSH_KEEPALIVE \
                            --command "sudo mkdir -p $( dirname "${m_remote%/}" ) && sudo tar -xzf /tmp/lupin-unversioned.tgz -C $( dirname "${m_remote%/}" ) && rm -f /tmp/lupin-unversioned.tgz && [ '$m_owner' = '-' ] || sudo chown -R $m_owner ${m_remote%/}"
                        ;;
                    *)  "$0" push-file "$src_path" "$m_remote"
                        [ "$m_mode" = "-" ] || gcloud compute ssh "$VM_NAME" --zone="$VM_ZONE" \
                            --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap $SSH_KEEPALIVE \
                            --command "sudo chmod $m_mode $m_remote && [ '$m_owner' = '-' ] || sudo chown $m_owner $m_remote"
                        ;;
                esac
            fi
            shipped=$(( shipped + 1 ))
        done < <( grep -v '^[[:space:]]*#' "$MANIFEST_FILE" | grep -v '^[[:space:]]*$' )
        log "push-unversioned done: $shipped shipped, $skipped_rows VM-local (assert-only)"
        log "verify with: lupin-vm.sh run \"cd $VM_ROOT && bash src/scripts/preflight-vm.sh --phase pre\""
        ;;

    creds-status)
        # R2 — print every authority for the notification API key SIDE BY SIDE.
        #
        # WHY: "the notification API key" is FIVE surfaces over TWO independent
        # validators, and BOTH of 2026-07-25's outages were the same defect at a
        # different validator — STT 401 (Secret Manager version eight months
        # stale) and DM missing_auth_header (the key file held the DEV BOX's key,
        # unregistered in the VM's database). Each surface looked fine on its own.
        # Nothing compared them, so nobody could see that they disagreed.
        #
        # THE ASYMMETRY THAT SHAPES THIS VERB: four surfaces hold a VALUE and can
        # be fingerprinted and compared. The fifth — the bcrypt row in the
        # server's api_keys table — is a one-way hash and can NEVER be compared,
        # only EXERCISED. That is why the acceptance probe is the design and not
        # a shortcut: for that validator, a request is the only question you can
        # ask. Fingerprints alone would leave the one surface that actually
        # rejects you unmeasured.
        require_project
        DEV_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )"
        PFV_LIB="$DEV_ROOT/src/scripts/lib/preflight-vm-lib.sh"
        [ -r "$PFV_LIB" ] || die "preflight lib not readable: $PFV_LIB"
        # shellcheck source=lib/preflight-vm-lib.sh
        source "$PFV_LIB"

        CS_TARGET="${2:-local}"           # which ~/.lupin/config section to read
        CS_KEYFILE="$DEV_ROOT/src/conf/keys/notification-api-claude-code-dev"
        CS_SECRET_NAME="${LUPIN_NOTIFICATION_KEY_SECRET:-lupin-notification-api-key}"

        printf '\n%s\n' "== notification API key — every authority, side by side =="
        printf '%s\n\n' "   (fingerprints are sha256 prefixes; values are NEVER printed)"

        # ── surface 1: the in-repo key file ──────────────────────────────────
        # `set -e` is ON in this script. A bare `var=$(cmd)` ABORTS when cmd
        # returns non-zero — which here is ABSENT/UNREADABLE/EMPTY, i.e. every
        # state this verb exists to report. `|| rc=$?` keeps the branch alive.
        cs_rc=0; cs_file_val="$( pfv_read_secret_file "$CS_KEYFILE" )" || cs_rc=$?
        if [ $cs_rc -eq 0 ]; then cs_fp_file="$( pfv_secret_fingerprint "$cs_file_val" )"
        else cs_fp_file="$cs_file_val"; fi
        printf '  %-34s %s\n' "key file" "$cs_fp_file"
        [ $cs_rc -eq 2 ] && printf '  %-34s %s\n' "" "^ mode/uid — this was the 2026-07-25 defect; try: sudo cat"

        # ── surface 2: the LUPIN_API_KEY env var ─────────────────────────────
        if [ -n "${LUPIN_API_KEY:-}" ]; then cs_fp_env="$( pfv_secret_fingerprint "$LUPIN_API_KEY" )"
        else cs_fp_env="UNSET"; fi
        printf '  %-34s %s\n' "LUPIN_API_KEY env" "$cs_fp_env"

        # ── surface 3: whatever ~/.lupin/config's api_key_file points at ─────
        cs_cfg_path="$( awk -v sect="[$CS_TARGET]" '
            $0 == sect { inside = 1; next }
            /^\[/      { inside = 0 }
            inside && $1 == "api_key_file" { print $3; exit }
        ' "$HOME/.lupin/config" 2>/dev/null )"
        if [ -n "$cs_cfg_path" ]; then
            cs_cfg_path="${cs_cfg_path/#\~/$HOME}"
            cs_rc=0; cs_cfg_val="$( pfv_read_secret_file "$cs_cfg_path" )" || cs_rc=$?
            if [ $cs_rc -eq 0 ]; then cs_fp_cfg="$( pfv_secret_fingerprint "$cs_cfg_val" )"
            else cs_fp_cfg="$cs_cfg_val"; fi
        else
            cs_fp_cfg="NO-api_key_file-IN-[$CS_TARGET]"
        fi
        printf '  %-34s %s\n' "~/.lupin/config [$CS_TARGET]" "$cs_fp_cfg"
        [ -n "$cs_cfg_path" ] && printf '  %-34s -> %s\n' "" "$cs_cfg_path"

        # ── surface 4: Secret Manager ────────────────────────────────────────
        # UNAVAILABLE is reported as its own state. A tool that silently omitted
        # this row when gcloud is absent would let a stale Secret Manager version
        # — one of the two 07-25 outages — sit unexamined behind a clean report.
        if command -v gcloud >/dev/null 2>&1; then
            cs_sm_val="$( gcloud secrets versions access latest --secret="$CS_SECRET_NAME" \
                          --project="$LUPIN_GCP_PROJECT_ID" 2>/dev/null | tr -d '\n\r' )"
            if [ -n "$cs_sm_val" ]; then cs_fp_sm="$( pfv_secret_fingerprint "$cs_sm_val" )"
            else cs_fp_sm="ABSENT-OR-DENIED"; fi
        else
            cs_fp_sm="UNAVAILABLE (no gcloud on this host)"
        fi
        printf '  %-34s %s\n' "Secret Manager/$CS_SECRET_NAME" "$cs_fp_sm"

        # ── the comparison ───────────────────────────────────────────────────
        printf '\n'
        cs_rc=0
        pfv_fingerprints_agree "$cs_fp_file" "$cs_fp_env" "$cs_fp_cfg" "$cs_fp_sm" || cs_rc=$?
        # Count coverage and name the gaps. "AGREES" over two surfaces reads
        # exactly like "AGREES" over four unless the denominator is printed —
        # and with the key file ABSENT the agreeing pair may not include the
        # surface the caller actually uses.
        cs_ncomp=0; cs_gaps=""
        for cs_pair in "key-file:$cs_fp_file" "env:$cs_fp_env" "config:$cs_fp_cfg" "secret-manager:$cs_fp_sm"; do
            case "${cs_pair#*:}" in
                sha256:*) cs_ncomp=$(( cs_ncomp + 1 )) ;;
                *)        cs_gaps="$cs_gaps ${cs_pair%%:*}" ;;
            esac
        done
        [ -n "$cs_gaps" ] && printf '  COVERAGE: %s of 4 surfaces yielded a value; NOT compared:%s\n' "$cs_ncomp" "$cs_gaps"

        case $cs_rc in
            0) printf '  VERDICT: the %s comparable surface(s) AGREE\n' "$cs_ncomp" ;;
            1) printf '  VERDICT: ⚠️  SURFACES DISAGREE — at least two hold different keys\n'
               printf '           Both 2026-07-25 outages were exactly this, at different validators.\n' ;;
            2) printf '  VERDICT: NOT COMPARABLE — fewer than two surfaces yielded a value.\n'
               printf '           This is NOT agreement. One surface cannot corroborate itself.\n' ;;
        esac

        # ── surface 5: the DB bcrypt row — EXERCISE, with a control ──────────
        # A 200 alone does not prove the key was checked. Only a 401 on a
        # deliberately-wrong key proves the endpoint enforces the header at all;
        # without that arm, an endpoint that ignores X-API-Key reports success
        # for any key, including a wrong one.
        printf '\n%s\n' "== the fifth surface: the api_keys bcrypt row (exercise only) =="
        CS_URL="${LUPIN_CREDS_STATUS_URL:-http://localhost:$APP_PORT}"
        if [ "$cs_fp_file" != "${cs_fp_file#sha256:}" ]; then
            cs_good="$( curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H "X-API-Key: $cs_file_val" "$CS_URL/api/dm/list" 2>/dev/null )"
            cs_bad="$(  curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H "X-API-Key: creds-status-deliberately-invalid" "$CS_URL/api/dm/list" 2>/dev/null )"
            printf '  %-34s good=%s  wrong-key control=%s\n' "$CS_URL" "$cs_good" "$cs_bad"
            if   [ "$cs_good" = "200" ] && [ "$cs_bad" = "401" ]; then
                printf '  VERDICT: key ACCEPTED, and the control proves the header is enforced\n'
            elif [ "$cs_good" = "200" ] && [ "$cs_bad" = "200" ]; then
                printf '  VERDICT: ⚠️  PROBE IS VACUOUS — the wrong key also returned 200.\n'
                printf '           This endpoint is not checking the header; the 200 above means nothing.\n'
            elif [ "$cs_good" = "401" ]; then
                printf '  VERDICT: ⚠️  key REJECTED — readable, but NOT registered in THIS database.\n'
                printf '           Mint one against this deployment; a key from another is never valid here.\n'
            else
                printf '  VERDICT: inconclusive (good=%s bad=%s) — is the app up at %s?\n' "$cs_good" "$cs_bad" "$CS_URL"
            fi
        else
            printf '  SKIPPED: no readable key file to probe with (%s)\n' "$cs_fp_file"
        fi
        printf '\n'
        ;;

    preflight)
        # Standalone preflight. PHASE defaults to full; pass pre|post|full.
        #
        # BOTH SPELLINGS ACCEPTED (row c8f60c22). This verb took a bare POSITIONAL
        # while the script it wraps takes `--phase <val>`, so the obvious
        # `lupin-vm.sh preflight --phase pre` forwarded `--phase --phase` and the
        # inner script aborted. It aborted LOUDLY — the design working — but the
        # failure named the INNER script's argument handling for a mistake made at
        # the OUTER verb, which sends the reader to the wrong file. Two interfaces
        # for one concept, with nothing reconciling them.
        #
        # The whitelist below is also what keeps this safe to interpolate: PF_PHASE
        # is pasted into the remote `--command` string, so an unvalidated value is
        # an injection point as well as a typo.
        require_project
        PF_PHASE="${1:-full}"
        [ "$PF_PHASE" = "--phase" ] && PF_PHASE="${2:-}"      # accept the inner script's own spelling
        case "$PF_PHASE" in
            pre|post|full) ;;
            "") die "preflight: --phase given with no value. Usage: lupin-vm.sh preflight [pre|post|full]" ;;
            *)  die "preflight: unknown phase '$PF_PHASE'. Expected one of: pre, post, full (or --phase <one of those>)." ;;
        esac
        runit gcloud compute ssh "$VM_NAME" \
            --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap \
            $SSH_KEEPALIVE \
            --command "cd $VM_ROOT && bash src/scripts/preflight-vm.sh --phase $PF_PHASE"
        ;;

    install-cli)
        # Install Claude Code + the Claude Agent SDK on the VM's HOST command line (NOT inside the
        # app container — the image has them, but that's unreachable for interactive host use).
        # Uses uv (astral) to install Python 3.13 — the SAME python-build-standalone lineage the
        # Docker image bakes (docker/lupin/Dockerfile:281) — so the VM host is COMMENSURATE with the
        # dev box + image (both 3.13), not the VM's system 3.10. uv also sidesteps the base image's
        # missing python3-venv/ensurepip. The SDK venv lands on 3.13; its bundled `claude` binary is
        # symlinked onto PATH (mirrors Dockerfile:337-341). One install → Agent SDK + interactive
        # `claude`. Idempotent. OAuth is a one-time INTERACTIVE step you run yourself: `claude`.
        require_project
        RCMD_INSTALL="set -e
mkdir -p ~/.local/bin ~/.venvs
echo '== install uv (astral) =='
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH=\"\$HOME/.local/bin:\$PATH\"
echo -n 'uv '; uv --version
echo '== install Python 3.13 via uv (python-build-standalone — matches the image) =='
uv python install 3.13
echo '== create the Claude Agent SDK venv on 3.13 =='
uv venv --clear --python 3.13 ~/.venvs/claude-agent-sdk
echo '== install claude-agent-sdk into the venv =='
uv pip install --python ~/.venvs/claude-agent-sdk/bin/python -q claude-agent-sdk
echo '== symlink bundled claude -> ~/.local/bin/claude =='
CLAUDE_BIN=\$(~/.venvs/claude-agent-sdk/bin/python -c 'import claude_agent_sdk as m, pathlib as p; print(p.Path(m.__file__).parent / \"_bundled\" / \"claude\")')
ln -sf \"\$CLAUDE_BIN\" ~/.local/bin/claude
echo '== ensure ~/.local/bin on PATH (append to ~/.bashrc if missing) =='
grep -qxF 'export PATH=\"\$HOME/.local/bin:\$PATH\"' ~/.bashrc || echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc
echo '== versions =='
echo -n 'python '; ~/.venvs/claude-agent-sdk/bin/python --version
~/.local/bin/claude --version || echo '(claude installed; run it once interactively to OAuth login)'
~/.venvs/claude-agent-sdk/bin/python -c 'import claude_agent_sdk as m; print(\"claude-agent-sdk\", getattr(m, \"__version__\", \"?\"))'
echo 'NEXT (manual, interactive): open a fresh shell, run  claude  once, complete the OAuth login.'"
        if [ "$DRY_RUN" -eq 1 ]; then
            log "(dry-run) install Claude Code + Agent SDK on VM:"
            printf '%s\n' "$RCMD_INSTALL" >&2
        else
            log "installing Claude Code + Agent SDK on $VM_NAME host"
            gcloud compute ssh "$VM_NAME" \
                --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap \
                --command "$RCMD_INSTALL"
        fi
        ;;

    push-env)
        # Sync your dev-box shell environment to the VM host so both feel identical. SCPs your alias
        # file + the uppercase generator, REGENERATES the uppercase aliases ON the VM (from the just-
        # shipped .bash_aliases), and ensures the VM ~/.bashrc sources both. Re-run whenever you
        # change local aliases. Idempotent (whole-line grep guards, no duplicate source lines).
        require_project
        ALIASES="$HOME/.bash_aliases"
        UC_GEN="$HOME/.bash_aliases_to_uc.py"
        [ -f "$ALIASES" ] || die "no $ALIASES on the dev box"
        [ -f "$UC_GEN" ]  || die "no $UC_GEN on the dev box (the uppercase-alias generator)"
        # NOTE: LUPIN_API_KEY is NOT shipped by push-env. The notify() X-API-Key (ck_live_) is
        # validated per-DATABASE (hash in the server's api_keys table). The VM runs its own test DB,
        # so the dev-box key can never validate there — a VM key must be MINTED against the VM DB
        # (create_service_account_postgres.py with LUPIN_ENV=testing) and set by hand. Shipping the
        # dev key here would only clobber that manual VM key via bashrc ordering. That exclusion is
        # expressed in the CONTRACT (writer = "minted ON the target"), not as a special case here.

        # ── the export set is DERIVED from src/conf/env-contract.tsv (R3b) ──────────
        # WHICH vars push-env writes is the contract's fact, asserted once. WHAT VALUE
        # each takes on the VM is machine-specific and stays here — the contract is
        # deliberately values-free (a path is legitimately /mnt/DATA01/... on dev and
        # /mnt/lupin-data/... on the VM).
        #
        # The two sets are compared IN BOTH DIRECTIONS below, and either mismatch is
        # fatal. That comparison — not the generation — is the point of this change:
        # today the derived set and the map agree exactly, so a check of the form
        # "generated == what we already emit" would pass while proving nothing. What
        # earns its keep is the FUTURE divergence:
        #   contract row with no value   -> preflight would assert the var, tell the
        #                                   operator to "run push-env", and push-env
        #                                   would not write it. A remedy that cannot
        #                                   clear its own alarm.
        #   value with no contract row   -> push-env writes a var nothing declares, so
        #                                   preflight never checks it and its absence
        #                                   on a fresh VM is discovered by failing.
        DEV_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )"
        CONTRACT_FILE="$DEV_ROOT/src/conf/env-contract.tsv"
        PFV_LIB="$DEV_ROOT/src/scripts/lib/preflight-vm-lib.sh"
        [ -r "$PFV_LIB" ]       || die "preflight lib not readable: $PFV_LIB"
        [ -r "$CONTRACT_FILE" ] || die "env contract not readable: $CONTRACT_FILE"
        # shellcheck source=lib/preflight-vm-lib.sh
        source "$PFV_LIB"

        # VM-side VALUES, keyed by contract var name. Single-quoted entries stay
        # LITERAL all the way to the VM (\$HOME must expand THERE, not here).
        declare -A PUSH_ENV_VALUES=(
            [LUPIN_ROOT]="$VM_ROOT"
            [PLANNING_IS_PROMPTING_ROOT]="$VM_PIP_ROOT"
            [DEEPILY_PROJECTS_DIR]="$VM_DEEPILY_PROJECTS_DIR"
            [LUPIN_CC_VENV]='$HOME/.venv-lupin-mcp'
            [LUPIN_DEV_EMAIL]='ricardo.felipe.ruiz@gmail.com'
        )

        CONTRACT_NAMES="$( pfv_contract_push_env_names "$CONTRACT_FILE" )" \
            || die "could not read the push-env var set from $CONTRACT_FILE"
        [ -n "$CONTRACT_NAMES" ] \
            || die "env contract declares NO push-env vars — refusing to write an empty environment to the VM (check the surface/writer columns in $CONTRACT_FILE)"

        # Direction 1 — every contract-declared var must have a value here.
        EXPORT_BLOCK=""
        while IFS= read -r ev_name; do
            [ -n "$ev_name" ] || continue
            [ -n "${PUSH_ENV_VALUES[$ev_name]+set}" ] || die \
                "env-contract.tsv declares $ev_name as push-env-written, but lupin-vm.sh has no VM value for it. Add it to PUSH_ENV_VALUES in the push-env verb, or change that row's writer column in $CONTRACT_FILE."
            ev_line="export $ev_name=${PUSH_ENV_VALUES[$ev_name]}"
            # whole-line grep guard: idempotent, and a CHANGED value appends a new
            # line that wins by bashrc ordering (later export overrides earlier).
            EXPORT_BLOCK="${EXPORT_BLOCK}grep -qxF '$ev_line' ~/.bashrc || echo '$ev_line' >> ~/.bashrc
"
        done <<< "$CONTRACT_NAMES"

        # Direction 2 — no value may exist without a contract row declaring it.
        for ev_name in "${!PUSH_ENV_VALUES[@]}"; do
            printf '%s\n' "$CONTRACT_NAMES" | grep -qxF "$ev_name" || die \
                "lupin-vm.sh would export $ev_name, but no row in $CONTRACT_FILE declares it as push-env-written (surface HOST/BOTH + writer mentioning push-env). Add the contract row, or drop it from PUSH_ENV_VALUES."
        done

        log "push-env will write $( printf '%s\n' "$CONTRACT_NAMES" | grep -c . ) contract-declared vars: $( printf '%s' "$CONTRACT_NAMES" | tr '\n' ' ' )"

        if [ "$DRY_RUN" -eq 1 ]; then
            log "(dry-run) scp $ALIASES + $UC_GEN -> $VM_NAME:~/ ; then on VM: python3 ~/.bash_aliases_to_uc.py; ensure ~/.bashrc sources .bash_aliases + .bash_aliases_uc"
            # Print the generated block. A dry-run that names the vars but hides the
            # VALUES cannot catch the failure this verb actually produces on a VM —
            # a right var carrying a dev-box path. \$HOME must appear UNEXPANDED here;
            # if it reads as /home/rruiz, it will be baked in on the VM too.
            log "(dry-run) would append these lines to the VM ~/.bashrc (if absent):"
            printf '%s' "$EXPORT_BLOCK" | sed 's/^/    /'
        else
            log "scp alias files -> $VM_NAME:~/"
            gcloud compute scp "$ALIASES" "$UC_GEN" "$VM_NAME:~/" \
                --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap
            RCMD_ENV="set -e
echo '== regenerate ~/.bash_aliases_uc on the VM (from the shipped .bash_aliases) =='
python3 ~/.bash_aliases_to_uc.py
echo '== ensure ~/.bashrc sources both alias files (whole-line, idempotent) =='
grep -qxF 'source ~/.bash_aliases'    ~/.bashrc || echo 'source ~/.bash_aliases'    >> ~/.bashrc
grep -qxF 'source ~/.bash_aliases_uc' ~/.bashrc || echo 'source ~/.bash_aliases_uc' >> ~/.bashrc
echo '== export contract-declared vars in ~/.bashrc (whole-line, idempotent; set derived from src/conf/env-contract.tsv) =='
$EXPORT_BLOCK
echo '== ensure ~/.lupin/config exists (lupin CLI: api_url + notification recipient) =='
mkdir -p ~/.lupin
if [ ! -f ~/.lupin/config ]; then
  cat > ~/.lupin/config <<'LUPINCFG'
[environments]
default = local

[local]
api_url = http://localhost:7999
global_notification_recipient = ricardo.felipe.ruiz@gmail.com
LUPINCFG
  echo '   created ~/.lupin/config'
else
  echo '   ~/.lupin/config already present — left as-is'
fi
echo '== done — open a fresh shell (or: source ~/.bashrc) to pick up aliases + roots =='"
            log "regenerating uc aliases + wiring ~/.bashrc on VM"
            gcloud compute ssh "$VM_NAME" \
                --zone="$VM_ZONE" --project="$LUPIN_GCP_PROJECT_ID" --tunnel-through-iap \
                --command "$RCMD_ENV"
        fi
        ;;

    -h|--help|help)
        usage
        ;;

    *)
        die "unknown subcommand: $SUBCMD  (try: lupin-vm.sh --help)"
        ;;
esac
