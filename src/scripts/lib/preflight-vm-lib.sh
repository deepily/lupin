#!/bin/bash
#
# preflight-vm-lib.sh — PURE helpers for preflight-vm.sh (task 47c4801b).
#
# Every function here is VM-uncoupled: no SSH, no docker, no gcloud, no network.
# The runner (preflight-vm.sh) gathers real state and feeds it to these; that split
# is what makes the logic unit-testable, following the precedent set by
# src/scripts/lib/deploy-cloud-test-lib.sh (task d8c699aa).
#
# Naming: every function is prefixed `pfv_` so a `source` into the runner cannot
# collide with the runner's own names.
#
# Unit tests: src/tests/unit/deploy/test_preflight_vm_lib.py
#

# ── pfv_parse_manifest ───────────────────────────────────────────────────────
# Emit the manifest's data rows, stripped of comments and blank lines.
#
# Requires:
#   - $1 is a readable path to a TSV manifest in the vm-unversioned-manifest.tsv format
# Ensures:
#   - prints one tab-separated row per entry: local<TAB>remote<TAB>owner<TAB>mode<TAB>req
#   - '#' comment lines and blank/whitespace-only lines are dropped
#   - returns 1 (printing nothing) when the file is unreadable
#   - returns 0 with NO output for a manifest that is all comments — an empty
#     manifest is a legitimate state, NOT an error; the caller decides what it means
pfv_parse_manifest() {
    local path="$1"
    [ -r "$path" ] || return 1
    # NB: the field count is NOT validated here. A malformed row must reach
    # pfv_manifest_field, which reports it by name — dropping it silently here
    # would make a typo'd row indistinguishable from an absent one.
    grep -v '^[[:space:]]*#' "$path" | grep -v '^[[:space:]]*$'
    return 0
}

# ── pfv_manifest_field ───────────────────────────────────────────────────────
# Extract field N (1-5) from a manifest row.
#
# Requires:
#   - $1 is a manifest row, $2 is a field index 1..5
# Ensures:
#   - prints the field's value with NO trailing newline, matching pfv_classify_probe.
#     `cut` appends one; it is stripped here so every printf-style helper in this lib
#     has the same output contract and a caller can compare with `=` without $( ) first
#   - returns 2 and prints nothing when the row has fewer than 5 tab-separated
#     fields — a short row is a MALFORMED MANIFEST, not a missing value, and the
#     two must not collapse onto the same empty string
pfv_manifest_field() {
    pfv_row_field "$1" "$2" 5
}

# ── pfv_row_field ────────────────────────────────────────────────────────────
# Generic TSV field extractor with an arity floor.
#
# Requires:
#   - $1 = row, $2 = field index, $3 = minimum field count the row must have
# Ensures:
#   - prints the field with NO trailing newline
#   - returns 2 and prints nothing when the row has fewer than $3 fields
#   - the arity floor is a PARAMETER, not a constant, so the manifest (5 columns)
#     and the env contract (6 columns) share one implementation and cannot drift
#     into two subtly different parsers — which is the very defect class this
#     whole body of work exists to remove
pfv_row_field() {
    local row="$1" idx="$2" min="$3"
    local n
    n="$( printf '%s' "$row" | awk -F'\t' '{ print NF }' )"
    [ "$n" -ge "$min" ] 2>/dev/null || return 2
    printf '%s' "$( printf '%s' "$row" | cut -d"$( printf '\t' )" -f"$idx" )"
}

# ── pfv_contract_field ───────────────────────────────────────────────────────
# Field N (1-6) of an env-contract.tsv row.
#
# Requires:  $1 = row, $2 = index 1..6
# Ensures:   as pfv_row_field with an arity floor of 6
pfv_contract_field() {
    pfv_row_field "$1" "$2" 6
}

