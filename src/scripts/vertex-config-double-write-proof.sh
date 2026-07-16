#!/usr/bin/env bash
#
# vertex-config-double-write-proof.sh — OSQ C-4 double-write proof (store cda7bf8b leg 4).
#
# THE CLAIM UNDER TEST: §4d's "setPublisherModelConfig is retry-safe by construction"
# was an INFERENCE from a gap in the schema (no updateMask ⇒ full-object SET ⇒ a
# repeat of the same payload should be a no-op). Now that a config EXISTS on
# the sandbox project (LRO 847218789178146816), the claim is PROVABLE:
#   read config → re-POST the IDENTICAL object → poll the LRO to done →
#   assert no error → read back → diff unchanged.
#
# BUILD, DO NOT RUN (executor: Mr. Radio / Rick):
#   - Default mode is --dry-run-implied: with no --execute flag this script only
#     prints what it would do. The live path requires BOTH --execute AND the
#     endpoint env vars below — it cannot fire by accident.
#   - The endpoint is PARAMETERIZED, not invented: the exact
#     setPublisherModelConfig URL + read-back URL come from the applied write in
#     the manager's record (memento / part-1 receipts). This script fails LOUD
#     if they are unset rather than guessing a URL shape.
#
# CLOBBER GUARD INTEGRATION (leg 5): before ANY live write, the payload is piped
# through vertex_publisher_config_guard.py against the just-read live config.
# For the double-write proof the payload IS the live config, so the guard must
# pass trivially — if it does not, something upstream is broken; stop.
#
# Required env (live mode only):
#   VERTEX_SET_CONFIG_URL   — full :setPublisherModelConfig POST URL (from the applied write)
#   VERTEX_GET_CONFIG_URL   — full read-back GET URL (from the applied write)
#
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
GUARD="${SCRIPT_DIR}/vertex_publisher_config_guard.py"
POLL_INTERVAL_SECONDS=10
POLL_MAX_ATTEMPTS=30

EXECUTE=false
for arg in "$@"; do
    case "${arg}" in
        --execute) EXECUTE=true ;;
        -h|--help)
            sed -n '2,30p' "${BASH_SOURCE[0]}"
            exit 0
            ;;
        *) echo "double-write-proof: unknown arg '${arg}' (only --execute exists)" >&2; exit 1 ;;
    esac
done

token() { gcloud auth print-access-token; }

if ! ${EXECUTE}; then
    cat <<'EOF'
DRY (default — no network calls). The live sequence, in order:

  1. READ  : curl -sS -H "Authorization: Bearer $( gcloud auth print-access-token )" \
               "${VERTEX_GET_CONFIG_URL}" > /tmp/dwp-live-config.json
  2. GUARD : python3 vertex_publisher_config_guard.py \
               --live /tmp/dwp-live-config.json --candidate /tmp/dwp-live-config.json
             (payload IS the live config — guard must trivially ALLOW; abort if not)
  3. WRITE : curl -sS -H "Authorization: Bearer ..." -H 'Content-Type: application/json' \
               -d "{\"publisherModelConfig\": $( cat /tmp/dwp-live-config.json )}" \
               "${VERTEX_SET_CONFIG_URL}" > /tmp/dwp-lro.json
  4. POLL  : GET the LRO name from /tmp/dwp-lro.json every 10s (max 30 attempts)
             until done=true; assert HTTP 200 and NO .error field.
  5. VERIFY: re-GET the config; python-diff against /tmp/dwp-live-config.json;
             assert UNCHANGED. Unchanged read-back + clean LRO = the §4d
             retry-safety claim is PROVEN, not inferred.

