#!/bin/bash
#
# preflight-vm.sh — assert the DEPLOYMENT CONTRACT of a Lupin VM (task 47c4801b).
#
# Design of record: src/rnd/v0.1.9/2026.07.26-vm-bring-up-automation-preflight-design.md
# Config analysis:  src/rnd/v0.1.9/2026.07.26-configuration-splintering-analysis.md
#
# WHY THIS EXISTS
#   Five days of lupin-host-test debugging produced 30 distinct defects. Only 5 were
#   code bugs; 25 were environment or configuration. A :8000 end-to-end run is
#   structurally blind to all 25 — it runs on the same host, where the host user IS
#   uid 1001 and the keys are the originals. This is the instrument for the other 25.
#
#   The hazard that justifies it: "lupin-vm.sh deploy runs up -d --force-recreate
#   WITHOUT --no-deps" was written into the runbook on 2026-07-25 with the words
#   "Filing recommended". It was never filed, and it took :7999 down on 2026-07-26 in
#   the next session's first deploy. PROSE IS NOT A GUARD.
#
# RUNS ON THE VM. Ship it there and execute in ONE ssh round-trip; 30 probes each
# paying its own round-trip would take minutes.
#
# PHASES (Rick's ruling, 2026-07-26 — run BOTH arms so a failure can be attributed):
#   --phase pre    is this VM fit to deploy ONTO?  (layers A, C, E + the B3 payloads)
#                  skips B-parity  (HEAD is about to change; asserting the old ref
#                  is meaningless) and skips D (probing a server about to restart)
#   --phase post   everything, parity included
#   --phase full   everything (the default, for a standalone run)
#
#   A BLOCK in PRE should stop a deploy before it touches anything.
#   A BLOCK in POST reports loudly and does NOT roll back — a rollback on a
#   half-applied deploy is more dangerous than a named failure.
#
# ASSERT-ONLY (Rick's ruling): every failure prints an executable remedy. Nothing is
# repaired. An assertion that has never been proven to fail cannot be trusted to fix.
#
# Exit codes:
#   0 — no blocking failures (WARNs are non-blocking)
#   1 — one or more blocking failures
#   2 — preflight itself could not run
#
# Usage:
#   src/scripts/preflight-vm.sh [--phase pre|post|full] [-v]
#

set -uo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LIB="$SCRIPT_DIR/lib/preflight-vm-lib.sh"
[ -r "$LIB" ] || { printf '[ABORT] cannot read %s\n' "$LIB" >&2; exit 2; }
# shellcheck source=lib/preflight-vm-lib.sh
source "$LIB"

REPO_ROOT="${LUPIN_ROOT:-$( cd "$SCRIPT_DIR/../.." && pwd )}"
MANIFEST="$REPO_ROOT/src/conf/vm-unversioned-manifest.tsv"
CONTRACT="$REPO_ROOT/src/conf/env-contract.tsv"

PHASE="full"
VERBOSE=false
CONTAINER="${PREFLIGHT_VM_CONTAINER:-lupin-rest-cloud-gpu}"
COMPOSE_FILE="${PREFLIGHT_VM_COMPOSE:-$REPO_ROOT/docker-compose.cloud-gpu.yml}"
VM_PREFIX="${PREFLIGHT_VM_PREFIX:-/mnt/lupin-data}"
APP_URL="${PREFLIGHT_VM_APP_URL:-http://localhost:7999}"
ARBITER_URL="${PREFLIGHT_VM_ARBITER_URL:-http://localhost:8001}"

while [ $# -gt 0 ]; do
    case "$1" in
        --phase) PHASE="${2:-full}"; shift 2 ;;
        -v|--verbose) VERBOSE=true; shift ;;
        -h|--help) sed -n '2,50p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) printf '[ABORT] unknown argument: %s\n' "$1" >&2; exit 2 ;;
    esac
done
case "$PHASE" in pre|post|full) ;; *) printf '[ABORT] bad --phase: %s\n' "$PHASE" >&2; exit 2 ;; esac

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
blocking=0; warned=0; passed=0; skipped=0

