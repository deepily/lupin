#!/usr/bin/env bash
#
# vertex-cap.sh — list / tweak / restore the Vertex spend-guardrail quota clamps.
#
# Rick's tweakability rider as a tool (store item 495b5c3c, 2026-07-15):
#   "Last thing I want is a cap that doesn't allow me to get any work done...
#    second worst outcome is a cap I can't easily reconfigure."
#
# The clamps, their derivation math, and the posture ruling live in
#   src/rnd/v0.1.9/2026.07.15-vertex-quota-clamp-prep.md   (§2c values, §3.1 slug findings)
# — this script deliberately does NOT restate the derivation; it operates the knobs.
#
# THE SPIKE WORKFLOW (what this tool is for):
#   vertex-cap.sh list                          # where the values live, at a glance
#   vertex-cap.sh set opus 3000 1000            # bump for a burst (increase = fires plain)
#   ... do the spike work ...
#   vertex-cap.sh set opus 1500 500 --force     # back DOWN to the ruling values
#                                               #   (decrease = --force, prints the trade first)
#   vertex-cap.sh restore opus                  # OR: un-clamp entirely to Google defaults
#                                               #   (increase toward defaults = fires plain)
#
#   NOTE the distinction: `restore` returns to GOOGLE'S defaults (no brake at all);
#   returning to RICK'S RULING values is a `set ... --force` decrease. Both are one-liners.
#
# REST-based on purpose: the gcloud alpha quotas component is NOT installed on this box.
# Uses curl + `gcloud auth print-access-token` — same pattern as the applied clamp scripts.
#
# SAFETY MODEL:
#   - Increases (and `restore`) fire plain — raising toward defaults is unrestricted.
#   - Decreases REQUIRE --force: the script prints the worst-case-$/day trade, then attaches
#     ignoreSafetyChecks=QUOTA_DECREASE_PERCENTAGE_TOO_HIGH,QUOTA_DECREASE_BELOW_USAGE.
#     Without --force the safety rail stays armed and Cloud Quotas will refuse big decreases
#     itself (that refusal carries the live usage meter — a refused write is a read).
#   - --dry-run prints the exact curl commands and makes ZERO network calls (list included).
#   - Every invocation appends an audit line to src/tmp/vertex-cap-audit.log.
#
set -euo pipefail

# Resolve the GCP project through the shared fail-loud resolver (cloud-run-config.sh): it reads the
# git-ignored src/scripts/cloud-run.env, honors an env override, and FAILS LOUD if LUPIN_GCP_PROJECT_ID
# is unset — no sandbox default can silently leak onto this LIVE-quota tool (the wrong id would clamp
# the wrong project). cloud-run.env already carries the id, so vertex-cap stays zero-config for Rick.
source "$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )/cloud-run-config.sh"
PROJECT="${PROJECT_ID}"
API="https://cloudquotas.googleapis.com/v1"
PARENT="projects/${PROJECT}/locations/global"
CONTACT_EMAIL="ricardo.felipe.ruiz@gmail.com"
JUSTIFICATION="vertex-cap.sh (store 495b5c3c) - operator adjustment of the c9dd0cc3 spend-guardrail clamps"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
AUDIT_LOG="${SCRIPT_DIR}/../tmp/vertex-cap-audit.log"

DRY_RUN=false
FORCE=false

# ---------------------------------------------------------------------------
# Model registry.
# Per-model quota rows: pref_id|quota_id|dimension_value|kind
#   kind: in | out | total | rpm
# Preference IDs match the ones created by the clamp-prep doc §5 sequence (part 1,
# 2026-07-15). opus carries BOTH base_model slugs: traffic meters on the BARE slug
# (§3.1 addendum #2, confirmed in execution); the versioned 4-8 slug is kept in
# lockstep as the re-key belt.
# ---------------------------------------------------------------------------
model_rows() {
    case "$1" in
        opus)
            cat <<'EOF'
clamp-opus-input-tpm|GlobalOnlinePredictionInputTokensPerMinutePerBaseModel|anthropic-claude-opus|in
clamp-opus-output-tpm|GlobalOnlinePredictionOutputTokensPerMinutePerBaseModel|anthropic-claude-opus|out
clamp-opus-rpm|GlobalOnlinePredictionRequestsPerMinutePerProjectPerBaseModel|anthropic-claude-opus|rpm
clamp-opus-4-8-input-tpm|GlobalOnlinePredictionInputTokensPerMinutePerBaseModel|anthropic-claude-opus-4-8|in
clamp-opus-4-8-output-tpm|GlobalOnlinePredictionOutputTokensPerMinutePerBaseModel|anthropic-claude-opus-4-8|out
clamp-opus-4-8-rpm|GlobalOnlinePredictionRequestsPerMinutePerProjectPerBaseModel|anthropic-claude-opus-4-8|rpm
EOF
            ;;
        deepseek)
            cat <<'EOF'
