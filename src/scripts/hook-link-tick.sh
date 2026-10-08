#!/usr/bin/env bash
#
# hook-link-tick.sh — a timed check that the two git hooks are still links to the scripts this repo ships.
#
# The commit gate and the push gate live in the hooks folder, which git does not carry. A script that
# rewrites that folder (a dangling link, a copy, a link to a file outside the checkout) switches a gate
# off for every seat, and git prints no error. The branch-lock guard reads the text of a Bash command,
# so it cannot see what a script does. This tick looks from outside the seat, every ten minutes.
#
# It SAYS NOTHING WHEN THE LINKS ARE RIGHT: zero bytes on stdout and stderr, exit 0. A finding is
# delivered as a notification to the global recipient and, when HOOK_LINK_DM names a persona, a direct
# message. A finding already delivered stays quiet until HOOK_LINK_RESEND_HOURS passes, unless the set
# changed. THE TICK NEVER REPAIRS A LINK: a detector that repaired would hide the writer and could
# overwrite a deliberate change. A person runs src/scripts/install-git-hooks.sh in the main checkout.
#
# What it looks at: the first entry of `git worktree list` (the main checkout, never $PWD, because cron
# has no working directory and every worktree shares the main folder's hooks), the folder git reads
# hooks from (core.hooksPath), and the states pfv_git_hook_status names for pre-commit and pre-push. A
# hooks path that is not the checkout's own folder is itself a finding. A reference-transaction hook that
# exists must be executable and carry its marker line; an absent one is not a finding, since this
# repo's installer does not make it.
#
# Exit codes, each a different fact:
#   0  clean, nothing printed
#   1  the check could not run (no git, no library, an unreadable hooks folder, no repository, a setting that is not a number)
#   2  findings, and every channel that was due arrived
#   3  findings, and at least one due channel failed (a channel that arrived is not sent again)
#   4  findings, every channel unchanged since its last delivery and inside the quiet window
#   5  findings, and delivery is switched off (HOOK_LINK_DELIVER=0): printed only, nothing sent
#
# Usage:  hook-link-tick.sh [--install | --uninstall | --status | --print-install]
# Environment (all optional):
#   HOOK_LINK_REPO          the checkout to look at (tests); setting it marks every message a drill
#   HOOK_LINK_DM            persona to direct-message
#   HOOK_LINK_API_BASE      default http://localhost:7999
#   HOOK_LINK_STATE         ledger path, default ~/.claude/hook-link-tick-state.json (a drill adds ".drill")
#   HOOK_LINK_RESEND_HOURS  quiet window, default 6
#   HOOK_LINK_DELIVER       0 prints the report, delivers nothing and exits 5
#   HOOK_LINK_PATH          replaces PATH outright (tests; cron's bare PATH is the default)
#   HOOK_LINK_SCHEDULE, HOOK_LINK_LOG, HOOK_LINK_CRONTAB_CMD   install settings
set -uo pipefail

# Cron's environment is bare. Nothing below relies on the profile.
export PATH="${HOOK_LINK_PATH:-/usr/local/bin:/usr/bin:/bin:${PATH:-}}"

SELF="$( readlink -f "${BASH_SOURCE[0]}" )"
HERE="$( dirname "$SELF" )"
SELF_ROOT="$( cd "$HERE/../.." && pwd )"

CRON_TAG="# hook-link-tick"
CRON_SCHEDULE="${HOOK_LINK_SCHEDULE:-2,12,22,32,42,52 * * * *}"
CRON_LOG="${HOOK_LINK_LOG:-$HOME/.lupin/logs/hook-link-tick.log}"
CRONTAB_CMD="${HOOK_LINK_CRONTAB_CMD:-crontab}"
REF_MARKER="branch-guard: reference-transaction hook"

# Git calls without the variables that would move the repository under us.
g() { env -u GIT_DIR -u GIT_COMMON_DIR -u GIT_WORK_TREE -u GIT_CEILING_DIRECTORIES git "$@"; }

cannot_look() {
    echo "HOOK-LINK TICK ERROR: the check could not run: $1" >&2
    exit 1
}

main_checkout() {
    local base="${HOOK_LINK_REPO:-$SELF_ROOT}"
    command -v git >/dev/null 2>&1 || cannot_look "git is not on PATH"
    g -C "$base" worktree list --porcelain 2>/dev/null | awk '/^worktree /{ print substr( $0, 10 ); exit }'
}