say_ok()   { printf "${GREEN}[OK]${NC}    %s\n" "$1"; passed=$(( passed + 1 )); }
say_fail() { printf "${RED}[FAIL]${NC}  %s\n" "$1"; blocking=$(( blocking + 1 )); }
say_warn() { printf "${YELLOW}[WARN]${NC}  %s\n" "$1"; warned=$(( warned + 1 )); }
say_unk()  { printf "${YELLOW}[UNKN]${NC}  %s\n" "$1"; }
say_head() { printf "\n${BOLD}== %s ==${NC}\n" "$1"; }
remedy()   { printf "        ${BOLD}remedy:${NC} %s\n" "$1"; }
dbg()      { [ "$VERBOSE" = true ] && printf "        \$ %s\n" "$*" >&2; return 0; }

# report <outcome> <tier> <message> [remedy]
#   Routes every probe through pfv_classify_probe so UNKNOWN can never be folded
#   into a pass — the rule that a deleted Cloud SQL socket violated by reporting
#   "healthy" for hours on 2026-07-26.
report() {
    local outcome="$1" tier="$2" msg="$3" fix="${4:-}"
    local label rc
    label="$( pfv_classify_probe "$outcome" "$tier" )"; rc=$?
    case "$label" in
        OK)            say_ok   "$msg" ;;
        WARN)          say_warn "$msg"; [ -n "$fix" ] && remedy "$fix" ;;
        FAIL)          say_fail "$msg"; [ -n "$fix" ] && remedy "$fix" ;;
        UNKNOWN-WARN)  say_unk  "$msg (could not determine)"; warned=$(( warned + 1 ));
                       [ -n "$fix" ] && remedy "$fix" ;;
        UNKNOWN-BLOCK) say_unk  "$msg (could not determine — treated as blocking)"
                       blocking=$(( blocking + 1 )); [ -n "$fix" ] && remedy "$fix" ;;
    esac
    return $rc
}

layer_runs() { pfv_phase_includes "$PHASE" "$1"; }
note_skip()  { skipped=$(( skipped + 1 )); [ "$VERBOSE" = true ] && printf "        (layer %s skipped in phase %s)\n" "$1" "$PHASE"; return 0; }

printf "${BOLD}Lupin VM preflight${NC} — phase=%s container=%s\n" "$PHASE" "$CONTAINER"
printf "repo=%s\n" "$REPO_ROOT"

# ══════════════════════════════════════════════════════════════════════════
# LAYER A — host / OS
# ══════════════════════════════════════════════════════════════════════════
if layer_runs A; then
say_head "A. Host / OS"

# A0 — the instrument must not lie about the environment.
#      `gcloud ssh --command` opens a NON-LOGIN shell that does not source ~/.bashrc,
#      so a naive `env` check reports MISSING on a perfectly-configured VM. Read the
#      env the way a login shell would, and SAY which surface was read.
#      MEASURED 2026-07-26, first live run: SOURCING IS NOT ENOUGH. Debian's stock
#      ~/.bashrc opens with `case $- in *i*) ;; *) return;; esac` — a non-interactive
#      guard that returns before any export. So `source ~/.bashrc` from this script is
#      a NO-OP, and every var read as UNSET on a correctly-configured VM. The first
#      run of this preflight reported 12 false UNSETs for exactly that reason.
#      Fix: source it, then for anything still unset, eval the `export NAME=` lines
#      out of the file directly — and SAY which surface supplied the value.
ENV_SURFACE="current shell"
if [ -r "$HOME/.bashrc" ] && [ -z "${LUPIN_ROOT:-}" ]; then
    dbg "sourcing ~/.bashrc (non-login shell detected: LUPIN_ROOT unset)"
    # shellcheck disable=SC1090
    source "$HOME/.bashrc" >/dev/null 2>&1 || true
    ENV_SURFACE="~/.bashrc sourced"
fi

# pfv_hydrate_from_bashrc <VARNAME> — last-resort read for a var the non-interactive
# guard hid. Only ever SETS a var that is currently empty; never overrides a live value.
pfv_hydrate_from_bashrc() {
    local name="$1" line
    [ -z "$( eval "printf '%s' \"\${$name:-}\"" )" ] || return 0
    [ -r "$HOME/.bashrc" ] || return 1
    line="$( grep -E "^[[:space:]]*export[[:space:]]+$name=" "$HOME/.bashrc" 2>/dev/null | tail -1 )"
    [ -n "$line" ] || return 1
    eval "$line" >/dev/null 2>&1 || return 1
    return 0
}