clamp-deepseek-v32-input-tpm|GlobalOpenapiInputTokensPerMinutePerBaseModel|deepseek-v3.2-maas|in
clamp-deepseek-v32-output-tpm|GlobalOpenapiOutputTokensPerMinutePerBaseModel|deepseek-v3.2-maas|out
clamp-deepseek-v32-total-tpm|GlobalOpenapiTotalTokensPerMinutePerBaseModel|deepseek-v3.2-maas|total
EOF
            ;;
        gpt-oss)
            cat <<'EOF'
clamp-gpt-oss-120b-input-tpm|GlobalOpenapiInputTokensPerMinutePerBaseModel|gpt-oss-120b-maas|in
clamp-gpt-oss-120b-output-tpm|GlobalOpenapiOutputTokensPerMinutePerBaseModel|gpt-oss-120b-maas|out
clamp-gpt-oss-120b-total-tpm|GlobalOpenapiTotalTokensPerMinutePerBaseModel|gpt-oss-120b-maas|total
EOF
            ;;
        *)
            return 1
            ;;
    esac
}

# Recorded defaults (the `restore` targets + the list view's reference column).
# Sources: Openapi family 40k/12k/52k (verified live 2026-07-13, c9dd0cc3);
# bare-opus 20M in / 2M out / 2,000 rpm (quotaInfos dump, doc §3.1). The versioned
# opus-4-8 slug has NO published default row — restore keeps it in lockstep with bare.
default_for() {  # default_for <model> <kind>
    case "$1:$2" in
        opus:in)        echo 20000000 ;;
        opus:out)       echo 2000000  ;;
        opus:rpm)       echo 2000     ;;
        deepseek:in)    echo 40000    ;;
        deepseek:out)   echo 12000    ;;
        deepseek:total) echo 52000    ;;
        gpt-oss:in)     echo 40000    ;;
        gpt-oss:out)    echo 12000    ;;
        gpt-oss:total)  echo 52000    ;;
        *)              echo "?"      ;;
    esac
}

# Published per-MTok prices for the --force trade print (primary citations: doc §1).
price_in() {
    case "$1" in
        opus)     echo 5.00 ;;
        deepseek) echo 0.56 ;;
        gpt-oss)  echo 0.09 ;;
    esac
}
price_out() {
    case "$1" in
        opus)     echo 25.00 ;;
        deepseek) echo 1.68  ;;
        gpt-oss)  echo 0.36  ;;
    esac
}

usage() {
    cat <<EOF
usage: vertex-cap.sh <subcommand> [args] [--dry-run] [--force]

subcommands:
  list                              show every quotaPreference on ${PROJECT}:
                                    preferred vs granted vs reconciling, plus recorded defaults
  set <model> <in_tpm> <out_tpm> [rpm]
                                    retune a model's clamps (model: opus | deepseek | gpt-oss)
                                    - opus writes BOTH base_model slugs (bare + 4-8, re-key belt)
                                    - deepseek/gpt-oss also PATCH total = in + out
                                    - INCREASES fire plain; DECREASES need --force (prints the
                                      worst-case-\$/day trade, attaches ignoreSafetyChecks)
  restore <model>                   un-clamp: PATCH back to Google's recorded defaults
                                    (an increase — fires plain)

flags:
  --dry-run   print the exact curl commands; ZERO network calls (list included)
  --force     required for any decrease; prints the trade before firing

the spike workflow:
  vertex-cap.sh set opus 3000 1000        # bump for a burst
  ...work...
  vertex-cap.sh set opus 1500 500 --force # back down to the ruling values
  # or: vertex-cap.sh restore opus        # remove the brake entirely (Google defaults)

Derivation math + posture ruling: src/rnd/v0.1.9/2026.07.15-vertex-quota-clamp-prep.md
Audit trail: src/tmp/vertex-cap-audit.log (appended on every invocation)
EOF
}

die() { echo "vertex-cap: ERROR: $*" >&2; exit 1; }

audit() {  # audit <line>
    mkdir -p "$( dirname "${AUDIT_LOG}" )"
    echo "$( date -Is ) | $*" >> "${AUDIT_LOG}"
}