# ── crontab install / uninstall ─────────────────────────────────────────────
cron_line() {
    local main="$1" dm=""
    [ -n "${HOOK_LINK_DM:-}" ] && dm="HOOK_LINK_DM='${HOOK_LINK_DM}' "
    printf '%s %s%s >> %s 2>&1 %s\n' "$CRON_SCHEDULE" "$dm" "$main/src/scripts/hook-link-tick.sh" "$CRON_LOG" "$CRON_TAG"
}

main_for_install() {
    local main
    main="$( main_checkout )"
    [ -n "$main" ] || cannot_look "no repository found"
    [ -f "$main/src/scripts/hook-link-tick.sh" ] || { echo "INSTALL REFUSED: $main has no src/scripts/hook-link-tick.sh yet, so a cron line would name a script that is not there. Land the script first." >&2; exit 1; }
    printf '%s' "$main"
}

do_print_install() {
    local main; main="$( main_for_install )" || exit $?
    cat <<EOF
# Add the git hook link tick to your crontab (every ten minutes, at minute 2 of each ten):
( crontab -l 2>/dev/null; echo '$( cron_line "$main" )' ) | crontab -
# Remove it again:
$main/src/scripts/hook-link-tick.sh --uninstall
EOF
}

do_status() {
    if $CRONTAB_CMD -l 2>/dev/null | grep -Fq "$CRON_TAG"; then
        echo "INSTALLED:"; $CRONTAB_CMD -l 2>/dev/null | grep -F "$CRON_TAG"; return 0
    fi
    echo "NOT INSTALLED: run $HERE/hook-link-tick.sh --print-install"; return 1
}

do_install() {
    local main existing backup
    main="$( main_for_install )" || exit $?
    existing="$( $CRONTAB_CMD -l 2>/dev/null )"
    if printf '%s\n' "$existing" | grep -Fq "$CRON_TAG"; then
        echo "already installed, leaving the existing line exactly as it is:"; printf '%s\n' "$existing" | grep -F "$CRON_TAG"; return 0
    fi
    mkdir -p "$( dirname "$CRON_LOG" )" 2>/dev/null
    # Back up before any write: a crontab is one file with no history, and no backup means no write.
    backup="$HOME/.claude/crontab-backup-$( date +%Y%m%d-%H%M%S ).txt"
    mkdir -p "$( dirname "$backup" )" 2>/dev/null
    printf '%s\n' "$existing" > "$backup" || { echo "INSTALL ABORTED: could not write backup $backup" >&2; return 1; }
    { [ -n "$existing" ] && printf '%s\n' "$existing"; cron_line "$main"; } | $CRONTAB_CMD - \
        || { echo "INSTALL FAILED: crontab refused the write (backup at $backup)" >&2; return 1; }
    echo "installed (backup at $backup):"; cron_line "$main"
}

do_uninstall() {
    local existing backup
    existing="$( $CRONTAB_CMD -l 2>/dev/null )"
    if ! printf '%s\n' "$existing" | grep -Fq "$CRON_TAG"; then echo "not installed, nothing removed"; return 0; fi
    backup="$HOME/.claude/crontab-backup-$( date +%Y%m%d-%H%M%S ).txt"
    mkdir -p "$( dirname "$backup" )" 2>/dev/null
    printf '%s\n' "$existing" > "$backup" || { echo "UNINSTALL ABORTED: could not write backup $backup" >&2; return 1; }
    # Only a line carrying this tag is removed, so the other jobs are unmatchable rather than carefully avoided.
    printf '%s\n' "$existing" | grep -Fv "$CRON_TAG" | $CRONTAB_CMD - \
        || { echo "UNINSTALL FAILED: crontab refused the write (backup at $backup)" >&2; return 1; }
    echo "removed (backup at $backup)"
}

case "${1:-}" in
    --print-install ) do_print_install; exit $? ;;
    --install       ) do_install;       exit $? ;;
    --uninstall     ) do_uninstall;     exit $? ;;
    --status        ) do_status;        exit $? ;;
    ""              ) ;;
    *               ) echo "usage: hook-link-tick.sh [--print-install|--install|--uninstall|--status]" >&2; exit 64 ;;
esac

