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

# ── pfv_req_effective ────────────────────────────────────────────────────────
# Resolve a contract `req` field to REQUIRED or OPTIONAL against the LIVE env.
#
# WHY THIS EXISTS (2026-07-26, first real `preflight pre` run — 7 warnings, 5 of
# them false). The contract already said these vars were OPTIONAL and the runner
# still reported UNSET-and-optional as UNKNOWN-WARN with a remedy. An OPTIONAL var
# that is absent is COMPLIANT; warning on it makes a reader triage a non-defect
# every run, which is how a reader learns to stop reading the tier — and then the
# one real warning is invisible. Same defect class as b5b6d252.
#
# It also adds the form the flat OPTIONAL/REQUIRED split could not express:
#
#     OPTIONAL_UNLESS:<VAR>=<VALUE>
#
# meaning "REQUIRED exactly when <VAR> currently equals <VALUE>, OPTIONAL otherwise".
# The Vertex trio is why. All three absent is a SAFE, coherent state — Vertex is off.
# The dangerous state is a PARTIAL set: CLAUDE_CODE_USE_VERTEX=1 with no
# CLOUD_ML_REGION yields model-not-found, which the CC wizard mis-reports as
# "permission denied" (the contract's own note on that row). A flat OPTIONAL cannot
# distinguish the safe emptiness from the dangerous half-fill, so it warned on the
# safe one and would have stayed quiet on the dangerous one — the alarm was
# loudest exactly where nothing was wrong.
#
# Requires:
#   - $1 = the contract's req field, verbatim
# Ensures:
#   - prints REQUIRED for "REQUIRED", or for OPTIONAL_UNLESS whose condition HOLDS
#   - prints OPTIONAL for "OPTIONAL", or for OPTIONAL_UNLESS whose condition does not
#   - an unparseable OPTIONAL_UNLESS prints REQUIRED — a malformed condition must not
#     silently downgrade an assertion; not-knowing makes the waiver unsafe
#   - prints REQUIRED for any unrecognised value, for the same reason
#   - never raises; reads the env, writes nothing
pfv_req_effective() {
    local req="$1"
    case "$req" in
        OPTIONAL) printf 'OPTIONAL'; return 0 ;;
        REQUIRED) printf 'REQUIRED'; return 0 ;;
        OPTIONAL_UNLESS:*)
            local cond var val observed
            cond="${req#OPTIONAL_UNLESS:}"
            case "$cond" in
                *=*) ;;
                *)   printf 'REQUIRED'; return 0 ;;    # malformed ⇒ assert, never waive
            esac
            var="${cond%%=*}"
            val="${cond#*=}"
            [ -n "$var" ] || { printf 'REQUIRED'; return 0; }
            observed="$( eval "printf '%s' \"\${$var:-}\"" )"
            if [ "$observed" = "$val" ]; then printf 'REQUIRED'; else printf 'OPTIONAL'; fi
            return 0 ;;
        *) printf 'REQUIRED'; return 0 ;;
    esac
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