To run live: set VERTEX_SET_CONFIG_URL + VERTEX_GET_CONFIG_URL (from the applied
write's record — this script deliberately does not guess URL shapes), then re-run
with --execute. Executor: Mr. Radio / Rick only.
EOF
    exit 0
fi

# ---------------------------------------------------------------------------
# LIVE PATH (executor-only)
# ---------------------------------------------------------------------------
: "${VERTEX_SET_CONFIG_URL:?double-write-proof: VERTEX_SET_CONFIG_URL unset — take it from the applied write's record; this script does not guess URLs}"
: "${VERTEX_GET_CONFIG_URL:?double-write-proof: VERTEX_GET_CONFIG_URL unset — take it from the applied write's record; this script does not guess URLs}"
[ -f "${GUARD}" ] || { echo "double-write-proof: guard not found at ${GUARD}" >&2; exit 1; }

echo "[1/5] READ live config"
curl -sS -f -H "Authorization: Bearer $( token )" "${VERTEX_GET_CONFIG_URL}" > /tmp/dwp-live-config.json

echo "[2/5] GUARD (identity payload — must trivially ALLOW)"
python3 "${GUARD}" --live /tmp/dwp-live-config.json --candidate /tmp/dwp-live-config.json

echo "[3/5] WRITE identical config (the double-write)"
printf '{"publisherModelConfig": %s}' "$( cat /tmp/dwp-live-config.json )" > /tmp/dwp-payload.json
curl -sS -f -H "Authorization: Bearer $( token )" -H "Content-Type: application/json" \
    -d @/tmp/dwp-payload.json "${VERTEX_SET_CONFIG_URL}" > /tmp/dwp-lro.json
LRO_NAME="$( python3 -c "import json; print( json.load( open( '/tmp/dwp-lro.json' ) ).get( 'name', '' ) )" )"
[ -n "${LRO_NAME}" ] || { echo "double-write-proof: write returned no LRO name:" >&2; cat /tmp/dwp-lro.json >&2; exit 1; }

echo "[4/5] POLL LRO ${LRO_NAME}"
LRO_BASE="$( echo "${VERTEX_SET_CONFIG_URL}" | python3 -c "import sys, urllib.parse; u = urllib.parse.urlparse( sys.stdin.read().strip() ); print( f'{u.scheme}://{u.netloc}' )" )"
attempt=0
while :; do
    attempt=$(( attempt + 1 ))
    curl -sS -f -H "Authorization: Bearer $( token )" "${LRO_BASE}/v1beta1/${LRO_NAME}" > /tmp/dwp-lro-status.json
    if python3 -c "
import json, sys
lro = json.load( open( '/tmp/dwp-lro-status.json' ) )
if lro.get( 'error' ):
    print( f'LRO ERROR: {lro[ \"error\" ]}' ); sys.exit( 2 )
sys.exit( 0 if lro.get( 'done' ) else 1 )
"; then
        echo "  LRO done, no error (attempt ${attempt})"
        break
    else
        rc=$?
        [ "${rc}" = "2" ] && { echo "double-write-proof: LRO carries an error" >&2; exit 1; }
        [ "${attempt}" -ge "${POLL_MAX_ATTEMPTS}" ] && { echo "double-write-proof: LRO not done after $(( POLL_INTERVAL_SECONDS * POLL_MAX_ATTEMPTS ))s — INDETERMINATE, not passing" >&2; exit 1; }
        sleep "${POLL_INTERVAL_SECONDS}"
    fi
done

echo "[5/5] VERIFY read-back unchanged"
curl -sS -f -H "Authorization: Bearer $( token )" "${VERTEX_GET_CONFIG_URL}" > /tmp/dwp-after-config.json
python3 -c "
import json, sys
before = json.load( open( '/tmp/dwp-live-config.json' ) )
after  = json.load( open( '/tmp/dwp-after-config.json' ) )
if before == after:
    print( 'PROOF COMPLETE: identical double-write left the config byte-equal — §4d retry-safety is PROVEN, not inferred.' )
    sys.exit( 0 )
print( 'PROOF FAILED: read-back differs after identical double-write:' )
print( json.dumps( { 'before': before, 'after': after }, indent=2 ) )
sys.exit( 1 )
"