# A1 — every REQUIRED var in the contract, validated against its declared shape.
if [ -r "$CONTRACT" ]; then
    while IFS= read -r row; do
        [ -n "$row" ] || continue
        name="$(  pfv_contract_field "$row" 1 )" || { say_fail "malformed env-contract row: $row"; continue; }
        surface="$( pfv_contract_field "$row" 2 )"
        shape="$( pfv_contract_field "$row" 4 )"
        req="$(   pfv_contract_field "$row" 5 )"
        # CONTAINER-surface vars are asserted in layer C, not here.
        [ "$surface" = "CONTAINER" ] && continue
        tier="BLOCK"; [ "$req" = "OPTIONAL" ] && tier="WARN"
        src="$ENV_SURFACE"
        if pfv_hydrate_from_bashrc "$name"; then
            [ "$src" = "$ENV_SURFACE" ] && src="~/.bashrc export line (the non-interactive guard hid it)"
        fi
        value="$( eval "printf '%s' \"\${$name:-}\"" )"
        pfv_shape_matches "$value" "$shape" "$VM_PREFIX"; rc=$?
        case $rc in
            0) report pass    "$tier" "$name set and matches $shape   [from: $src]" ;;
            1) report fail    "$tier" "$name = '$value' does NOT match shape $shape" \
                              "fix the value in ~/.bashrc, or re-run: lupin-vm.sh push-env" ;;
            2) report unknown "$tier" "$name is UNSET (surface: $surface)" \
                              "lupin-vm.sh push-env   # writes it to the VM ~/.bashrc" ;;
        esac
    done < <( pfv_parse_manifest "$CONTRACT" )
else
    report unknown BLOCK "env contract unreadable at $CONTRACT" "deploy the repo to the VM"
fi

# A2/A3 — the CC venv trap: $LUPIN_ROOT/.venv is a SYMLINK to the arbiter's venv.
CC_VENV="${LUPIN_CC_VENV:-${LUPIN_ROOT:-$REPO_ROOT}/.venv}"
if [ -e "$CC_VENV" ]; then
    is_link=false; [ -L "$CC_VENV" ] && is_link=true
    venv_uid="$( stat -c '%u' "$CC_VENV" 2>/dev/null || printf '' )"
    my_uid="$( id -u )"
    pfv_venv_is_foreign "$CC_VENV" "$is_link" "$venv_uid" "$my_uid"; rc=$?
    case $rc in
        0) report pass BLOCK "CC venv $CC_VENV is not a foreign symlink" ;;
        1) report fail BLOCK "CC venv $CC_VENV is a SYMLINK owned by uid $venv_uid (not $my_uid) — this is the arbiter's venv" \
                        "export LUPIN_CC_VENV=\$HOME/.venv-lupin-mcp && LUPIN_CC_VENV=\$HOME/.venv-lupin-mcp bash $REPO_ROOT/src/scripts/install-cosa-voice.sh" ;;
        2) report fail WARN "CC venv $CC_VENV is a symlink (owned by you) — verify it points where you think" \
                        "readlink -f $CC_VENV" ;;
    esac
    py="$CC_VENV/bin/python"
    if [ -x "$py" ]; then
        pyver="$( "$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null )"
        [ "$pyver" = "3.13" ] \
            && report pass BLOCK "CC venv python is $pyver" \
            || report fail BLOCK "CC venv python is '$pyver', expected 3.13" \
                          "uv venv --python 3.13 --clear $CC_VENV"
        missing=""
        for mod in fastmcp requests pydantic regex pytz; do
            "$py" -c "import $mod" >/dev/null 2>&1 || missing="$missing $mod"
        done
        [ -z "$missing" ] \
            && report pass BLOCK "CC venv host closure importable (fastmcp requests pydantic regex pytz)" \
            || report fail BLOCK "CC venv missing:$missing" \
                          "$py -m pip install fastmcp==2.14.2 requests pydantic regex pytz"
    else
        report unknown BLOCK "no python at $py" "provision it: uv venv --python 3.13 $CC_VENV"
    fi
else
    report unknown BLOCK "CC venv $CC_VENV does not exist" "lupin-vm.sh push-env, then install-cosa-voice.sh on the VM"
fi