# ── pfv_compose_var_regime ───────────────────────────────────────────────────
# How does THIS compose file treat this variable? (row b5ca8fd5)
#
# WHY DERIVE INSTEAD OF DECLARING (Mr. Radio's ruling, 2026-07-27)
#   env-contract.tsv has ONE `requirement` column, and the venues disagree:
#       docker-compose.cloud-gpu.yml:193   ${LUPIN_MODEL_SERVER_URL:?…}       required
#       docker-compose.yml:193,299         ${LUPIN_MODEL_SERVER_URL:-http://…} defaulted
#       docker-compose.cloud-test.yml:113  http://lupin-model-server:7998      hardcoded
#   The obvious fix is a per-venue requirement column. That would be a SECOND
#   authority for a fact compose already states — the shape decision 2b20a6d6 found
#   with FOUR authorities for "which store backs this data" and no comparator
#   between them. The compose interpolation regime IS the requirement, declared
#   where the venue is defined. Adding a column duplicates it; deriving reads it.
#
# ⚠️ THE RISK THIS TRADE ACCEPTS: it replaces a STATED fact with a PARSED one, so
#   this parser becomes the authority. A parser that silently mis-classifies a form
#   nobody enumerated does it quietly, at a rate that reads like noise. So every
#   form in the compose grammar is enumerated EXPLICITLY, and anything else is a
#   loud UNKNOWN — never a default to OPTIONAL, which would waive an assertion by
#   accident.
#
# THE FULL GRAMMAR (docker compose interpolation), all seven forms:
#     ${VAR}       BARE       unset interpolates to empty; compose only WARNS
#     ${VAR:-d}    DEFAULTED  default when unset OR empty
#     ${VAR-d}     DEFAULTED  default when unset only
#     ${VAR:?e}    REQUIRED   compose ABORTS when unset OR empty
#     ${VAR?e}     REQUIRED   compose ABORTS when unset only
#     ${VAR:+r}    ALTERNATE  substitutes only when SET; unset is fine
#     ${VAR+r}     ALTERNATE  substitutes only when set (even if empty)
#   Measured 2026-07-27 across every docker-compose*.yml in the repo: 27
#   interpolations total = 13 `:?` + 13 `:-` + 1 bare, and the three classes sum to
#   the total (a count that did NOT reconcile is what exposed my first, broken
#   tally). The other four forms are absent TODAY — which is not a reason to leave
#   them unhandled, because absence now is not absence later.
#
# Requires:
#   - $1 = path to a compose file, $2 = variable name
# Ensures:
#   - prints exactly one of:
#       REQUIRED | DEFAULTED | ALTERNATE | BARE | LITERAL | ABSENT | CONFLICT | UNKNOWN
#   - returns 0 for a confidently-classified regime, 2 for CONFLICT/UNKNOWN and for
#     an unreadable file or empty name — the caller must treat 2 as
#     cannot-determine, never as a pass
#   - LITERAL means the name appears as a compose KEY with a hardcoded value and is
#     interpolated NOWHERE — cloud-test.yml's shape. The env var is not consulted at
#     all on that venue, so asserting the HOST/container env for it would be asking
#     about a knob that is not wired
#   - CONFLICT means ONE file interpolates the same var under two different
#     operators. That is a real inconsistency in the file, and reporting it as
#     either requirement would pick a side silently
#   - matching is anchored on the character AFTER the name, so ${LUPIN_ROOT} and
#     ${LUPIN_ROOT_EXTRA} can never be confused for one another
pfv_compose_var_regime() {
    local path="$1" name="$2" ops="" n=0 op pat
    [ -r "$path" ] || { printf 'UNKNOWN'; return 2; }
    [ -n "$name" ] || { printf 'UNKNOWN'; return 2; }

    # ⚠️ STRUCTURED AS "IS IT REFERENCED AT ALL?" THEN "WHICH OPERATOR?", DELIBERATELY.
    # The first cut of this function matched only the KNOWN operators in one regex.
    # That made an UNENUMERATED operator — say `${VAR:%odd}` — fail to match at all,
    # so the var fell through to the not-interpolated branch and was reported
    # **ABSENT: not present in this file**, about a variable sitting right there on
    # line N. My own negative control caught it, because the verdict was predicted
    # before the run.
    #
    # That is the parser's reach standing in for the file's content — the same defect
    # class this instrument exists to remove, in the instrument. The tier happened to
    # land safe (ABSENT maps to UNDETERMINED, not OPTIONAL), but the FACT reported was
    # false, and a reader would have concluded the venue does not wire the var.
    #
    # ⇒ Detect the reference FIRST, on the name alone. Only then classify. Anything
    #   referenced-but-unclassifiable is a loud UNKNOWN.

    # Referenced as ${NAME…} or as braceless $NAME. Braceless is legal compose
    # (equivalent to a bare ${NAME}) and appears ZERO times in this repo today —
    # which is a reason to handle it, not a reason to skip it.
    local braced=false bare_ref=false
    grep -qE '\$\{'"$name"'([^A-Za-z0-9_]|$)'  "$path" 2>/dev/null && braced=true
    grep -qE '\$'"$name"'([^A-Za-z0-9_{]|$)'   "$path" 2>/dev/null && bare_ref=true

    if [ "$braced" = true ]; then
        # EVERY form in the grammar, tried longest-operator-first so `:-` is never
        # read as a bare `-`. This list IS the enumeration; adding a compose operator
        # means adding a line here, and forgetting to yields UNKNOWN rather than a
        # confident wrong answer.
        for pat in ':-:DEFAULTED' ':\?:REQUIRED' ':\+:ALTERNATE' \
                   '-:DEFAULTED'  '\?:REQUIRED'  '\+:ALTERNATE' '}:BARE'; do
            op="${pat##*:}"
            local sym="${pat%:*}"
            if grep -qE '\$\{'"$name$sym" "$path" 2>/dev/null; then
                case " $ops " in *" $op "*) ;; *) ops="$ops $op"; n=$(( n + 1 )) ;; esac
            fi
        done
        # Referenced with braces but matching NO known operator ⇒ a form this reader
        # does not understand. Say so.
        [ "$n" -eq 0 ] && { printf 'UNKNOWN'; return 2; }
    fi

    if [ "$bare_ref" = true ]; then
        case " $ops " in *" BARE "*) ;; *) ops="$ops BARE"; n=$(( n + 1 )) ;; esac
    fi

    # One file interpolating the same var under two operators is a real
    # inconsistency in that file. Reporting either requirement would pick a side
    # silently.
    if [ "$n" -gt 1 ]; then printf 'CONFLICT'; return 2; fi
    if [ "$n" -eq 1 ]; then printf '%s' "${ops# }"; return 0; fi

    # Not referenced anywhere. Distinguish "wired to a hardcoded value here" from
    # "not present at all" — collapsing them would report a var this venue
    # deliberately pins as though the venue had forgotten it.
    if grep -qE "^[[:space:]]*$name:" "$path" 2>/dev/null; then
        printf 'LITERAL'; return 0
    fi
    printf 'ABSENT'; return 0
}

