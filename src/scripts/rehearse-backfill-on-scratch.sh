#!/usr/bin/env bash
# Prove backfill_missing_question_vectors.py on a throwaway Postgres database, then drop it.
#
# Steps: dump the schema of three tables from lupin_db_dev (schema only, no rows), create
# lupin_db_scratch_vectors from it, seed six fixture asks, run the script five ways inside the
# lupin-rest-dev container (dry run, wrong database, rehearsal, apply, second apply), check each
# result with psql, and drop the scratch database. Exit 0 only when every check holds.
#
# It never writes to lupin_db_dev or lupin_db_test: those two are read by pg_dump only.
# Prerequisites: docker, containers lupin-postgres and lupin-rest-dev running, run from any tree.
# Rollback: the EXIT trap drops the scratch database and removes the files copied into the container.
#
# Usage: src/scripts/rehearse-backfill-on-scratch.sh 2>&1 | tee <log path>

set -u
HERE="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SCRIPT="$HERE/backfill_missing_question_vectors.py"
SCRATCH_DB="lupin_db_scratch_vectors"
WORK="$( mktemp -d )"
PG="docker exec -i lupin-postgres"
APP="docker exec -e PYTHONPATH=/var/lupin/src -e LUPIN_ROOT=/var/lupin lupin-rest-dev"
FAILED=0

cleanup() {
    $PG psql -U lupin_dev -d postgres -c "DROP DATABASE IF EXISTS $SCRATCH_DB" > /dev/null 2>&1
    docker exec lupin-rest-dev rm -rf /tmp/scratchvec > /dev/null 2>&1
    rm -rf "$WORK"
    echo "cleanup: scratch database dropped, still present: $( $PG psql -U lupin_dev -d postgres -Atc "select count(*) from pg_database where datname='$SCRATCH_DB'" )"
}
trap cleanup EXIT

check() {   # check <label> <expected> <actual>
    if [ "$2" == "$3" ]; then echo "PASS  $1 ( $3 )"; else echo "FAIL  $1: expected '$2', got '$3'"; FAILED=1; fi
}
scratch() { $PG psql -U lupin_app -d "$SCRATCH_DB" -Atc "$1"; }
runner() { $APP python3 /tmp/scratchvec/runner.py "$@" 2>&1; }

echo "== $( date -u +%FT%TZ ) scratch rehearsal of $( basename "$SCRIPT" ), sha256 $( sha256sum "$SCRIPT" | cut -c1-12 )"
if [ "$( $PG psql -U lupin_dev -d postgres -Atc "select count(*) from pg_database where datname='$SCRATCH_DB'" )" != "0" ]; then
    echo "REFUSED: $SCRATCH_DB already exists; drop it by hand first"; trap - EXIT; exit 2
fi

echo "== create the scratch database from a schema-only dump"
$PG psql -U lupin_dev -d postgres -c "CREATE DATABASE $SCRATCH_DB OWNER lupin_app" | tail -1
$PG psql -U lupin_dev -d "$SCRATCH_DB" -c "CREATE EXTENSION IF NOT EXISTS vector" | tail -1
$PG pg_dump -U lupin_dev -d lupin_db_dev -s --no-owner --no-privileges -t notifications -t prediction_log -t prediction_decisions > "$WORK/schema.sql"
# the foreign key to users fails by design: users is not copied
$PG psql -U lupin_app -d "$SCRATCH_DB" < "$WORK/schema.sql" 2>&1 | grep ERROR | sed 's/^/expected: /'

echo "== seed six fixture asks"
python3 - "$WORK" <<'EOF'
import json, sys, uuid
work = sys.argv[ 1 ]
def vec( seed ):
    value = 20.0 / ( 768 ** 0.5 )
    return [ round( value + seed * 1e-4, 6 ) ] * 768
ids  = { key: str( uuid.uuid4() ) for key in ( "a1", "a2", "a3", "b1", "b2", "by" ) }
user = str( uuid.uuid4() )
old  = "[" + ",".join( [ "0.1" ] * 768 ) + "]"
sql  = []
def ask( key, message, response_type, actual, source, has_row, question=None ):
    value = json.dumps( { "source": source } ) if source else "{}"
    sql.append( f"INSERT INTO notifications (id,sender_id,recipient_id,title,message,type,priority,responded_at,response_value,state) VALUES ('{ids[ key ]}','s','{user}','t',$m${message}$m$,'ask','high','2026-09-01 10:00:00+00','{value}','responded');" )
    sql.append( f"INSERT INTO prediction_log (notification_id,response_type,category,prediction_strategy,actual_value) VALUES ('{ids[ key ]}','{response_type}','cat','s','{json.dumps( actual )}');" )
    if has_row: sql.append( f"INSERT INTO prediction_decisions (id,question,question_embedding,answer_source) VALUES ('{ids[ key ]}',$m${question or message.strip()}$m$,'{old}','human');" )
