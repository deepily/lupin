#!/bin/bash
#################################################################
# deploy-cloud-test-lib.sh
#
# Pure (VM-uncoupled) helper functions for deploy-cloud-test.sh.
# Extracted so the arg-parse / ref-resolve / axis-detect / stamp
# logic is unit-testable WITHOUT touching the GCP VM (task d8c699aa).
#
# Every function here is side-effect-light: it reads only the local
# git repo (cwd) + its arguments, and writes only stdout / globals.
# The VM-coupled orchestration (SCP, ssh, docker) stays in the
# parent script. Source this file; do not execute it.
#
# Design: src/rnd/2026.06.23-gcp-code-sync-to-runtime-design.md §4
#################################################################

# Dependency files whose change forces the AXIS-B (image rebuild) path.
# Overridable by callers/tests via DCTL_DEP_PATHS before sourcing.
if [ -z "${DCTL_DEP_PATHS:-}" ]; then
    DCTL_DEP_PATHS=( pyproject.toml uv.lock )
fi

# dctl_parse_args "$@"
#   Parse the deploy-cloud-test CLI. Sets globals:
#     REF (default HEAD), TAKE_DEPS, DRY_RUN, ALLOW_DIRTY (0/1 flags).
#   Requires: args are a valid flag sequence.
#   Ensures:  globals reflect the flags; returns 0 on success.
#   Raises:   prints to stderr + returns 2 on an unknown arg or a
#             --ref missing its value.
dctl_parse_args() {
    REF="HEAD"; TAKE_DEPS=0; DRY_RUN=0; ALLOW_DIRTY=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --ref)
                if [ $# -lt 2 ]; then echo "ERROR: --ref needs a value" >&2; return 2; fi
                REF="$2"; shift 2 ;;
            --deps)        TAKE_DEPS=1;  shift ;;
            --dry-run)     DRY_RUN=1;    shift ;;
            --allow-dirty) ALLOW_DIRTY=1; shift ;;
            *) echo "ERROR: unknown arg '$1'" >&2; return 2 ;;
        esac
    done
    return 0
}

# dctl_resolve_sha <ref>
#   Echo the full commit SHA for <ref>.
#   Requires: <ref> resolves to a commit in the cwd git repo.
#   Ensures:  echoes the 40-char SHA + returns 0 on success.
#   Raises:   returns 1 + echoes nothing if <ref> is not a commit.
dctl_resolve_sha() {
    local ref="$1" sha
    sha="$( git rev-parse --verify "${ref}^{commit}" 2>/dev/null )" || return 1
    echo "$sha"
}

# dctl_sanitize_sha <raw>
#   Strip everything but lowercase-hex from <raw> (defends against the
#   ".deployed-ref" line carrying "<sha> <ts> <axis>" — we want the SHA only).
#   Ensures: echoes only [0-9a-f] characters from <raw>.
dctl_sanitize_sha() {
    echo "$1" | tr -dc '0-9a-f'
}

# dctl_detect_axis <prev_sha> <sha>
#   Decide the delivery axis between the VM's deployed ref and the target.
#   Requires: <sha> is a valid commit; <prev_sha> is a valid commit or "".
#   Ensures:  echoes "deps" when <prev_sha> is empty (conservative first
#             deploy) OR when any DCTL_DEP_PATHS file differs between the
#             two refs; echoes "code" otherwise. Returns 0.
dctl_detect_axis() {
    local prev_sha="$1" sha="$2"
    if [ -z "$prev_sha" ]; then
        echo "deps"; return 0
    fi
    if git diff --quiet "$prev_sha" "$sha" -- "${DCTL_DEP_PATHS[@]}" 2>/dev/null; then
        echo "code"
    else
        echo "deps"
    fi
}

# dctl_check_clean <sha>
#   Provenance guard: is the working tree identical to <sha> under src/
#   and the dep files? (If not, the deploy would ship un-committed code.)
#   Requires: <sha> is a valid commit.
#   Ensures:  returns 0 when clean, 1 when src/ or a dep file differs.
dctl_check_clean() {
    local sha="$1"
    git diff --quiet "$sha" -- src/ "${DCTL_DEP_PATHS[@]}" 2>/dev/null
}

# dctl_compute_stamp <sha>
#   Build the provenance stamp suffix: committer-ISO-date (colons/plus
#   stripped so it is path-safe) + short SHA.
#   Requires: <sha> is a valid commit.
#   Ensures:  echoes "<YYYY-MM-DDThhmmssZZ>-<short8>" + returns 0.
dctl_compute_stamp() {
    local sha="$1" short="${1:0:8}"
    echo "$( git show -s --format=%cI "$sha" | tr -d ':+' )-$short"
}