# ── pfv_regime_requirement ───────────────────────────────────────────────────
# Map a compose regime to the requirement tier preflight should assert at.
#
# Requires:  $1 = a regime token from pfv_compose_var_regime
# Ensures:
#   - prints REQUIRED for REQUIRED (compose itself aborts the bring-up without it,
#     so asserting it as blocking adds NO new abort surface — it moves an existing
#     failure earlier and gives it a name)
#   - prints OPTIONAL for DEFAULTED / ALTERNATE / BARE — in all three, an unset var
#     is a state compose tolerates
#   - prints UNDETERMINED for LITERAL / ABSENT / CONFLICT / UNKNOWN / anything else.
#     ⚠️ An UNRECOGNIZED token maps to UNDETERMINED, never to OPTIONAL: a typo or a
#     future regime must surface as "I cannot tell", because silently waiving an
#     assertion is the failure this whole file exists to prevent, and it is the
#     quiet one
pfv_regime_requirement() {
    case "$1" in
        REQUIRED)                    printf 'REQUIRED'     ; return 0 ;;
        DEFAULTED|ALTERNATE|BARE)    printf 'OPTIONAL'     ; return 0 ;;
        *)                           printf 'UNDETERMINED' ; return 2 ;;
    esac
}

# ── pfv_requirement_agrees ───────────────────────────────────────────────────
# Does the CONTRACT's requirement column agree with what the compose file does?
#
# WHY THIS IS THE HALF THAT PAYS FOR THE TRADE: deriving the requirement removes a
# duplicate authority, but the contract column still exists and is still read by
# other consumers (pfv_contract_push_env_names, the coverage comparator). Two
# authorities with nothing comparing them is the defect; two authorities WITH a
# comparator is a check. This is the comparator.
#
# Requires:  $1 = contract requirement field (verbatim), $2 = derived requirement
# Ensures:
#   - returns 0 when they agree, 1 when they DISAGREE, 2 when the comparison cannot
#     be made (derived is UNDETERMINED, or either side is empty)
#   - the contract side is resolved through pfv_req_effective first, so an
#     OPTIONAL_UNLESS row is compared on what it means RIGHT NOW rather than on its
#     literal text
#   - a 2 is never an agreement. A comparator that answers "fine" whenever it cannot
#     parse its input is quietest exactly when something has changed underneath it
pfv_requirement_agrees() {
    local contract_req="$1" derived="$2" effective
    [ -n "$contract_req" ] || return 2
    [ -n "$derived" ]      || return 2
    [ "$derived" = "UNDETERMINED" ] && return 2
    effective="$( pfv_req_effective "$contract_req" )"
    [ "$effective" = "$derived" ] && return 0
    return 1
}