ask( "a1", "  First?  ",   "yes_no",          { "value": "yes" },                "ui", False )
ask( "a2", "Pick one",    "multiple_choice", { "answers": { "Q": "A" } },       None, False )
ask( "a3", "Third?",      "yes_no",          { "value": "no" },                 "ui", False )
ask( "b1", "Fourth?",     "yes_no",          { "value": "yes" },                "ui", True, question="stale text" )
ask( "b2", "Fifth?",      "multiple_choice", { "answers": { "Z": "Y" } },       "ui", True )
ask( "by", "Bystander?",  "yes_no",          { "value": "yes" },                "ui", True )
open( f"{work}/seed.sql", "w" ).write( "\n".join( sql ) + "\n" )
order  = [ "a1", "a2", "a3", "b1", "b2" ]
header = { "kind": "header", "model": "scratch-model", "revision": "rev-scratch-1", "count": 5 }
lines  = [ json.dumps( header ) ] + [ json.dumps( { "id": ids[ key ], "model": "scratch-model", "revision": "rev-scratch-1", "vector": vec( index ) } ) for index, key in enumerate( order ) ]
open( f"{work}/side.jsonl", "w" ).write( "\n".join( lines ) + "\n" )
open( f"{work}/insert_ids.txt", "w" ).write( "\n".join( ids[ key ] for key in ( "a1", "a2", "a3" ) ) + "\n" )
open( f"{work}/runner.py", "w" ).write( '''import importlib.util, sys
import sqlalchemy as sa
from cosa.rest.db.database import get_database_url
spec = importlib.util.spec_from_file_location( "bf", "/tmp/scratchvec/backfill_missing_question_vectors.py" )
bf   = importlib.util.module_from_spec( spec ); sys.modules[ "bf" ] = bf; spec.loader.exec_module( bf )
url  = sa.engine.make_url( get_database_url() ).set( database="lupin_db_scratch_vectors" ).render_as_string( hide_password=False )
sys.exit( bf.main( [ "--side-file", "/tmp/scratchvec/side.jsonl", "--database-url", url ] + sys.argv[ 1: ] ) )
''' )
EOF
$PG psql -U lupin_app -d "$SCRATCH_DB" < "$WORK/seed.sql" | sort | uniq -c
docker exec lupin-rest-dev mkdir -p /tmp/scratchvec
docker cp "$SCRIPT" lupin-rest-dev:/tmp/scratchvec/backfill_missing_question_vectors.py
for f in side.jsonl insert_ids.txt runner.py; do docker cp "$WORK/$f" lupin-rest-dev:/tmp/scratchvec/$f; done
EXPECT="--expect-insert 3 --expect-update 2 --expect-log 5 --expect-insert-ids /tmp/scratchvec/insert_ids.txt"

echo "== 1 dry run: nothing written"
runner | tail -8
check "dry run leaves 3 case rows" 3 "$( scratch 'select count(*) from prediction_decisions' )"
check "dry run stamps nothing" 0 "$( scratch 'select count(*) from prediction_log where encoder_version is not null' )"

echo "== 2 wrong database name: refused"
OUT="$( runner --apply $EXPECT --expect-database lupin_db_dev )"; echo "$OUT" | tail -2
check "wrong database refused" 1 "$( echo "$OUT" | grep -c "REFUSED: connected to" )"
check "refusal leaves 3 case rows" 3 "$( scratch 'select count(*) from prediction_decisions' )"

echo "== 3 rehearsal: every step, then rollback"
OUT="$( runner --rehearse $EXPECT --expect-database $SCRATCH_DB )"; echo "$OUT" | tail -2
check "rehearsal read back 5 rows" 1 "$( echo "$OUT" | grep -c '"rows": 5' )"
check "rehearsal left 3 case rows" 3 "$( scratch 'select count(*) from prediction_decisions' )"
check "rehearsal stamped nothing" 0 "$( scratch 'select count(*) from prediction_log where encoder_version is not null' )"

echo "== 4 apply"
OUT="$( runner --apply $EXPECT --expect-database $SCRATCH_DB )"; echo "$OUT" | tail -2
check "apply read back clean" 1 "$( echo "$OUT" | grep -c 'applied and read back' )"
check "6 case rows (3 inserted, 2 replaced, 1 bystander)" 6 "$( scratch 'select count(*) from prediction_decisions' )"
check "5 log rows stamped" 5 "$( scratch 'select count(*) from prediction_log where encoder_version is not null' )"
check "one encoder version" 1 "$( scratch 'select count(distinct encoder_version) from prediction_log where encoder_version is not null' )"
check "bystander log row not stamped" 0 "$( scratch "select count(*) from prediction_log l join prediction_decisions d on d.id=l.notification_id::text where d.question='Bystander?' and l.encoder_version is not null" )"
check "6 distinct 768-wide vectors" "6|6" "$( scratch 'select count(*) filter (where vector_dims(question_embedding)=768) || chr(124) || count(distinct question_embedding::text) from prediction_decisions' )"
check "answer sources human|unknown" "human:5,unknown:1" "$( scratch "select string_agg(answer_source || ':' || n, ',' order by answer_source) from (select answer_source, count(*) n from prediction_decisions group by 1) t" )"

echo "== 5 second apply: the inserted ids now have a row, so it must roll back"
OUT="$( runner --apply $EXPECT --expect-database $SCRATCH_DB )"; echo "$OUT" | tail -1
check "second apply rolled back" 1 "$( echo "$OUT" | grep -c 'ROLLED BACK: insert ids differ' )"
check "second apply left 6 case rows" 6 "$( scratch 'select count(*) from prediction_decisions' )"

echo "== lupin_db_dev and lupin_db_test were read by pg_dump only"
if [ "$FAILED" == "0" ]; then echo "RESULT: all checks passed"; else echo "RESULT: at least one check failed"; fi
exit $FAILED