# A4/A5 — the CC session-bridge surface (persona-404's two halves).
SESSIONS_DIR="${LUPIN_HOST_SESSIONS_DIR:-$HOME/.claude/sessions}"
if [ -d "$SESSIONS_DIR" ]; then
    dmode="$( stat -c '%a' "$SESSIONS_DIR" 2>/dev/null || printf '' )"
    pfv_mode_matches "$dmode" "2770"; rc=$?
    case $rc in
        0) report pass BLOCK "sessions dir is 2770 (setgid)" ;;
        1) report fail BLOCK "sessions dir mode is $dmode, expected 2770 (setgid)" \
                        "chmod 2770 $SESSIONS_DIR" ;;
        2) report unknown BLOCK "could not stat $SESSIONS_DIR" "ls -ld $SESSIONS_DIR" ;;
    esac
    bad_bridges=""
    for f in "$SESSIONS_DIR"/cc-*.json; do
        [ -e "$f" ] || continue
        m="$( stat -c '%a' "$f" 2>/dev/null )"
        case "$m" in 660|664|0660|0664) ;; *) bad_bridges="$bad_bridges $(basename "$f"):$m" ;; esac
    done
    [ -z "$bad_bridges" ] \
        && report pass BLOCK "all cc-*.json bridges are group-writable" \
        || report fail BLOCK "bridges not group-writable:$bad_bridges" \
                      "chmod 660 $SESSIONS_DIR/cc-*.json"
else
    report unknown BLOCK "sessions dir $SESSIONS_DIR missing" "mkdir -p $SESSIONS_DIR && chmod 2770 $SESSIONS_DIR"
fi

# A6 — git ignores a MISSING excludesfile with NO warning, so the patterns
#      silently stop applying (including **/.claude/settings.local.json).
exc="$( git config --global core.excludesfile 2>/dev/null || printf '' )"
if [ -z "$exc" ]; then
    report fail WARN "git core.excludesfile is not set" "git config --global core.excludesfile '~/.gitignore_global'"
else
    exc_resolved="${exc/#\~/$HOME}"
    [ -r "$exc_resolved" ] \
        && report pass WARN "core.excludesfile resolves to a readable file" \
        || report fail WARN "core.excludesfile='$exc' does not resolve to a readable file (git ignores this SILENTLY)" \
                      "ship the file, or: git config --global core.excludesfile '~/.gitignore_global'"
fi

# A7 — git on this VM runs as ROOT via sudo (the repo dirs are uid 1001 and the
#      SSH user cannot write them), so the safe.directory exception must exist for
#      the identity git ACTUALLY RUNS AS, not for the login user.
for d in "$REPO_ROOT" "${PLANNING_IS_PROMPTING_ROOT:-}"; do
    [ -n "$d" ] && [ -d "$d" ] || continue
    # NB tier=WARN, deliberately. The sanctioned tooling (lupin-vm.sh push-bundle)
    # passes `-c safe.directory=` INLINE on every call, so a missing root-side entry
    # does NOT break the supported path — it only bites a bare `sudo git` typed by
    # hand. Reporting it as BLOCK was this check's first-run defect: it failed a VM
    # whose supported workflow was entirely healthy.
    if sudo -n git config --global --get-all safe.directory 2>/dev/null | grep -qxF "$d"; then
        report pass WARN "safe.directory registered for $d in root's gitconfig"
    else
        report fail WARN "no root-side safe.directory for $d — a bare 'sudo git -C $d' will refuse (the tooling passes it inline, so this is not blocking)" \
                      "sudo git config --global --add safe.directory $d"
    fi
done
else note_skip A; fi

# ══════════════════════════════════════════════════════════════════════════
# LAYER B — repo parity + the payloads git cannot deliver
# ══════════════════════════════════════════════════════════════════════════
say_head "B. Repo parity + unversioned payloads"