token() { gcloud auth print-access-token; }

# Worst-case \$/day for (model, in_tpm, out_tpm): (in*p_in + out*p_out)/1e6 * 1440
worst_case_per_day() {  # worst_case_per_day <model> <in_tpm> <out_tpm>
    python3 -c "print( f'{ ( ${2} * $( price_in "$1" ) + ${3} * $( price_out "$1" ) ) / 1e6 * 1440 :.2f}' )"
}

# ---------------------------------------------------------------------------
# REST helpers. Every mutating call goes through upsert_pref, which is the ONLY
# place a write URL is constructed — one choke point to eyeball.
# ---------------------------------------------------------------------------
pref_body() {  # pref_body <quota_id> <dimension_value> <preferred_value>
    python3 - "$1" "$2" "$3" "${JUSTIFICATION}" "${CONTACT_EMAIL}" <<'PYEOF'
import json, sys

quota_id, base_model, value, justification, email = sys.argv[1:6]
print( json.dumps( {
    "service"      : "aiplatform.googleapis.com",
    "quotaId"      : quota_id,
    "quotaConfig"  : { "preferredValue": value },
    "dimensions"   : { "base_model": base_model },
    "justification": justification,
    "contactEmail" : email,
} ) )
PYEOF
}

upsert_pref() {  # upsert_pref <pref_id> <quota_id> <dimension_value> <value> <with_safety:true|false>
    local pref_id="$1" quota_id="$2" dim="$3" value="$4" with_safety="$5"
    local qs=""
    if [ "${with_safety}" = "true" ]; then
        qs="?ignoreSafetyChecks=QUOTA_DECREASE_PERCENTAGE_TOO_HIGH&ignoreSafetyChecks=QUOTA_DECREASE_BELOW_USAGE"
    fi
    local body
    body="$( pref_body "${quota_id}" "${dim}" "${value}" )"

    local patch_url="${API}/${PARENT}/quotaPreferences/${pref_id}${qs}"
    local post_qs="${qs/\?/\&}"
    local post_url="${API}/${PARENT}/quotaPreferences?quotaPreferenceId=${pref_id}${post_qs}"

    if ${DRY_RUN}; then
        echo "DRY-RUN would PATCH: ${pref_id} -> ${value}  (${quota_id} [base_model=${dim}])"
        echo "  curl -sS -X PATCH '${patch_url}' \\"
        echo "    -H \"Authorization: Bearer \$( gcloud auth print-access-token )\" \\"
        echo "    -H 'Content-Type: application/json' -d '${body}'"
        echo "  # fallback iff PATCH returns 404 (preference not yet created):"
        echo "  # curl -sS -X POST '${post_url}' -H <same headers> -d '<same body>'"
        return 0
    fi

    local resp_file
    resp_file="$( mktemp /tmp/vertex-cap-resp.XXXXXX.json )"
    local http_code
    http_code="$( curl -sS -o "${resp_file}" -w '%{http_code}' -X PATCH "${patch_url}" \
        -H "Authorization: Bearer $( token )" \
        -H "Content-Type: application/json" -d "${body}" )"
    if [ "${http_code}" = "404" ]; then
        http_code="$( curl -sS -o "${resp_file}" -w '%{http_code}' -X POST "${post_url}" \
            -H "Authorization: Bearer $( token )" \
            -H "Content-Type: application/json" -d "${body}" )"
    fi
    if [ "${http_code}" != "200" ]; then
        echo "vertex-cap: ${pref_id}: HTTP ${http_code}" >&2
        cat "${resp_file}" >&2
        rm -f "${resp_file}"
        return 1
    fi
    rm -f "${resp_file}"
    echo "OK ${pref_id} -> ${value}"
}

current_pref_value() {  # current_pref_value <pref_id>  (live only; empty if not found)
    curl -sS -H "Authorization: Bearer $( token )" \
        "${API}/${PARENT}/quotaPreferences/$1" 2>/dev/null \
      | python3 -c "
import json, sys
try:
    print( json.load( sys.stdin ).get( 'quotaConfig', {} ).get( 'preferredValue', '' ) )
except Exception:
    print( '' )
"
}

# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------
cmd_list() {
    local url="${API}/${PARENT}/quotaPreferences"
    if ${DRY_RUN}; then
        echo "DRY-RUN would GET: ${url}"
        echo "  curl -sS -H \"Authorization: Bearer \$( gcloud auth print-access-token )\" '${url}'"
        audit "list | dry_run=true"
        return 0
    fi
    curl -sS -H "Authorization: Bearer $( token )" "${url}" | python3 -c "
import json, sys

prefs = json.load( sys.stdin ).get( 'quotaPreferences', [] )
# Recorded defaults, keyed (quotaId, base_model) — clamp-prep doc §0 + §3.1.
defaults = {
    ( 'GlobalOpenapiInputTokensPerMinutePerBaseModel',  'deepseek-v3.2-maas' ): '40000',
    ( 'GlobalOpenapiOutputTokensPerMinutePerBaseModel', 'deepseek-v3.2-maas' ): '12000',
    ( 'GlobalOpenapiTotalTokensPerMinutePerBaseModel',  'deepseek-v3.2-maas' ): '52000',
    ( 'GlobalOpenapiInputTokensPerMinutePerBaseModel',  'gpt-oss-120b-maas' ): '40000',
    ( 'GlobalOpenapiOutputTokensPerMinutePerBaseModel', 'gpt-oss-120b-maas' ): '12000',
    ( 'GlobalOpenapiTotalTokensPerMinutePerBaseModel',  'gpt-oss-120b-maas' ): '52000',
    ( 'GlobalOnlinePredictionInputTokensPerMinutePerBaseModel',        'anthropic-claude-opus' ): '20000000',
    ( 'GlobalOnlinePredictionOutputTokensPerMinutePerBaseModel',       'anthropic-claude-opus' ): '2000000',
    ( 'GlobalOnlinePredictionRequestsPerMinutePerProjectPerBaseModel', 'anthropic-claude-opus' ): '2000',
    ( 'GlobalOnlinePredictionInputTokensPerMinutePerBaseModel',        'anthropic-claude-opus-4-8' ): 'unpublished',
    ( 'GlobalOnlinePredictionOutputTokensPerMinutePerBaseModel',       'anthropic-claude-opus-4-8' ): 'unpublished',
    ( 'GlobalOnlinePredictionRequestsPerMinutePerProjectPerBaseModel', 'anthropic-claude-opus-4-8' ): 'unpublished',
}
fmt = '{:<32} {:<58} {:<28} {:>12} {:>12} {:<11} {:>12}'
print( fmt.format( 'NAME', 'QUOTA_ID', 'BASE_MODEL', 'PREFERRED', 'GRANTED', 'RECONCILING', 'DEFAULT' ) )
for p in sorted( prefs, key=lambda x: x.get( 'name', '' ) ):
    name = p.get( 'name', '' ).rsplit( '/', 1 )[-1]
    qid  = p.get( 'quotaId', '' )
    bm   = p.get( 'dimensions', {} ).get( 'base_model', '-' )
    cfg  = p.get( 'quotaConfig', {} )
    print( fmt.format( name, qid, bm,
                       cfg.get( 'preferredValue', '-' ), cfg.get( 'grantedValue', '-' ),
                       str( p.get( 'reconciling', False ) ),
                       defaults.get( ( qid, bm ), '?' ) ) )
"
    audit "list | dry_run=false"
}

