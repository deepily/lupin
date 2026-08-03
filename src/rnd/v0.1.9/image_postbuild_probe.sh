#!/usr/bin/env bash
# image_postbuild_probe.sh — MANDATORY pre-push app-image probe (Mr. Radio doctrine, 2026-07-07).
#
# WHY: docker-compose bind-mounts ./src over /var/lupin/src on dev+test, so the
# integration gate validates HOST code and NEVER the baked image. GCP Cloud Run
# has no mount → it runs the BAKED image. This probe verifies the baked artifact
# carries the postgres cutover, catching a stale re-tag before it ships.
# (Origin: the 1.2.1-pgvector re-tag of 5-day-old a87d3219 — deps green, baked
#  code missing today's cutover 0901984d. Clayton, task c845346a.)
#
# Usage:  image_postbuild_probe.sh <image-ref>
#   <image-ref> = a tag (lupin:1.2.1-pgvector-fullbuild) OR a repo@sha256:... digest.
# Exit 0 iff every check passes. Read-only: docker run --rm, no mutations.

set -u
IMG="${1:?usage: image_postbuild_probe.sh <image-ref>}"
INI="/var/lupin/src/conf/lupin-app.ini"
MIGDIR_GLOB="/var/lupin/src/cosa/rest/db/migrations/versions /var/lupin/src/migrations/versions"
CUTOVER_MIGRATION="e1f2a3b4c5d6"

pass=0; fail=0
check() { # <name> <0|1 ok> <detail>
  if [ "$2" -eq 0 ]; then printf "  [PASS] %-42s : %s\n" "$1" "$3"; pass=$((pass+1));
  else printf "  [FAIL] %-42s : %s\n" "$1" "$3"; fail=$((fail+1)); fi
}

echo "=== image post-build probe :: ${IMG} ==="

# 0. Build recency — a real rebuild is NOT days old.
created="$( docker inspect --format '{{.Created}}' "$IMG" 2>/dev/null )"
check "image created timestamp" 0 "${created:-unknown} (verify TODAY build, not a stale re-tag)"

# 1. LAYER 1 — deps import (no app config needed).
if docker run --rm --entrypoint python "$IMG" -c \
   "import pgvector; from pgvector.sqlalchemy import Vector; import psycopg2; import sqlalchemy" >/dev/null 2>&1; then
  check "deps: pgvector/Vector/psycopg2/sqlalchemy" 0 "all import"
else
  check "deps: pgvector/Vector/psycopg2/sqlalchemy" 1 "an import FAILED"
fi

# 2. LAYER 2a — baked code carries the postgres-backend resolver.
if [ -n "$( docker run --rm --entrypoint grep "$IMG" -rl 'def is_postgres_backend' /var/lupin/src/cosa 2>/dev/null )" ]; then
  check "baked: is_postgres_backend present" 0 "found in /var/lupin/src/cosa"
else
  check "baked: is_postgres_backend present" 1 "ABSENT — image predates the cutover"
fi

# 3. LAYER 2b — baked INI selects the postgres backend.
ini_line="$( docker run --rm --entrypoint grep "$IMG" -iE '^vector store backend' "$INI" 2>/dev/null )"
if echo "$ini_line" | grep -qi 'postgres'; then
  check "baked INI: vector store backend=postgres" 0 "$( echo "$ini_line" | tr -s ' ' )"
else
  check "baked INI: vector store backend=postgres" 1 "key absent or != postgres (got: '${ini_line:-none}')"
fi

# 4. LAYER 2c — exact-scan cutover migration is baked in (path moved across builds; probe both).
mig_found=""
for d in $MIGDIR_GLOB; do
  hit="$( docker run --rm --entrypoint sh "$IMG" -c "ls $d 2>/dev/null | grep -i $CUTOVER_MIGRATION" 2>/dev/null )"
  [ -n "$hit" ] && { mig_found="$d :: $hit"; break; }
done
if [ -n "$mig_found" ]; then
  check "baked migration ${CUTOVER_MIGRATION} present" 0 "$mig_found"
else
  check "baked migration ${CUTOVER_MIGRATION} present" 1 "ABSENT — drop-HNSW migration not baked"
fi

# 5. LAYER 2d — the resolver returns 'postgres' with the RUNTIME-CORRECT relative
# config env (project convention: config paths are /src-relative, combined with
# LUPIN_ROOT at runtime — as docker-compose sets them). Proves the CODE is right.
RELENV="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"
backend="$( docker run --rm -e LUPIN_CONFIG_MGR_CLI_ARGS="$RELENV" --entrypoint python "$IMG" -c \
  "from cosa.rest.db.repositories.vector_store_backend import get_vector_store_backend; print('PROBE_RESULT='+str(get_vector_store_backend()))" 2>/dev/null | sed -n 's/^PROBE_RESULT=//p' )"
if [ "$backend" = "postgres" ]; then
  check "resolver (correct env) -> postgres" 0 "code resolves 'postgres'"
else
  check "resolver (correct env) -> postgres" 1 "returns '${backend:-<error/import-fail>}' (want postgres)"
fi

# 6. LAYER 2e — BAKED-ENV boot check: run the resolver with the image's OWN baked
# LUPIN_CONFIG_MGR_CLI_ARGS (what GCP Cloud Run uses — no compose override there).
# An absolute config_path in the Dockerfile ENV doubles (/var/lupin/var/lupin/...)
# and fails boot. This is masked in dev/test by the compose env override.
baked="$( docker run --rm --entrypoint python "$IMG" -c \
  "from cosa.rest.db.repositories.vector_store_backend import get_vector_store_backend; print('PROBE_RESULT='+str(get_vector_store_backend()))" 2>/dev/null | sed -n 's/^PROBE_RESULT=//p' )"
if [ "$baked" = "postgres" ]; then
  check "resolver (BAKED env) -> postgres [GCP]" 0 "baked env boots clean"
else
  check "resolver (BAKED env) -> postgres [GCP]" 1 "baked env FAILS (got '${baked:-<boot-error>}') — GCP must override LUPIN_CONFIG_MGR_CLI_ARGS with /src-relative paths OR fix Dockerfile ENV"
fi

echo "=== $( [ $fail -eq 0 ] && echo GREEN || echo RED ) : ${pass} pass / ${fail} fail ==="
[ $fail -eq 0 ]