# B3 runs in EVERY phase — a missing payload is exactly what you want to know
# BEFORE deploying, and layer B's phase gate covers only the parity checks.
if [ -r "$MANIFEST" ]; then
    while IFS= read -r row; do
        [ -n "$row" ] || continue
        remote="$( pfv_manifest_field "$row" 2 )" || { say_fail "malformed manifest row: $row"; continue; }
        owner="$(  pfv_manifest_field "$row" 3 )"
        mode="$(   pfv_manifest_field "$row" 4 )"
        req="$(    pfv_manifest_field "$row" 5 )"
        tier="BLOCK"; [ "$req" = "OPTIONAL" ] && tier="WARN"
        case "$remote" in
            */) if [ -d "${remote%/}" ]; then
                    report pass "$tier" "payload dir present: $remote"
                else
                    report fail "$tier" "payload dir MISSING: $remote" \
                                "lupin-vm.sh push-unversioned   # see src/conf/vm-unversioned-manifest.tsv"
                fi ;;
            *)  if [ -e "$remote" ]; then
                    o="$( stat -c '%u:%g' "$remote" 2>/dev/null || printf '' )"
                    m="$( stat -c '%a'    "$remote" 2>/dev/null || printf '' )"
                    pfv_owner_matches "$o" "$owner"; orc=$?
                    pfv_mode_matches  "$m" "$mode";  mrc=$?
                    if [ $orc -eq 0 ] && [ $mrc -eq 0 ]; then
                        report pass "$tier" "payload present with expected owner/mode: $remote"
                    else
                        report fail "$tier" "payload $remote has owner=$o mode=$m (expected $owner / $mode)" \
                                    "sudo chown ${owner/:/:} $remote && sudo chmod $mode $remote"
                    fi
                else
                    report fail "$tier" "payload MISSING: $remote" \
                                "lupin-vm.sh push-unversioned   # see src/conf/vm-unversioned-manifest.tsv"
                fi ;;
        esac
    done < <( pfv_parse_manifest "$MANIFEST" )
else
    report unknown BLOCK "unversioned manifest unreadable at $MANIFEST" "deploy the repo to the VM"
fi

if layer_runs B; then
# B1/B2 — parity. POST-phase only: PRE runs before HEAD changes, so asserting the
# old ref would be meaningless — and a meaningless assertion that passes is worse
# than no assertion, because it reads as coverage.
for pair in "$REPO_ROOT" "${PLANNING_IS_PROMPTING_ROOT:-}"; do
    [ -n "$pair" ] && [ -d "$pair/.git" ] || continue
    # -c safe.directory inline: root's gitconfig lacks the 1001-owned-repo exception,
    # exactly as lupin-vm.sh does it. Without this the read returns nothing and the
    # check reports a FALSE "cannot read HEAD" on a perfectly clean repo.
    head_sha="$( sudo -n git -c "safe.directory=$pair" -C "$pair" rev-parse --short HEAD 2>/dev/null || printf '' )"
    dirty="$(   sudo -n git -c "safe.directory=$pair" -C "$pair" status --porcelain 2>/dev/null | grep -v '^??' | head -5 )"
    if [ -z "$head_sha" ]; then
        report unknown BLOCK "cannot read HEAD of $pair" "sudo git -C $pair rev-parse HEAD"
    elif [ -n "$dirty" ]; then
        report fail BLOCK "$pair has TRACKED drift at $head_sha: $( printf '%s' "$dirty" | tr '\n' ' ' )" \
                      "lupin-vm.sh deploy   # reset --hard to the branch (untracked payloads survive)"
    else
        report pass BLOCK "$pair clean at $head_sha"
    fi
done

# B4 — a committed .mcp.json with absolute dev paths pollutes every checkout.
if sudo -n git -c "safe.directory=$REPO_ROOT" -C "$REPO_ROOT" ls-files --error-unmatch .mcp.json >/dev/null 2>&1; then
    report fail WARN ".mcp.json is TRACKED — it must not be (cosa-voice is a per-machine USER-scope MCP)" \
                  "git rm --cached .mcp.json && echo .mcp.json >> .gitignore"
else
    report pass WARN ".mcp.json is not tracked"
fi
else note_skip B; fi

# ══════════════════════════════════════════════════════════════════════════
# LAYER C — compose / container
# ══════════════════════════════════════════════════════════════════════════
if layer_runs C; then
say_head "C. Compose / container"

if ! command -v docker >/dev/null 2>&1; then
    report unknown BLOCK "docker not reachable" "check the docker daemon"
elif ! docker ps --filter "name=^${CONTAINER}$" --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER"; then
    report fail BLOCK "container '$CONTAINER' is not running" \
                  "sudo docker compose -f $COMPOSE_FILE --env-file $REPO_ROOT/cloud-gpu.env up -d --no-deps $CONTAINER"
else
    report pass BLOCK "container '$CONTAINER' is running"

    running_mounts="$( docker inspect "$CONTAINER" --format '{{range .Mounts}}{{.Destination}}{{"\n"}}{{end}}' 2>/dev/null )"

    # C1 — a container's MOUNT TABLE is fixed at CREATION. `docker restart` reuses it,
    #      so a compose edit is invisible to a restarted container. Only a recreate reads
    #      the new file. This has bitten twice on this VM (07-24 sessions bind, 07-25 doc viewer).
    if [ -r "$COMPOSE_FILE" ] && command -v python3 >/dev/null 2>&1; then
        declared="$( python3 - "$COMPOSE_FILE" <<'PY' 2>/dev/null
