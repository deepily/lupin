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
# Design: src/rnd/v0.1.9/2026.06.23-gcp-code-sync-to-runtime-design.md §4
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

# dctl_venue_present <container> <ps_names>
#   Is <container> among the names in <ps_names> (one per line, as
#   `docker ps -a --format '{{.Names}}'` emits them)?
#
#   WHY (row 5f1532d1). This script is hardcoded to the cloud-TEST venue —
#   lupin-rest-cloud-test / docker-compose.cloud-test.yml / cloud-test.env. The
#   one and only VM runs the cloud-GPU venue. Measured on lupin-host-test
#   2026-08-24, `lupin-rest-cloud-test` does not exist in ANY state, not even
#   stopped, so every `docker restart|inspect` here addresses nothing. Nobody is
#   broken today because the working path is `lupin-vm.sh deploy`; the hazard is
#   a reader picking this script by its name — it reads like THE deploy script —
#   and concluding the container is missing or that code deploys are impossible.
#
#   Requires: $1 = the container name to look for; $2 = newline-separated names.
#   Ensures:
#     - returns 0 when present, 1 when absent, 2 when the name list is EMPTY.
#     - the empty case is SEPARATE on purpose. "docker reported no containers"
#       and "docker reported containers, none of them mine" are different facts:
#       the first usually means the probe itself failed (ssh died, docker down,
#       no sudo) and answering "absent" to a question that was never successfully
#       asked is how a broken probe becomes a confident wrong verdict.
#     - the match is WHOLE-LINE exact, never a substring: `lupin-rest` is a prefix
#       of `lupin-rest-cloud-gpu`, and a substring test would report a cloud-test
#       container present on a VM that runs only cloud-gpu — the precise
#       false-green this guard exists to stop.
#     - PURE: takes the ps output as an argument rather than shelling out, so the
#       decision is testable without a VM, a network, or docker.
dctl_venue_present() {
    local want="$1" names="$2"
    [ -n "$( printf '%s' "$names" | tr -d '[:space:]' )" ] || return 2
    printf '%s\n' "$names" | grep -Fxq "$want" && return 0
    return 1
}
