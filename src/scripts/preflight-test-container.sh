#!/bin/bash
#
# preflight-test-container.sh — Verify lupin-rest-test deployment state before
# TFE/BFE Resume or live E2E runs.
#
# Catches the class of failures where docker-compose.yml changes (new bind
# mounts) have not been applied to the running container because a `docker
# restart` preserves the prior mount set. The fix is always a recreate:
#
#     docker rm -f lupin-rest-test && docker compose up -d lupin-rest-test
#
# Exit codes:
#   0 — all blocking probes green (WARNings are non-blocking)
#   1 — one or more blocking probes failed
#   2 — preflight itself could not run (docker unreachable, etc.)
#
# Usage:
#   src/scripts/preflight-test-container.sh         # run all probes
#   src/scripts/preflight-test-container.sh -v      # verbose (echo commands)
#

set -u

CONTAINER="${PREFLIGHT_CONTAINER:-lupin-rest-test}"
VERBOSE=false
for arg in "$@"; do
    case "$arg" in
        -v|--verbose) VERBOSE=true ;;
        -h|--help)
            sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
    esac
done

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

failures=0
warnings=0

say_ok()    { printf "${GREEN}[OK]${NC}   %s\n" "$1"; }
say_fail()  { printf "${RED}[FAIL]${NC} %s\n" "$1"; failures=$(( failures + 1 )); }
say_warn()  { printf "${YELLOW}[WARN]${NC} %s\n" "$1"; warnings=$(( warnings + 1 )); }
say_info()  { printf "${BOLD}==>${NC} %s\n" "$1"; }
remedy()    { printf "       ${BOLD}remedy:${NC} %s\n" "$1"; }

run_cmd() {
    if [ "$VERBOSE" = true ]; then
        printf "       $ %s\n" "$*" >&2
    fi
    "$@"
}

# ── 0. Docker reachable? ─────────────────────────────────────────────────
if ! docker info >/dev/null 2>&1; then
    printf "${RED}[ABORT]${NC} docker daemon not reachable\n"
    exit 2
fi

say_info "Preflight: ${CONTAINER}"

# ── 1. Container running ─────────────────────────────────────────────────
if run_cmd docker ps --filter "name=^${CONTAINER}$" --format "{{.Names}}" | grep -q "^${CONTAINER}$"; then
    say_ok "container '${CONTAINER}' is running"
else
    say_fail "container '${CONTAINER}' is not running"
    remedy "docker compose up -d ${CONTAINER}"
    exit 1
fi

# ── 2. .git mount present in inspect output ──────────────────────────────
mounts="$(run_cmd docker inspect "${CONTAINER}" --format '{{range .Mounts}}{{.Source}}→{{.Destination}}{{"\n"}}{{end}}' 2>/dev/null)"
if printf "%s\n" "$mounts" | grep -q "/\.git→/var/lupin/\.git"; then
    say_ok ".git bind-mount is applied (docker inspect)"
else
    say_fail ".git bind-mount is NOT in the running container's mount set"
    remedy "docker rm -f ${CONTAINER} && docker compose up -d ${CONTAINER}"
fi

# ── 3. git rev-parse --is-inside-work-tree ───────────────────────────────
if run_cmd docker exec "${CONTAINER}" sh -c 'cd /var/lupin && git rev-parse --is-inside-work-tree 2>/dev/null' | grep -q "true"; then
    say_ok "git sees /var/lupin as a work tree"
else
    say_fail "git does NOT see /var/lupin as a work tree"
    remedy "docker rm -f ${CONTAINER} && docker compose up -d ${CONTAINER}"
fi