cmd_set() {  # cmd_set <model> <in> <out> [rpm]
    local model="${1:-}" in_tpm="${2:-}" out_tpm="${3:-}" rpm="${4:-}"
    if [ -z "${model}" ] || [ -z "${in_tpm}" ] || [ -z "${out_tpm}" ]; then
        usage
        die "set needs <model> <in_tpm> <out_tpm> [rpm]"
    fi
    model_rows "${model}" > /dev/null 2>&1 || die "unknown model '${model}' (opus | deepseek | gpt-oss)"
    [[ "${in_tpm}"  =~ ^[0-9]+$ ]] || die "in_tpm must be a positive integer, got '${in_tpm}'"
    [[ "${out_tpm}" =~ ^[0-9]+$ ]] || die "out_tpm must be a positive integer, got '${out_tpm}'"
    if [ -n "${rpm}" ]; then
        [[ "${rpm}" =~ ^[0-9]+$ ]] || die "rpm must be a positive integer, got '${rpm}'"
        [ "${model}" = "opus" ]    || die "rpm belt exists only for opus (MaaS models have no RPM clamp)"
    fi

    local total=$(( in_tpm + out_tpm ))
    local changes=""

    # Decrease detection: live mode compares against the CURRENT preferred value; a
    # decrease without --force aborts before any write. Dry-run cannot read current
    # values (zero network calls), so it notes how the live run will behave instead.
    local any_decrease=false
    if ! ${DRY_RUN}; then
        while IFS='|' read -r pref qid dim kind; do
            local new_val=""
            case "${kind}" in
                in)    new_val="${in_tpm}"  ;;
                out)   new_val="${out_tpm}" ;;
                total) new_val="${total}"   ;;
                rpm)   if [ -n "${rpm}" ]; then new_val="${rpm}"; else continue; fi ;;
            esac
            local cur
            cur="$( current_pref_value "${pref}" )"
            if [ -n "${cur}" ] && [ "${new_val}" -lt "${cur}" ]; then
                any_decrease=true
                changes="${changes}${pref}: ${cur} -> ${new_val} (DECREASE); "
            else
                changes="${changes}${pref}: ${cur:-unset} -> ${new_val}; "
            fi
        done < <( model_rows "${model}" )
    fi

    # The trade print — always shown under --force (the operator is about to tighten
    # a live brake): what the NEW values bound worst-case spend to, and who feels it.
    if ${FORCE}; then
        echo "== THE TRADE (--force decrease) =="
        echo "   ${model} at ${in_tpm} in / ${out_tpm} out tok/min bounds worst-case spend to"
        echo "   \$$( worst_case_per_day "${model}" "${in_tpm}" "${out_tpm}" )/day (saturated every minute; derivation: clamp-prep doc §2)."
        echo "   Any consumer above these rates starts seeing 429s BY DESIGN."
        echo "   ignoreSafetyChecks attached: QUOTA_DECREASE_PERCENTAGE_TOO_HIGH, QUOTA_DECREASE_BELOW_USAGE."
    fi
    if ! ${DRY_RUN} && ${any_decrease} && ! ${FORCE}; then
        echo "vertex-cap: decrease detected without --force:" >&2
        echo "  ${changes}" >&2
        echo "  Re-run with --force to accept the trade (it will be printed before firing)." >&2
        exit 1
    fi
    if ${DRY_RUN} && ! ${FORCE}; then
        echo "NOTE (dry-run): live decreases will be refused without --force — by this script"
        echo "AND by the Cloud Quotas safety rail (whose refusal carries the live usage meter)."
    fi

    while IFS='|' read -r pref qid dim kind; do
        local new_val=""
        case "${kind}" in
            in)    new_val="${in_tpm}"  ;;
            out)   new_val="${out_tpm}" ;;
            total) new_val="${total}"   ;;
            rpm)   if [ -n "${rpm}" ]; then new_val="${rpm}"; else continue; fi ;;
        esac
        upsert_pref "${pref}" "${qid}" "${dim}" "${new_val}" "${FORCE}"
    done < <( model_rows "${model}" )

    audit "set ${model} in=${in_tpm} out=${out_tpm} rpm=${rpm:--} | ${changes:-dry-run} | force=${FORCE} | dry_run=${DRY_RUN}"
}

cmd_restore() {  # cmd_restore <model>
    local model="${1:-}"
    if [ -z "${model}" ]; then
        usage
        die "restore needs <model>"
    fi
    model_rows "${model}" > /dev/null 2>&1 || die "unknown model '${model}' (opus | deepseek | gpt-oss)"

    echo "Restoring ${model} clamps to Google's recorded defaults (un-clamp; increase — fires plain)."
    echo "To return to the RULING values instead: vertex-cap.sh set ${model} <in> <out> --force"

    while IFS='|' read -r pref qid dim kind; do
        local target
        target="$( default_for "${model}" "${kind}" )"
        [ "${target}" != "?" ] || continue
        upsert_pref "${pref}" "${qid}" "${dim}" "${target}" "false"
    done < <( model_rows "${model}" )

    audit "restore ${model} -> defaults | dry_run=${DRY_RUN}"
}

# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------
POSITIONAL=()
for arg in "$@"; do
    case "${arg}" in
        --dry-run) DRY_RUN=true ;;
        --force)   FORCE=true   ;;
        -h|--help) usage; exit 0 ;;
        --*)       die "unknown flag '${arg}'" ;;
        *)         POSITIONAL+=( "${arg}" ) ;;
    esac
done
if [ ${#POSITIONAL[@]} -lt 1 ]; then
    usage
    exit 1
fi

case "${POSITIONAL[0]}" in
    list)    cmd_list ;;
    set)     cmd_set     "${POSITIONAL[@]:1}" ;;
    restore) cmd_restore "${POSITIONAL[@]:1}" ;;
    *)       usage; die "unknown subcommand '${POSITIONAL[0]}'" ;;
esac