# ── pfv_contract_push_env_names ──────────────────────────────────────────────
# The set of env vars `lupin-vm.sh push-env` is contractually responsible for
# writing to the VM's ~/.bashrc, DERIVED from env-contract.tsv (R3b).
#
# WHY THIS EXISTS: env-contract.tsv's own header says push-env "SHOULD generate
# from this file rather than carrying its own hardcoded echo list (follow-on;
# the list is duplicated today)". Until this function the contract had ONE
# consumer (preflight check A1) where it needed TWO — so a var could be added
# to the contract, asserted by preflight, and never written by push-env. The
# operator's remedy for that preflight failure is "run push-env", which would
# not have fixed it. An alarm whose prescribed remedy cannot clear it is worse
# than no alarm.
#
# The selection predicate is the contract's own columns, not a second list:
#   surface  HOST or BOTH  — CONTAINER-only vars are compose's job, not bashrc's
#   writer   mentions push-env
# LUPIN_API_KEY is excluded by the DATA, not by a special case here: its writer
# column reads "minted ON the target" precisely because the key is validated
# per-database and a dev-box value can never authenticate against the VM.
#
# Requires:
#   - $1 is a readable env-contract.tsv path
#
# Ensures:
#   - prints each qualifying var NAME on its own line, in contract order
#   - returns 1 and prints nothing when $1 is unreadable — an unreadable
#     contract is a BROKEN INPUT, and must not read as "no vars to write",
#     which would let push-env silently write nothing and report success
#   - returns 0 with NO output when the contract is readable but has no
#     qualifying row; that is a legitimate (if unlikely) empty answer and is
#     deliberately distinguished from the unreadable case above
#   - malformed rows (fewer than 6 fields) are SKIPPED, not guessed at; the
#     contract's own well-formedness is check A1's assertion, not this one's
pfv_contract_push_env_names() {
    local contract="$1" row name surface writer
    [ -r "$contract" ] || return 1
    while IFS= read -r row; do
        [ -n "$row" ] || continue
        name="$( pfv_contract_field "$row" 1 )" || continue
        surface="$( pfv_contract_field "$row" 2 )"
        writer="$(  pfv_contract_field "$row" 3 )"
        case "$surface" in HOST|BOTH) ;; *) continue ;; esac
        case "$writer"  in *push-env*) ;; *) continue ;; esac
        printf '%s\n' "$name"
    done < <( pfv_parse_manifest "$contract" )
    return 0
}

# ── pfv_contract_remedy ──────────────────────────────────────────────────────
# The remedy line for a failing/unset contract var, DERIVED from the var's own
# `writer` column rather than assumed.
#
# WHY THIS EXISTS — found live 2026-07-26 by running preflight after wiring R3b.
# A1 hardcoded "lupin-vm.sh push-env" as the remedy for EVERY host var. Four of
# the contract's vars are not push-env's to write, and the contract says so in
# the column right next to them:
#     LUPIN_API_KEY                writer = minted ON the target
#     CLAUDE_CODE_USE_VERTEX       writer = operator ~/.bashrc
#     ANTHROPIC_VERTEX_PROJECT_ID  writer = operator ~/.bashrc
#     CLOUD_ML_REGION              writer = operator ~/.bashrc
# So the instrument told the operator to run a command that CANNOT clear the
# alarm — for LUPIN_API_KEY it is worse than useless, because push-env
# deliberately refuses to ship a per-database key and running it would look like
# compliance while changing nothing.
#
# This is the same defect R3b closes on the WRITE side, surviving on the READ
# side: one fact (who writes this var) asserted in two places, with nothing
# comparing them. Now there is one place, and it is the contract.
#
# Requires:
#   - $1 = the row's writer field, $2 = the var name
#
# Ensures:
#   - prints a remedy string with NO trailing newline
#   - an UNRECOGNIZED writer yields a remedy that names the writer verbatim and
#     points at the contract, rather than guessing a command. A wrong remedy is
#     more expensive than an honest "the contract says X writes this" — the
#     operator can act on the second and is misled by the first
pfv_contract_remedy() {
    local writer="$1" name="$2"
    case "$writer" in
        *push-env*)
            printf '%s' "lupin-vm.sh push-env   # writes $name to the VM ~/.bashrc" ;;
        *minted*)
            printf '%s' "MINT it on the target (push-env deliberately will NOT ship this): create_service_account_postgres.py with LUPIN_ENV=testing, then export $name by hand. A dev-box value can never validate against the VM's own database." ;;
        *operator*)
            printf '%s' "set $name by hand in the operator's ~/.bashrc on that machine (contract writer: $writer) — push-env does NOT write it" ;;
        *cloud-gpu.env*)
            printf '%s' "add $name to cloud-gpu.env on the VM (git-ignored, VM-local; ship the file with: lupin-vm.sh push-unversioned)" ;;
        *compose*)
            printf '%s' "set $name in the compose environment: block (contract writer: $writer)" ;;
        *)
            printf '%s' "no known remedy path — env-contract.tsv names the writer as '$writer' for $name; fix it there or at that writer" ;;
    esac
}