# ── the check ───────────────────────────────────────────────────────────────
LIB="$SELF_ROOT/src/scripts/lib/preflight-vm-lib.sh"
[ -r "$LIB" ] || cannot_look "the library $LIB is missing"
# shellcheck source=lib/preflight-vm-lib.sh
source "$LIB"
declare -F pfv_git_hook_status >/dev/null || cannot_look "the library has no pfv_git_hook_status"

MAIN="$( main_checkout )"
[ -n "$MAIN" ] && [ -d "$MAIN" ] || cannot_look "no repository found from ${HOOK_LINK_REPO:-$SELF_ROOT}"

hooks_path="$( g -C "$MAIN" rev-parse --git-path hooks 2>/dev/null )" || hooks_path=""
[ -n "$hooks_path" ] || cannot_look "git could not name the hooks folder of $MAIN"
case "$hooks_path" in /*) HOOKS_DIR="$hooks_path" ;; *) HOOKS_DIR="$MAIN/$hooks_path" ;; esac

common_dir="$( g -C "$MAIN" rev-parse --git-common-dir 2>/dev/null )" || common_dir=""
[ -n "$common_dir" ] || cannot_look "git could not name the common directory of $MAIN"
case "$common_dir" in /*) ;; *) common_dir="$MAIN/$common_dir" ;; esac
OWN_DIR="$common_dir/hooks"

if [ -e "$HOOKS_DIR" ]; then
    { [ -d "$HOOKS_DIR" ] && [ -r "$HOOKS_DIR" ] && [ -x "$HOOKS_DIR" ]; } || cannot_look "the hooks folder $HOOKS_DIR is not a readable directory"
fi

FINDINGS="$( mktemp )" || cannot_look "could not make a scratch file"
trap 'rm -f "$FINDINGS"' EXIT

if [ "$( readlink -f "$HOOKS_DIR" 2>/dev/null )" != "$( readlink -f "$OWN_DIR" 2>/dev/null )" ]; then
    printf 'core.hooksPath\tHOOKS_PATH_MOVED\t%s\t%s\n' "$HOOKS_DIR" "$OWN_DIR" >> "$FINDINGS"
fi

for row in "pre-commit:pre-commit-chain.sh" "pre-push:pre-push-chain.sh"; do
    hook="${row%%:*}"; script="${row##*:}"
    status="$( pfv_git_hook_status "$HOOKS_DIR" "$hook" "$MAIN/src/scripts/$script" "$MAIN" )"
    word="${status%%$'\t'*}"; lands=""
    case "$status" in *$'\t'*) lands="${status#*$'\t'}" ;; esac
    [ "$word" = "MATCH" ] || printf '%s\t%s\t%s\t%s\n' "$hook" "$word" "$HOOKS_DIR" "$lands" >> "$FINDINGS"
done

ref="$HOOKS_DIR/reference-transaction"
if [ -e "$ref" ] || [ -L "$ref" ]; then
    if   [ ! -e "$ref" ];                      then printf 'reference-transaction\tDANGLING\t%s\t%s\n' "$HOOKS_DIR" "$( readlink -m "$ref" )" >> "$FINDINGS"
    elif [ ! -x "$ref" ];                      then printf 'reference-transaction\tREF_NOT_EXECUTABLE\t%s\t\n' "$HOOKS_DIR" >> "$FINDINGS"
    elif ! grep -Fq "$REF_MARKER" "$ref" 2>/dev/null; then printf 'reference-transaction\tREF_NO_MARKER\t%s\t\n' "$HOOKS_DIR" >> "$FINDINGS"
    fi
fi

# Setting HOOK_LINK_REPO points the tick at a checkout that is not the real one, which is what a test does.
# That alone marks every message a drill, so a test fire cannot read like a real alarm (HOOK_LINK_DRILL=0 overrides).
if [ -n "${HOOK_LINK_REPO:-}" ] && [ "${HOOK_LINK_DRILL:-}" != "0" ]; then export HOOK_LINK_DRILL=1; fi

if [ -x "$SELF_ROOT/.venv/bin/python" ]; then PYTHON="$SELF_ROOT/.venv/bin/python"; else PYTHON="python3"; fi
LUPIN_ROOT="$SELF_ROOT" PYTHONPATH="$SELF_ROOT/src" "$PYTHON" -m cosa.utils.hook_link_tick "$FINDINGS"
exit $?