# ── pfv_config_block_id ──────────────────────────────────────────────────────
# Extract the `config_block_id=<value>` token from a LUPIN_CONFIG_MGR_CLI_ARGS
# string.
#
# Requires:  $1 = the full CLI-args string (may contain other space-separated tokens)
# Ensures:
#   - prints the block id with NO trailing newline, returns 0
#   - returns 2 and prints nothing when no config_block_id token is present —
#     ABSENT and EMPTY must not collapse, because "the knob is missing" and
#     "the knob is set to nothing" have different remedies
pfv_config_block_id() {
    local args="$1" tok
    tok="$( printf '%s' "$args" | tr ' ' '\n' | grep -m1 '^config_block_id=' || true )"
    [ -n "$tok" ] || return 2
    printf '%s' "${tok#config_block_id=}"
}

# ── pfv_env_block_agree ──────────────────────────────────────────────────────
# Do LUPIN_ENV and the INI block id name the SAME environment? (R4)
#
# WHY THIS EXISTS: two knobs with similar names, set side by side in every
# compose file, choosing COUPLED facts — and nothing compares them.
#   LUPIN_ENV                  chooses the DATABASE.  cloud-test.yml's own
#                              comment says it is "never inferred".
#   config_block_id            chooses the INI BLOCK.
# They can disagree silently, and the failure mode is the worst kind: an app
# reading testing config while writing to the development database, or the
# reverse. Nothing crashes. All four shipped service blocks agree TODAY, which
# is exactly why this needs a comparator rather than an inspection — agreement
# now is not a property, it is a coincidence nobody is holding in place.
#
# THE AGREEMENT RULE, stated so it can be argued with:
#   strip a leading "Lupin:+", take the segment before the first "-", lowercase,
#   and require equality with a lowercased LUPIN_ENV. The suffix is deliberately
#   ignored — "Lupin:+Testing-GCS" is a testing block with a storage variant,
#   and treating the variant as a disagreement would make the check cry wolf on
#   the shipped configuration.
#
# Requires:  $1 = LUPIN_ENV value, $2 = config block id
# Ensures:
#   - returns 0 when they agree, 1 when they DISAGREE
#   - returns 2 (UNDETERMINED) when either input is empty, or when the block id
#     does not carry the "Lupin:+" prefix this rule knows how to read. An
#     unreadable block id is NOT reported as agreement: a comparator that
#     answers "fine" whenever it cannot parse its input is quietest exactly
#     when something has changed underneath it. Callers must treat 2 as
#     blocking-and-loud, not as a pass
pfv_env_block_agree() {
    local lupin_env="$1" block_id="$2" head
    [ -n "$lupin_env" ] || return 2
    [ -n "$block_id" ]  || return 2
    case "$block_id" in Lupin:+*) ;; *) return 2 ;; esac
    head="${block_id#Lupin:+}"
    head="${head%%-*}"
    [ -n "$head" ] || return 2
    [ "$( printf '%s' "$head" | tr '[:upper:]' '[:lower:]' )" \
      = "$( printf '%s' "$lupin_env" | tr '[:upper:]' '[:lower:]' )" ] && return 0
    return 1
}