# ── 4. git worktree add/remove smoke ─────────────────────────────────────
smoke_path="/tmp/preflight-smoke-$$"
wt_add_out="$(run_cmd docker exec "${CONTAINER}" sh -c "cd /var/lupin && git worktree add ${smoke_path} HEAD 2>&1" 2>&1 || true)"
if echo "$wt_add_out" | grep -qE "(Preparing worktree|HEAD is now at)"; then
    # cleanup (best-effort)
    # NB: `remove --force` already deletes the smoke worktree's admin entry — do
    # NOT add `git worktree prune` here. An in-container prune wipes the ENTIRE
    # host .git/worktrees registry (bug 47ac0e50: ./.git is mounted but
    # lupin-worktrees/ is not, so every host lane's gitdir reads as missing).
    run_cmd docker exec "${CONTAINER}" sh -c "cd /var/lupin && git worktree remove --force ${smoke_path} >/dev/null 2>&1" || true
    say_ok "git worktree add/remove works inside container"
else
    say_fail "git worktree add failed inside container"
    remedy "check docker-compose.yml has - ./.git:/var/lupin/.git, then recreate container"
    if [ "$VERBOSE" = true ]; then
        printf "       last output: %s\n" "$wt_add_out"
    fi
fi

# ── 5. Claude Agent SDK credentials mount ────────────────────────────────
if run_cmd docker exec "${CONTAINER}" sh -c 'test -f /home/rruiz/.claude/.credentials.json' 2>/dev/null; then
    say_ok "claude-agent-sdk credentials mount present"
else
    say_fail "claude-agent-sdk credentials mount is missing"
    remedy "docker rm -f ${CONTAINER} && docker compose up -d ${CONTAINER}"
fi

# ── 5b. Worktree bind-mount end-to-end (container ↔ host visibility) ─────
# Creates a real git worktree inside the container at the bind-mount path,
# then confirms the host sees it too. Catches the class of regression where
# `./.claude/worktrees:/var/lupin/.claude/worktrees` is silently unmounted
# or the host side is missing permissions. Tears down on success or failure.
SMOKE_WT="worktree-preflight-smoke-$$"
HOST_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOST_WT="$HOST_ROOT/.claude/worktrees/$SMOKE_WT"
CONTAINER_WT="/var/lupin/.claude/worktrees/$SMOKE_WT"

if run_cmd docker exec "${CONTAINER}" sh -c "cd /var/lupin && git worktree add ${CONTAINER_WT} HEAD >/dev/null 2>&1"; then
    if [ -d "$HOST_WT" ]; then
        say_ok "worktree bind-mount: container writes visible on host"
    else
        say_fail "worktree created in container but NOT visible on host at ${HOST_WT}"
        remedy "verify docker-compose.yml has '- ./.claude/worktrees:/var/lupin/.claude/worktrees' on both services"
    fi
    # Teardown regardless of outcome. `remove --force` cleans the smoke worktree's
    # admin entry — do NOT add `git worktree prune` (bug 47ac0e50: an in-container
    # prune wipes the entire host .git/worktrees registry).
    run_cmd docker exec "${CONTAINER}" sh -c "cd /var/lupin && git worktree remove --force ${CONTAINER_WT} >/dev/null 2>&1" || true
else
    say_fail "worktree bind-mount: could not create smoke worktree inside container"
    remedy "check ${CONTAINER_WT} is writable inside container (bind-mount permissions)"
fi

# ── 6. gh auth status (WARN-only — Phase 5 future-proof) ─────────────────
gh_out="$(run_cmd docker exec "${CONTAINER}" sh -c 'gh auth status 2>&1' 2>&1 || true)"
if echo "$gh_out" | grep -qE "Logged in|Active account: true"; then
    say_ok "gh CLI has valid GitHub auth"
else
    say_warn "gh CLI has no valid GitHub auth in container"
    remedy "when Phase 5 needs it: mount ~/.config/gh into the compose services"
fi

# ── Summary ──────────────────────────────────────────────────────────────
echo
if [ "$failures" -eq 0 ]; then
    if [ "$warnings" -eq 0 ]; then
        say_info "preflight PASSED (all probes green)"
    else
        say_info "preflight PASSED with ${warnings} warning(s) — non-blocking"
    fi
    exit 0
else
    say_info "preflight FAILED (${failures} blocking, ${warnings} warning)"
    exit 1
fi