import sys, yaml
d = yaml.safe_load( open( sys.argv[1] ) )
svc = d["services"].get("lupin-rest") or {}
for v in svc.get("volumes") or []:
    if isinstance(v, dict):
        t = v.get("target")
    else:
        p = str(v).split(":")
        t = p[1] if len(p) >= 2 else None
    if t: print(t)
PY
)"
        missing="$( pfv_diff_mount_sets "$declared" "$running_mounts" )"; rc=$?
        [ $rc -eq 0 ] \
            && report pass BLOCK "running mount set covers every compose-declared mount" \
            || report fail BLOCK "compose declares mounts the RUNNING container lacks: $( printf '%s' "$missing" | tr '\n' ' ' )" \
                          "sudo docker compose -f $COMPOSE_FILE --env-file $REPO_ROOT/cloud-gpu.env up -d --no-deps --force-recreate $CONTAINER   # a RESTART will NOT do it"
    else
        report unknown WARN "cannot parse $COMPOSE_FILE (need python3 + pyyaml)" "pip install pyyaml"
    fi

    # C2 — an absence means TWO things and only one of them is loud.
    #      path absent  => the registry WARNs and skips.                        LOUD
    #      path present but EMPTY => it registers the scope and 404s everything. SILENT.
    #      An auto-created empty dir converts the first into the second, which is
    #      the entire reason `create_host_path: false` is in the compose file.
    empty_mounts=""
    while IFS= read -r m; do
        [ -n "$m" ] || continue
        case "$m" in /var/external-projects/*) ;; *) continue ;; esac
        if [ -z "$( docker exec "$CONTAINER" sh -c "ls -A '$m' 2>/dev/null | head -1" 2>/dev/null )" ]; then
            empty_mounts="$empty_mounts $m"
        fi
    done <<< "$running_mounts"
    [ -z "$empty_mounts" ] \
        && report pass BLOCK "every external-scope mount is present AND non-empty" \
        || report fail BLOCK "mounted but EMPTY (registers the scope, then 404s every file — silent):$empty_mounts" \
                      "verify the host path exists and is non-empty, then recreate the container"

    # C3 — the claude-creds VOLUME mounts over the whole .claude dir and SHADOWS the
    #      host's sessions bind unless both are present. That shadowing was persona-404.
    has_creds=false; has_sessions=false
    printf '%s\n' "$running_mounts" | grep -qx "/home/rruiz/.claude"          && has_creds=true
    printf '%s\n' "$running_mounts" | grep -qx "/home/rruiz/.claude/sessions" && has_sessions=true
    if [ "$has_creds" = true ] && [ "$has_sessions" = true ]; then
        report pass BLOCK "both CC mounts present (creds volume + sessions bind)"
    else
        report fail BLOCK "CC mounts incomplete (creds=$has_creds sessions=$has_sessions) — the volume SHADOWS the bind" \
                      "add the long-form sessions bind with create_host_path:false, then --force-recreate"
    fi

    # C4 — container uid + the bridge gid it must join.
    cuid="$( docker exec "$CONTAINER" id -u 2>/dev/null || printf '' )"
    [ "$cuid" = "1001" ] \
        && report pass BLOCK "container runs as uid 1001" \
        || report unknown BLOCK "container uid is '$cuid', expected 1001" "check the image's USER directive"
    if [ -n "${LUPIN_BRIDGE_GID:-}" ]; then
        docker exec "$CONTAINER" id -G 2>/dev/null | tr ' ' '\n' | grep -qx "$LUPIN_BRIDGE_GID" \
            && report pass BLOCK "container joined bridge gid $LUPIN_BRIDGE_GID" \
            || report fail BLOCK "container is NOT in bridge gid $LUPIN_BRIDGE_GID — it cannot read host-written bridges" \
                          "add group_add: [\"\${LUPIN_BRIDGE_GID}\"] to the compose service, then --force-recreate"
    fi

    # C5 — THE ALARM MUST NOT BE GATED ON THE HEALTHY VALUE.
    #      The Cloud SQL proxy healthcheck probes :9090 and never touches the socket
    #      it exists to publish. On 2026-07-26 it reported "Up 35 hours (healthy)" for
    #      the entire outage, while socket-init had DELETED the socket out from under it.
    #      So: probe the ARTIFACT, not the provider's self-report.
    conn="${CLOUD_SQL_CONNECTION_NAME:-}"
    if [ -z "$conn" ] && [ -e "$REPO_ROOT/cloud-gpu.env" ]; then
        # sudo: cloud-gpu.env is mode 600 / uid 1001, so a plain grep by the SSH user
        # reads NOTHING and the socket check reports a false UNKNOWN — measured on the
        # first live run. `sudo docker compose` reads it the same way for the same reason.
        conn="$( sudo -n grep -E '^CLOUD_SQL_CONNECTION_NAME=' "$REPO_ROOT/cloud-gpu.env" 2>/dev/null | head -1 | cut -d= -f2- )"
    fi
    if [ -z "$conn" ]; then
        report unknown BLOCK "CLOUD_SQL_CONNECTION_NAME unknown — cannot locate the socket" \
                      "set it in cloud-gpu.env"
    elif docker exec "$CONTAINER" sh -c "test -S '/cloudsql/$conn/.s.PGSQL.5432'" 2>/dev/null; then
        report pass BLOCK "Cloud SQL socket exists and IS a socket"
    else
        report fail BLOCK "Cloud SQL socket /cloudsql/$conn/.s.PGSQL.5432 is absent or not a socket (the proxy may still report 'healthy' — bug 70794d58)" \
                      "sudo docker compose -f $COMPOSE_FILE --env-file $REPO_ROOT/cloud-gpu.env restart cloud-sql-proxy && ... up -d --no-deps --force-recreate $CONTAINER"
    fi
fi
else note_skip C; fi

# ══════════════════════════════════════════════════════════════════════════
# LAYER D — application / auth  (only ACCEPTANCE can answer these)
# ══════════════════════════════════════════════════════════════════════════
if layer_runs D; then
say_head "D. Application / auth"

http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time "${2:-20}" "$1" 2>/dev/null; }

c="$( http_code "$APP_URL/health" 30 )"
[ "$c" = "200" ] && report pass BLOCK "app /health 200" \
                 || report fail BLOCK "app /health returned '$c'" "docker logs --tail 60 $CONTAINER"

c="$( http_code "$ARBITER_URL/health" 10 )"
[ "$c" = "200" ] && report pass WARN "arbiter /health 200" \
                 || report fail WARN "arbiter /health returned '$c'" "systemctl --user restart lupin-arbiter-app.service"

# D4 — ASSERT ACCEPTANCE, NOT PRESENCE, and prove the check can fail.
#      os.path.exists() passes on the exact shape that broke (a mode-600 key), and a
#      readable key from ANOTHER deployment sails through a readability check too —
#      it was the dev box's key, unregistered in this server's DB. So: probe the
#      endpoint the caller depends on, WITH a wrong-key control. A 200 alone does not
#      prove the key was checked; only a 401 on a bad key proves that.
KEYFILE="$REPO_ROOT/src/conf/keys/notification-api-claude-code-dev"
if [ -r "$KEYFILE" ]; then
    K="$( cat "$KEYFILE" 2>/dev/null )"
    good="$( curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H "X-API-Key: $K" "$APP_URL/api/dm/list" 2>/dev/null )"
    bad="$(  curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H "X-API-Key: pfv-deliberately-invalid" "$APP_URL/api/dm/list" 2>/dev/null )"
    if [ "$good" = "200" ] && [ "$bad" = "401" ]; then
        report pass BLOCK "outbound API key ACCEPTED (200) and the wrong-key control was REJECTED (401)"
    elif [ "$good" = "200" ] && [ "$bad" = "200" ]; then
        report fail BLOCK "key probe is VACUOUS — a deliberately-invalid key also returned 200, so this endpoint is not checking the key" \
                      "the probe proves nothing here; pick an endpoint that enforces X-API-Key"
    elif [ "$good" = "401" ]; then
        report fail BLOCK "outbound API key REJECTED (401) — readable, but not registered in THIS server's database" \
                      "mint one against this deployment: docker exec -w /var/lupin $CONTAINER python src/scripts/create_service_account_postgres.py --email=claude.code@lupin.deepily.ai"
    else
        report unknown BLOCK "key probe inconclusive (good=$good bad=$bad)" "curl -v -H 'X-API-Key: ...' $APP_URL/api/dm/list"
    fi
else
    report fail BLOCK "outbound key file unreadable: $KEYFILE" \
                  "ls -l $KEYFILE ; sudo chmod 644 $KEYFILE   # mode 600 + uid 1001 was the 07-25 defect"
fi

# D8 — the installer once COUNTED the hooks and never wrote them (0/8 installed).
SETTINGS="$HOME/.claude/settings.json"
if [ -r "$SETTINGS" ] && command -v python3 >/dev/null 2>&1; then
    got="$( python3 - "$SETTINGS" <<'PY' 2>/dev/null
import sys, json
want = {"SessionStart","SessionEnd","UserPromptSubmit","PreToolUse","PostToolUse","Stop","Notification","PermissionRequest"}
try:
    hooks = json.load( open( sys.argv[1] ) ).get( "hooks", {} ) or {}
except Exception:
    print( "ERR" ); raise SystemExit
print( ",".join( sorted( want - set( hooks ) ) ) or "OK" )
PY
)"
    case "$got" in
        OK)  report pass BLOCK "all 8 CC hook event-types present in settings.json" ;;
        ERR) report unknown BLOCK "settings.json unparseable" "python3 -m json.tool $SETTINGS" ;;
        *)   report fail BLOCK "CC hooks MISSING: $got" \
                       "bash $REPO_ROOT/src/scripts/install-cosa-voice.sh   # merges src/conf/claude-code-hooks.json" ;;
    esac
else
    report unknown BLOCK "cannot read $SETTINGS" "run install-cosa-voice.sh on this VM"
fi
else note_skip D; fi

# ══════════════════════════════════════════════════════════════════════════
# LAYER E — cloud / IAM (read-only)
# ══════════════════════════════════════════════════════════════════════════
if layer_runs E; then
say_head "E. Cloud / IAM"

if [ "${CLAUDE_CODE_USE_VERTEX:-}" = "1" ]; then
    # Opus 4.8 on Vertex is GLOBAL-only. A regional value yields model-not-found,
    # which the Claude Code wizard mis-reports as "permission denied".
    [ "${CLOUD_ML_REGION:-}" = "global" ] \
        && report pass WARN "CLOUD_ML_REGION=global (Opus 4.8 is global-only)" \
        || report fail WARN "CLOUD_ML_REGION='${CLOUD_ML_REGION:-}' — Opus 4.8 on Vertex is GLOBAL-only" \
                      "export CLOUD_ML_REGION=global in ~/.bashrc"
    [ -n "${ANTHROPIC_VERTEX_PROJECT_ID:-}" ] \
        && report pass WARN "ANTHROPIC_VERTEX_PROJECT_ID set" \
        || report fail WARN "ANTHROPIC_VERTEX_PROJECT_ID unset" "export it in ~/.bashrc"
else
    report pass WARN "Vertex not enabled here (CLAUDE_CODE_USE_VERTEX != 1) — skipping region checks"
fi

# CC 2.1.220 added VERTEX_REGION_CLAUDE_5_OPUS. An unguarded per-model override
# silently routes a SINGLE model to another region, where it runs, bills, and logs
# nothing. Opus is the expensive one.
if env | grep -q '^VERTEX_REGION_CLAUDE_5_OPUS='; then
    report fail WARN "VERTEX_REGION_CLAUDE_5_OPUS is set — a per-model override routes ONE model elsewhere, silently" \
                  "unset VERTEX_REGION_CLAUDE_5_OPUS   # unless this is deliberate"
else
    report pass WARN "no per-model Vertex region override set"
fi
else note_skip E; fi

# ══════════════════════════════════════════════════════════════════════════
say_head "Summary"
printf "phase=%s   passed=%d   warnings=%d   blocking=%d   layers-skipped=%d\n" \
       "$PHASE" "$passed" "$warned" "$blocking" "$skipped"
printf "\n%s\n" "A green preflight means THESE assertions hold — never that the VM is fine."
if [ "$blocking" -eq 0 ]; then
    printf "${GREEN}${BOLD}PREFLIGHT PASSED${NC} (%d warning(s), non-blocking)\n" "$warned"
    exit 0
fi
printf "${RED}${BOLD}PREFLIGHT FAILED${NC} — %d blocking\n" "$blocking"
exit 1