# ── pfv_secret_fingerprint ───────────────────────────────────────────────────
# A comparable fingerprint for a secret VALUE, never the value itself (R2).
#
# WHY A FINGERPRINT AND NOT THE VALUE: the whole point of `creds-status` is to
# print several authorities SIDE BY SIDE so a divergence is visible. Printing the
# secrets would make the tool itself the leak — and it would be run precisely
# when someone is already confused, i.e. when they are most likely to paste the
# output somewhere.
#
# Requires:
#   - $1 = the value (may be empty)
#
# Ensures:
#   - prints "sha256:<first 12 hex>" for a non-empty value, returns 0
#   - prints "EMPTY" and returns 2 for a present-but-empty value — a key file
#     that exists and holds nothing is a DIFFERENT failure from one that is
#     missing, and the two have different remedies. Collapsing them is how a
#     truncated write reads as "not configured yet"
#   - returns 3 and prints "NO-SHA-TOOL" when no sha256 utility exists, rather
#     than printing something that looks like a fingerprint
pfv_secret_fingerprint() {
    local value="$1" sum
    if [ -z "$value" ]; then printf 'EMPTY'; return 2; fi
    if   command -v sha256sum >/dev/null 2>&1; then sum="$( printf '%s' "$value" | sha256sum | cut -c1-12 )"
    elif command -v shasum    >/dev/null 2>&1; then sum="$( printf '%s' "$value" | shasum -a 256 | cut -c1-12 )"
    else printf 'NO-SHA-TOOL'; return 3; fi
    printf 'sha256:%s' "$sum"
}

# ── pfv_read_secret_file ─────────────────────────────────────────────────────
# Read a secret file, distinguishing every way it can fail to yield a value.
#
# WHY FOUR STATES AND NOT A STRING-OR-EMPTY: the 2026-07-25 outage was a key file
# that EXISTED and was UNREADABLE (mode 600, uid 1001) — `os.path.exists()` said
# yes and a plain `cat` by the SSH user printed nothing, with no error. A reader
# that returns "" for absent, unreadable, and empty alike cannot tell the
# operator which of three different things to do.
#
# Requires:  $1 = path
# Ensures:
#   - prints the trimmed contents and returns 0 when readable and non-empty
#   - prints ABSENT (1) / UNREADABLE (2) / EMPTY (3), each distinct, otherwise
pfv_read_secret_file() {
    local path="$1" content
    [ -e "$path" ] || { printf 'ABSENT'; return 1; }
    [ -r "$path" ] || { printf 'UNREADABLE'; return 2; }
    content="$( tr -d '\n\r' < "$path" 2>/dev/null )"
    [ -n "$content" ] || { printf 'EMPTY'; return 3; }
    printf '%s' "$content"
}

# ── pfv_fingerprints_agree ───────────────────────────────────────────────────
# Do a set of fingerprints all name the same secret?
#
# Requires:  "$@" = zero or more fingerprint strings
# Ensures:
#   - returns 0 when every COMPARABLE fingerprint is identical
#   - returns 1 when two comparable fingerprints differ
#   - returns 2 when FEWER THAN TWO comparable fingerprints were supplied —
#     "they all agree" is not a claim one value can support, and reporting
#     agreement from a single surface is how a lone stale key reads as verified.
#     Non-fingerprints (ABSENT/UNREADABLE/EMPTY/UNAVAILABLE/NO-SHA-TOOL) are
#     excluded from the comparison rather than counted as a mismatch: an absent
#     surface is a fact about coverage, not a disagreement about the value
pfv_fingerprints_agree() {
    local first="" fp n=0
    for fp in "$@"; do
        case "$fp" in sha256:*) ;; *) continue ;; esac
        n=$(( n + 1 ))
        if [ -z "$first" ]; then first="$fp"
        elif [ "$fp" != "$first" ]; then return 1; fi
    done
    [ "$n" -ge 2 ] || return 2
    return 0
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