# ── pfv_shape_matches ────────────────────────────────────────────────────────
# Validate an env var's VALUE against the SHAPE its contract row declares.
#
# Requires:
#   - $1 = observed value, $2 = shape token, $3 = the VM root prefix (for PATH_VM)
# Ensures:
#   - returns 2 when the value is EMPTY — unset is a distinct outcome from wrong,
#     and the two have different remedies
#   - returns 0 when the value satisfies the shape, 1 when it does not
#   - an UNRECOGNIZED shape token returns 0 (accept) and is NOT treated as a
#     failure of the VALUE: a typo in the contract must not be reported as a
#     broken environment. The contract's own well-formedness is a separate
#     assertion, and conflating the two would send the operator to the wrong file
#   - SECRET is never pattern-matched, only checked non-empty — a shape rule that
#     inspected a secret's content would be one more place a secret can leak
pfv_shape_matches() {
    local value="$1" shape="$2" vm_prefix="$3"
    [ -n "$value" ] || return 2
    case "$shape" in
        PATH_VM)
            pfv_env_is_vm_path "$value" "$vm_prefix"
            local rc=$?
            # 0 = ok; anything else (dev path, wrong root) is a shape failure here.
            [ "$rc" -eq 0 ] && return 0
            return 1 ;;
        PATH_ANY)
            case "$value" in /*) return 0 ;; *) return 1 ;; esac ;;
        EMAIL)
            case "$value" in *?@?*.?*) return 0 ;; *) return 1 ;; esac ;;
        NUMERIC)
            case "$value" in ''|*[!0-9]*) return 1 ;; *) return 0 ;; esac ;;
        ENUM:*)
            local allowed="${shape#ENUM:}" one
            local IFS='|'
            for one in $allowed; do
                [ "$value" = "$one" ] && return 0
            done
            return 1 ;;
        SECRET|LITERAL)
            return 0 ;;
        *)
            return 0 ;;
    esac
}

# ── pfv_mode_matches ─────────────────────────────────────────────────────────
# Compare an observed octal mode against an expected one.
#
# Requires:
#   - $1 = observed mode (e.g. "644", "0644", "2770"), $2 = expected ("-" = skip)
# Ensures:
#   - returns 0 when expected is "-" (assertion deliberately waived)
#   - returns 0 on an exact match after normalizing a leading zero, so "0644"
#     and "644" agree — `stat` output differs by platform and a false RED from
#     formatting is the instrument lying, not a finding
#   - returns 1 on a real mismatch
#   - returns 2 when the observed value is empty (could not be read) — UNKNOWN is
#     never folded into a pass (the secret_drift rule)
pfv_mode_matches() {
    local observed="$1" expected="$2"
    [ "$expected" = "-" ] && return 0
    [ -n "$observed" ]    || return 2
    # Normalize: strip leading zeros but keep at least 3 digits of significance.
    local o e
    o="$( printf '%s' "$observed" | sed 's/^0*\([0-7][0-7][0-7][0-7]*\)$/\1/' )"
    e="$( printf '%s' "$expected" | sed 's/^0*\([0-7][0-7][0-7][0-7]*\)$/\1/' )"
    [ "$o" = "$e" ] && return 0
    return 1
}

# ── pfv_owner_matches ────────────────────────────────────────────────────────
# Compare an observed numeric uid:gid against an expected one.
#
# Requires:
#   - $1 = observed "uid:gid", $2 = expected "uid:gid" ("-" = skip)
# Ensures:
#   - returns 0 when expected is "-"
#   - returns 0 on exact match, 1 on mismatch, 2 when observed is empty
#   - comparison is NUMERIC-STRING exact: a name ("rruiz:rruiz") never matches a
#     number, deliberately. The whole persona-404 defect was a uid divergence that
#     read fine by NAME on each side (bug: host 1721846087 vs container 1001).
pfv_owner_matches() {
    local observed="$1" expected="$2"
    [ "$expected" = "-" ] && return 0
    [ -n "$observed" ]    || return 2
    [ "$observed" = "$expected" ] && return 0
    return 1
}

# ── pfv_diff_mount_sets ──────────────────────────────────────────────────────
# Report compose-declared mount targets that are ABSENT from the running set.
#
# Requires:
#   - $1 = newline-separated list of DECLARED container paths (from the compose file)
#   - $2 = newline-separated list of RUNNING container paths (from docker inspect)
# Ensures:
#   - prints one missing target per line, sorted; prints nothing when none are missing
#   - returns 0 when nothing is missing, 1 when at least one is
#   - the comparison is ONE-WAY by design: a running container legitimately carries
#     mounts the compose file does not declare (anonymous volumes, runtime binds), so
#     an extra is not a defect. A DECLARED-but-absent one always is — it means the
#     container predates the compose edit (mount tables are fixed at creation).
pfv_diff_mount_sets() {
    local declared="$1" running="$2"
    local missing
    missing="$( comm -23 \
        <( printf '%s\n' "$declared" | grep -v '^[[:space:]]*$' | sort -u ) \
        <( printf '%s\n' "$running"  | grep -v '^[[:space:]]*$' | sort -u ) )"
    [ -z "$missing" ] && return 0
    printf '%s\n' "$missing"
    return 1
}

# ── pfv_env_is_vm_path ───────────────────────────────────────────────────────
# Assert an env var's value is a VM path, not a dev-box path.
#
# Requires:
#   - $1 = the value to check, $2 = the VM root prefix it must start with
# Ensures:
#   - returns 2 when the value is EMPTY (unset var — a distinct failure from wrong)
#   - returns 3 when the value looks like a DEV-BOX path (/mnt/DATA01/...) — reported
#     separately because the remedy differs: unset means "run push-env", whereas a dev
#     path means "push-env shipped the wrong values", and conflating them sends the
#     operator down the wrong branch
#   - returns 0 when it starts with the VM prefix, 1 otherwise
pfv_env_is_vm_path() {
    local value="$1" vm_prefix="$2"
    [ -n "$value" ] || return 2
    case "$value" in
        /mnt/DATA01/*) return 3 ;;
    esac
    case "$value" in
        "$vm_prefix"*) return 0 ;;
    esac
    return 1
}

# ── pfv_venv_is_foreign ──────────────────────────────────────────────────────
# Detect the trap that cost a whole bring-up: $LUPIN_ROOT/.venv is a SYMLINK into
# another service's venv (.venv-arbiter, uid 1001, python 3.10). The dev box masks
# this completely — there .venv is operator-owned, so the check cannot be developed
# by observation on dev alone.
#
# Requires:
#   - $1 = the resolved venv path, $2 = "true"/"false" is-a-symlink, $3 = its owner uid,
#     $4 = the expected operator uid
# Ensures:
#   - returns 1 when it is a symlink AND owned by a uid other than the operator's
#   - returns 2 when it is a symlink owned by the operator (suspicious, not fatal)
#   - returns 0 otherwise
#   - a non-symlink is ALWAYS 0 regardless of owner: a real directory owned by
#     someone else is a permissions problem the mode checks catch, not this one
pfv_venv_is_foreign() {
    local path="$1" is_link="$2" owner_uid="$3" operator_uid="$4"
    [ -n "$path" ] || return 0
    [ "$is_link" = "true" ] || return 0
    [ "$owner_uid" = "$operator_uid" ] && return 2
    return 1
}

# ── pfv_classify_probe ───────────────────────────────────────────────────────
# Turn a probe's raw outcome into the verdict vocabulary, enforcing the standing
# rule that UNKNOWN is never folded into PASS.
#
# Requires:
#   - $1 = "pass" | "fail" | "unknown", $2 = tier "BLOCK" | "WARN"
# Ensures:
#   - prints exactly one of: OK | FAIL | WARN | UNKNOWN-BLOCK | UNKNOWN-WARN
#   - returns 0 for a non-blocking outcome, 1 for a blocking one
#   - an UNKNOWN at BLOCK tier is BLOCKING. A probe that could not see one side has
#     verified nothing, and calling that a pass is the alarm-gated-on-the-healthy-
#     value defect that let a deleted Cloud SQL socket read as "healthy" for hours.
pfv_classify_probe() {
    local outcome="$1" tier="$2"
    case "$outcome" in
        pass)    printf 'OK';   return 0 ;;
        fail)    if [ "$tier" = "WARN" ]; then printf 'WARN'; return 0; fi
                 printf 'FAIL'; return 1 ;;
        unknown) if [ "$tier" = "WARN" ]; then printf 'UNKNOWN-WARN'; return 0; fi
                 printf 'UNKNOWN-BLOCK'; return 1 ;;
        *)       printf 'UNKNOWN-BLOCK'; return 1 ;;
    esac
}

# ── pfv_phase_includes ───────────────────────────────────────────────────────
# Decide whether a layer runs in the given phase (Rick's both-arms ruling).
#
# Requires:
#   - $1 = phase "pre" | "post" | "full", $2 = layer "A".."E"
# Ensures:
#   - returns 0 when the layer runs in that phase, 1 when it is skipped
#   - PRE runs A, C, E and the B3 payload check, but NOT B-parity or D — the deploy
#     is about to change HEAD, so asserting the OLD ref is meaningless, and the
#     D-tier app probes would be measuring a server that is about to restart
#   - POST and FULL run everything
#   - an unknown layer RUNS (returns 0) rather than being skipped: a typo must
#     surface as a noisy extra probe, never as silently-skipped coverage
pfv_phase_includes() {
    local phase="$1" layer="$2"
    case "$phase" in
        post|full) return 0 ;;
        pre)
            case "$layer" in
                B|D) return 1 ;;
                *)   return 0 ;;
            esac ;;
        *) return 0 ;;
    esac
}
