#!/usr/bin/env python3
"""
Step 13 of the brain-integration plan — dump the solution cache, with receipts.

Plan of record: src/rnd/v0.2.0/2026.08.21-step13-cache-dump-plan.md (row 1e597a65).
This tool is PREP: it does nothing destructive unless --apply is passed, and it
runs only on Cheech's explicit GO after plan steps 9a + 9b have merged.

Parameterised on the three scope questions so the GO just picks values:
  --db {dev,test,both}        which database(s) — lupin_db_dev (:7999) / lupin_db_test (:8000)
  --synonyms / --no-synonyms  canonical_synonyms too (default ON — ruled 2026-08-21 11:39)
  --adjacent-caches           the five adjacent caches too (default OFF — ruled OUT)

Per database, in order: pg_dump backup of the in-scope tables → counts before →
one DELETE-per-table transaction → counts after → JSON receipts. DELETE, not
TRUNCATE (truncate takes ACCESS EXCLUSIVE and blocks every live reader).

Verification (the plan's two halves): --verify-empty re-counts every in-scope
table with a FRESH psql call after the delete transaction has returned — never
the transaction's own 'after' row, which is pre-commit (Pocholo, review of
0e6d3b33) — and fails on any non-zero; --verify-learn-back asks one question
through /api/v2/ask and proves the cache still LEARNS — a snapshot row appeared,
it passes 9a (non-blank user_id, a routed command), and a second ask RE-RUNS
rather than replays (9b's guard holds on the fresh, unconfirmed row).

The learn-back check WAITS for that first ask to actually finish. On the agent path
/api/v2/ask answers `status: "waiting"` with a job_id and the snapshot is written when
the queued job completes, so reading the answer off the immediate HTTP body reports
failures against a working system (row 004c94ec). It polls the done/dead queues for the
job, bounded by --learn-back-timeout, and fails LOUD and BY NAME on a timeout — "the
answer never arrived" is reported as a timeout, never as "the system is broken". Only
once the fresh row is read back does it fire the second ask; with no row established, 9b
is reported UNTESTED rather than passed.

DRY-RUN IS THE DEFAULT AND TOUCHES NOTHING LIVE: counts only — no pg_dump, no
DELETE, and no HTTP (the learn-back logs in and asks a question that WRITES a
snapshot, so it runs only under --apply; without --apply it is described, not
sent).

Dry-run (default):
    python3 src/scripts/dump_solution_cache.py --db both
Apply, on the GO:
    python3 src/scripts/dump_solution_cache.py --db both --apply --verify-empty
Apply + learn-back check against the dev server (single --db):
    python3 src/scripts/dump_solution_cache.py --db dev --apply --verify-empty --verify-learn-back --base-url http://localhost:7999
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:  # pragma: no cover — unreachable in-process: importing this module requires LUPIN_ROOT to be set, so by the time any in-process test can call it the guard is already false
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )
import cosa.utils.util as cu

PG_CONTAINER     = "lupin-postgres"
PG_USER          = "lupin_dev"
DB_BY_TARGET     = {
    "dev"  : "lupin_db_dev",
    "test" : "lupin_db_test",
}
SNAPSHOT_TABLE   = "solution_snapshots"
SYNONYM_TABLE    = "canonical_synonyms"
ADJACENT_TABLES  = [ "gist_cache", "question_embeddings", "embedding_cache", "query_log", "input_and_output" ]

# How long the learn-back check waits for a QUEUED first ask to finish, and how often it
# looks. The agent path answers "waiting" and finishes behind the CJ Flow queue, so a
# check that does not wait can only ever pass on a path that answers inline (row 004c94ec).
DEFAULT_LEARN_BACK_TIMEOUT_S = 120
DEFAULT_LEARN_BACK_POLL_S    = 2


def databases_for( target ):
    """
    Resolve the --db choice to the database names it covers.

    Requires:
        - target is one of "dev", "test", "both"

    Ensures:
        - returns a list of database names, dev first when both
        - raises ValueError on any other target (never guesses a database)
    """
    if target == "both": return [ DB_BY_TARGET[ "dev" ], DB_BY_TARGET[ "test" ] ]
    if target in DB_BY_TARGET: return [ DB_BY_TARGET[ target ] ]
    raise ValueError( f"unknown --db target {target!r}; expected dev, test or both" )


def tables_for( include_synonyms, include_adjacent ):
    """
    Resolve the two table flags to the in-scope table list.

    Requires:
        - include_synonyms and include_adjacent are booleans

    Ensures:
        - solution_snapshots is always first
        - canonical_synonyms follows iff include_synonyms
        - the five adjacent caches follow iff include_adjacent, in ADJACENT_TABLES order
    """
    tables = [ SNAPSHOT_TABLE ]
    if include_synonyms: tables.append( SYNONYM_TABLE )
    if include_adjacent: tables.extend( ADJACENT_TABLES )
    return tables


def psql_argv( db, sql=None, variables=None ):
    """
    Build the docker-exec psql argv for one SQL statement.

    Two shapes, chosen by whether the SQL carries parameters:
      · no variables → `-c sql` (sql is the last argv element)
      · variables    → `-v name=value` per parameter and `-f -`, and the CALLER
        pipes the SQL on stdin (run_argv(..., stdin=sql)), referencing each
        parameter as :'name', which psql quotes as a SQL literal. This is the
        only way: psql performs NO variable interpolation inside `-c` (measured
        live: "syntax error at or near ':'"), so the value is never spliced into
        the statement and never reaches the statement through -c either.

    Requires:
        - db is a database name
        - without variables: sql is a non-empty string
        - with variables: {name: value}; sql is NOT part of the argv

    Ensures:
        - returns the argv list (no shell), unaligned tuples-only output so
          count rows parse as "a|b|c"
        - ON_ERROR_STOP=1 on every call: a failed statement makes psql exit 3
          instead of running on, so a half-done transaction can never be
          reported as success (Pocholo, review of c298ca02)
        - with variables the argv ends with `-f -` and `docker exec` carries `-i`
          so stdin reaches psql
    """
    argv = [ "docker", "exec" ] + ( [ "-i" ] if variables else [ ] ) + [ PG_CONTAINER, "psql", "-U", PG_USER, "-d", db, "-At", "-v", "ON_ERROR_STOP=1" ]
    if variables:
        for name, value in variables.items():
            argv.extend( [ "-v", f"{name}={value}" ] )
        argv.extend( [ "-f", "-" ] )
    else:
        argv.extend( [ "-c", sql ] )
    return argv


def pg_dump_argv( db, tables ):
    """
    Build the docker-exec pg_dump argv for the in-scope tables of one database.

    Requires:
        - db is a database name; tables is a non-empty list

    Ensures:
        - returns the argv list with one -t per table, in order
    """
    argv = [ "docker", "exec", PG_CONTAINER, "pg_dump", "-U", PG_USER, "-d", db ]
    for t in tables: argv.extend( [ "-t", t ] )
    return argv


def count_sql( tables ):
    """
    One SELECT returning one pipe-separated row of counts, in table order.

    Requires:
        - tables is a non-empty list of table names

    Ensures:
        - returns "SELECT (SELECT count(*) FROM a), (SELECT count(*) FROM b);"
    """
    parts = ", ".join( f"(SELECT count(*) FROM {t})" for t in tables )
    return f"SELECT {parts};"


def delete_sql( tables ):
    """
    One transaction that deletes every in-scope table, counts printed either side.

    Requires:
        - tables is a non-empty list of table names

    Ensures:
        - BEGIN … DELETE FROM each table … COMMIT, with a 'before' and an 'after'
          count row so the psql output carries both
        - uses DELETE, never TRUNCATE
    """
    parts   = ", ".join( f"(SELECT count(*) FROM {t})" for t in tables )
    deletes = " ".join( f"DELETE FROM {t};" for t in tables )
    return f"BEGIN; SELECT 'before', {parts}; {deletes} SELECT 'after', {parts}; COMMIT;"


def run_argv( argv, runner=subprocess.run, stdin=None ):
    """
    Run one argv and return its stdout, failing loudly on a non-zero exit.

    Requires:
        - argv is a list; runner has subprocess.run's signature
        - stdin, if given, is text piped to the process (the parameterised psql shape)

    Ensures:
        - returns stdout as str
        - raises RuntimeError naming the argv and stderr on non-zero exit
    """
    proc = runner( argv, capture_output=True, text=True, input=stdin )
    if proc.returncode != 0:
        raise RuntimeError( f"command failed ({proc.returncode}): {' '.join( argv )}\n{proc.stderr}" )
    return proc.stdout


def parse_count_row( line, tables ):
    """
    Turn one psql -At row ("3|3" or "before|3|3") into {table: count}.

    Requires:
        - line is a pipe-separated row whose LAST len(tables) fields are integers

    Ensures:
        - returns a dict keyed by table, in order
        - raises ValueError if the field count is short or a field is not an int
    """
    fields = line.strip().split( "|" )
    if len( fields ) < len( tables ):
        raise ValueError( f"count row {line!r} has {len( fields )} fields, expected at least {len( tables )}" )
    values = fields[ -len( tables ): ]
    return { t: int( v ) for t, v in zip( tables, values ) }


def count_rows( db, tables, runner=subprocess.run ):
    """
    Count every in-scope table in one database.

    Requires:
        - db is a database name; tables non-empty

    Ensures:
        - returns {table: count}
    """
    out   = run_argv( psql_argv( db, count_sql( tables ) ), runner=runner )
    lines = [ l for l in out.splitlines() if l.strip() ]
    return parse_count_row( lines[ 0 ], tables )


def backup( db, tables, backup_dir, now, runner=subprocess.run ):
    """
    pg_dump the in-scope tables of one database to a timestamped file.

    Requires:
        - backup_dir is a writable directory path (created if absent)
        - now is a datetime

    Ensures:
        - returns the backup file path; file holds pg_dump's stdout
        - raises RuntimeError if pg_dump fails (nothing is written then)
    """
    os.makedirs( backup_dir, exist_ok=True )
    ts   = now.strftime( "%Y.%m.%d-at-%H%M%S" )
    path = os.path.join( backup_dir, f"cache-backup-{db}-{ts}.sql" )
    out  = run_argv( pg_dump_argv( db, tables ), runner=runner )
    with open( path, "w" ) as f:
        f.write( out )
    return path


def dump( db, tables, runner=subprocess.run ):
    """
    Delete every in-scope table of one database inside one transaction.

    Requires:
        - a backup has already been taken by the caller

    Ensures:
        - returns ( before, after ) count dicts parsed from the transaction's own
          'before' / 'after' rows — the 'after' row is read INSIDE the transaction,
          i.e. pre-commit; callers that need proof of the committed state must
          re-count with count_rows() after this returns (main() does)
        - raises RuntimeError if psql fails (the transaction then rolled back)
        - raises ValueError if the output lacks both rows
    """
    out   = run_argv( psql_argv( db, delete_sql( tables ) ), runner=runner )
    rows  = { }
    for line in out.splitlines():
        if line.startswith( "before|" ): rows[ "before" ] = parse_count_row( line, tables )
        if line.startswith( "after|" ):  rows[ "after" ]  = parse_count_row( line, tables )
    if "before" not in rows or "after" not in rows:
        raise ValueError( f"dump output for {db} lacked a before/after row:\n{out}" )
    return rows[ "before" ], rows[ "after" ]


def verify_empty( after ):
    """
    The plan's first verification half: every in-scope count reads 0.

    Requires:
        - after is {table: count} from an INDEPENDENT read taken after the delete
          transaction returned (count_rows), not the transaction's own 'after' row

    Ensures:
        - returns the list of tables that are NOT empty (empty list == pass)
    """
    return [ t for t, n in after.items() if n != 0 ]


def latest_snapshot_row( db, id_hash, runner=subprocess.run ):
    """
    Fetch the 9a-relevant columns of one snapshot row by id_hash.

    Requires:
        - id_hash is the snapshot_id the ask returned

    Ensures:
        - returns {"id_hash", "user_id", "routing_command", "answer_is_correct"}
          with empty strings for NULLs
        - raises ValueError if no row came back
    """
    # id_hash travels as a psql variable (-v) and is quoted by psql as :'id_hash'; the
    # SQL goes on stdin because -c never interpolates — the value is never spliced
    # into the statement (Pocholo, review of c298ca02).
    sql = ( "SELECT id_hash, coalesce(user_id,''), coalesce(routing_command,''), coalesce(answer_is_correct,'') "
            f"FROM {SNAPSHOT_TABLE} WHERE id_hash = :'id_hash';" )
    out   = run_argv( psql_argv( db, variables={ "id_hash": id_hash } ), runner=runner, stdin=sql )
    lines = [ l for l in out.splitlines() if l.strip() ]
    if not lines:
        raise ValueError( f"no {SNAPSHOT_TABLE} row with id_hash {id_hash!r} in {db}" )
    f = lines[ 0 ].split( "|" )
    return { "id_hash": f[ 0 ], "user_id": f[ 1 ], "routing_command": f[ 2 ], "answer_is_correct": f[ 3 ] }


def queue_jobs( base_url, token, queue_name, http ):
    """
    Read one named queue's job metadata list.

    Requires:
        - queue_name is one of the queues /api/get-queue serves ("done", "dead", ...)
        - http has requests' get(url, headers=, timeout=) signature

    Ensures:
        - returns the "<queue_name>_jobs_metadata" list (empty list when absent)
        - raises RuntimeError on a non-200
    """
    resp = http.get( f"{base_url}/api/get-queue/{queue_name}",
                     headers={ "Authorization": f"Bearer {token}" }, timeout=30 )
    if resp.status_code != 200:
        raise RuntimeError( f"/api/get-queue/{queue_name} failed: {resp.status_code} {resp.text}" )
    return resp.json().get( f"{queue_name}_jobs_metadata", [ ] )


def probe_job_terminal( base_url, token, job_id, http ):
    """
    One look for a queued job in a TERMINAL queue.

    Requires:
        - job_id is the id the ask returned for the queued work

    Ensures:
        - returns ( "done", job ) or ( "dead", job ) the first time the job appears
          in either terminal queue, done checked first
        - returns None while it is still in flight — that is "not arrived yet", NOT
          a verdict about the system
    """
    for queue_name in ( "done", "dead" ):
        for job in queue_jobs( base_url, token, queue_name, http ):
            if job.get( "job_id" ) == job_id: return ( queue_name, job )
    return None


def snapshot_ids( db, runner=subprocess.run ):
    """
    Every id_hash currently in the snapshot table.

    Ensures:
        - returns a set of id_hash strings (empty set on an empty table)
    """
    out = run_argv( psql_argv( db, f"SELECT id_hash FROM {SNAPSHOT_TABLE};" ), runner=runner )
    return { l.strip() for l in out.splitlines() if l.strip() }


def poll_until( probe, timeout_s, interval_s, sleep=time.sleep, clock=time.monotonic ):
    """
    Call probe() until it answers truthy or the budget runs out.

    Requires:
        - probe is a zero-argument callable; timeout_s / interval_s are seconds
        - sleep / clock are injection seams (tests pass a fake clock; nothing sleeps)

    Ensures:
        - probe() is called at least once, even with timeout_s == 0
        - returns the first truthy result, or None when the budget expired
        - never sleeps after the last attempt
    """
    deadline = clock() + timeout_s
    while True:
        result = probe()
        if result: return result
        if clock() >= deadline: return None
        sleep( interval_s )


def login( base_url, email, password, http ):
    """
    Log in and return the bearer token.

    Requires:
        - http has requests' post(url, json=, timeout=) signature

    Ensures:
        - returns tokens.access_token
        - raises RuntimeError on a non-200
    """
    resp = http.post( f"{base_url}/auth/login", json={ "email": email, "password": password }, timeout=10 )
    if resp.status_code != 200:
        raise RuntimeError( f"login failed: {resp.status_code} {resp.text}" )
    return resp.json()[ "tokens" ][ "access_token" ]


def ask_v2( base_url, token, question, http ):
    """
    POST one question to /api/v2/ask and return the AskResponse dict.

    Ensures:
        - returns the JSON body
        - raises RuntimeError on a non-200
    """
    resp = http.post( f"{base_url}/api/v2/ask", json={ "question": question },
                      headers={ "Authorization": f"Bearer {token}" }, timeout=180 )
    if resp.status_code != 200:
        raise RuntimeError( f"/api/v2/ask failed: {resp.status_code} {resp.text}" )
    return resp.json()


def settle_first_ask( first, db, base_url, token, before_ids, http, runner=subprocess.run,
                      timeout_s=DEFAULT_LEARN_BACK_TIMEOUT_S, interval_s=DEFAULT_LEARN_BACK_POLL_S,
                      sleep=time.sleep, clock=time.monotonic ):
    """
    Wait for the first ask to actually FINISH, then name the snapshot row it wrote.

    THE DEFECT THIS EXISTS TO KILL (row 004c94ec): /api/v2/ask answers INLINE only on
    the paths that run the work on the request thread. On the agent path — the common
    one — it answers `status: "waiting"` with a job_id, the work goes to the CJ Flow
    queue, and the snapshot is written when the job finishes. Reading wrote_snapshot /
    answer / snapshot_id off that immediate body reports three failures against a
    system that is working correctly. So this waits, bounded, and keeps "the answer
    has not arrived yet" separate from "the system is broken":
      · still in flight        → keep polling (no verdict)
      · budget expired         → a failure that SAYS it timed out, not that it broke
      · landed in the dead queue → a failure that names the job's own error
      · finished with no fresh row → the cache genuinely did not learn

    Requires:
        - first is the AskResponse body; before_ids is snapshot_ids(db) taken BEFORE
          the ask, so a row can be proven FRESH rather than merely present
        - sleep / clock are injection seams

    Ensures:
        - returns ( snapshot_id_or_None, failures, receipt )
        - snapshot_id is None whenever the ask could not be settled — the caller must
          then treat 9b as untested rather than as passed
        - never raises for a failed criterion; raises only on transport/psql errors
    """
    status   = first.get( "status" )
    failures = [ ]
    receipt  = { "status": status, "mode": None, "job_id": first.get( "job_id" ), "terminal": None, "fresh_ids": [ ] }

    if status == "done":
        receipt[ "mode" ] = "inline"
        if not first.get( "wrote_snapshot" ): failures.append( "first ask finished inline without writing a snapshot" )
        if not first.get( "answer" ):         failures.append( "first ask finished inline with no answer" )
        snapshot_id = first.get( "snapshot_id" )
        if not snapshot_id:                   failures.append( "first ask finished inline with no snapshot_id" )
        return snapshot_id, failures, receipt

    if status != "waiting":
        receipt[ "mode" ] = "unusable"
        failures.append( f"first ask returned status {status!r} — neither an inline answer nor a queued job" )
        return None, failures, receipt

    receipt[ "mode" ] = "queued"
    job_id = first.get( "job_id" )
    if not job_id:
        failures.append( "first ask was queued but returned no job_id — the check has nothing to wait for" )
        return None, failures, receipt

    terminal = poll_until( lambda: probe_job_terminal( base_url, token, job_id, http ),
                           timeout_s, interval_s, sleep=sleep, clock=clock )
    if terminal is None:
        receipt[ "terminal" ] = "timeout"
        failures.append( f"TIMED OUT after {timeout_s}s waiting for queued job {job_id} to reach done or dead — "
                         "the answer never arrived; this is NOT evidence the system is broken" )
        return None, failures, receipt

    queue_name, job = terminal
    receipt[ "terminal" ] = queue_name
    if queue_name == "dead":
        failures.append( f"queued job {job_id} died before answering: {job.get( 'error' )}" )
        return None, failures, receipt
    if not job.get( "response_text" ):
        failures.append( f"queued job {job_id} finished with no answer" )

    fresh = poll_until( lambda: sorted( snapshot_ids( db, runner=runner ) - before_ids ),
                        timeout_s, interval_s, sleep=sleep, clock=clock )
    if not fresh:
        failures.append( "the job finished but no new snapshot row appeared — the cache did not learn" )
        return None, failures, receipt

    receipt[ "fresh_ids" ] = fresh
    if len( fresh ) != 1:
        failures.append( f"cannot attribute a snapshot row to this ask — {len( fresh )} new rows appeared ({fresh}); "
                         "the check will not guess which one it wrote" )
        return None, failures, receipt
    return fresh[ 0 ], failures, receipt


def verify_learn_back( db, base_url, email, password, question, http, runner=subprocess.run,
                       timeout_s=DEFAULT_LEARN_BACK_TIMEOUT_S, interval_s=DEFAULT_LEARN_BACK_POLL_S,
                       sleep=time.sleep, clock=time.monotonic ):
    """
    The plan's second verification half: the emptied cache still LEARNS, and 9b holds.

    ORDER IS PART OF THE CHECK, not an implementation detail. The second ask fires only
    AFTER the first ask's row has been proven to exist and read back — a second ask sent
    while the first one is still queued cannot fail to "not replay", so a pass would
    prove nothing (row 004c94ec). No row established ⇒ 9b is reported UNTESTED, never
    passed.

    Requires:
        - the dump has already run against db; base_url serves that db
        - http is the requests module (or a stand-in) with post() AND get()

    Ensures:
        - returns a receipts dict: the first ask's own fields, how it settled, the fresh
          row's user_id/routing_command/answer_is_correct, the second ask's path/cache_hit
          (or None when 9b was not testable), and a list of `failures` (empty == pass)
        - never raises on a failed CRITERION — failures are listed; raises only on
          transport/auth errors (RuntimeError) or a missing row (ValueError)
    """
    token      = login( base_url, email, password, http )
    before_ids = snapshot_ids( db, runner=runner )
    first      = ask_v2( base_url, token, question, http )
    failures   = [ ]
    if first.get( "path" ) == "replay": failures.append( "first ask replayed — cache was not empty" )

    snapshot_id, settle_failures, settle = settle_first_ask(
        first, db, base_url, token, before_ids, http, runner=runner,
        timeout_s=timeout_s, interval_s=interval_s, sleep=sleep, clock=clock )
    failures.extend( settle_failures )

    row    = { }
    second = { }
    if snapshot_id:
        row = latest_snapshot_row( db, snapshot_id, runner=runner )     # the row EXISTS — proven before 9b is tested
        if not row[ "user_id" ]:                              failures.append( "fresh row has blank user_id (fails 9a)" )
        if not row[ "routing_command" ]:                      failures.append( "fresh row has no routing_command (fails 9a)" )
        if row[ "answer_is_correct" ].lower() == "true":      failures.append( "fresh row already confirmed True — guard would serve it" )
        second = ask_v2( base_url, token, question, http )
        if second.get( "cache_hit" ) or second.get( "path" ) == "replay":
            failures.append( "second ask replayed an unconfirmed row (fails 9b)" )
    else:
        failures.append( "9b NOT TESTED — no fresh row was established, so a second ask would prove nothing" )

    return {
        "question"       : question,
        "first_ask"      : { k: first.get( k ) for k in ( "path", "status", "wrote_snapshot", "snapshot_id", "job_id", "trace_id" ) },
        "settled"        : settle,
        "fresh_row"      : row,
        "second_ask"     : { k: second.get( k ) for k in ( "path", "status", "cache_hit", "trace_id" ) } if second else None,
        "failures"       : failures,
    }


def build_parser():
    """
    The CLI surface — every scope question is a flag, defaults follow the 2026-08-21 ruling.

    Ensures:
        - returns an argparse parser; nothing is parsed here
    """
    p = argparse.ArgumentParser( description="Step 13: dump the solution cache with backup + receipts (dry-run by default)." )
    p.add_argument( "--db", required=True, choices=[ "dev", "test", "both" ], help="which database(s) to dump" )
    syn = p.add_mutually_exclusive_group()
    syn.add_argument( "--synonyms",    dest="synonyms", action="store_true",  help="include canonical_synonyms (default)" )
    syn.add_argument( "--no-synonyms", dest="synonyms", action="store_false", help="leave canonical_synonyms alone" )
    p.set_defaults( synonyms=True )
    p.add_argument( "--adjacent-caches", action="store_true", help="ALSO dump gist_cache, question_embeddings, embedding_cache, query_log, input_and_output (ruled OUT — off by default)" )
    p.add_argument( "--apply", action="store_true", help="actually back up + delete (default: dry-run, counts only)" )
    p.add_argument( "--backup-dir", default=os.path.join( cu.get_project_root(), "io", "cache-dump-backups" ) )
    p.add_argument( "--verify-empty", action="store_true", help="after --apply, re-count with a fresh psql call and fail if any in-scope count is not 0" )
    p.add_argument( "--verify-learn-back", action="store_true", help="with --apply: ask one question through /api/v2/ask, WAIT for it to finish (the agent path answers 'waiting' and completes behind the queue), and prove the cache still learns + 9b holds (single --db only; writes a snapshot, so it never runs in dry-run)" )
    p.add_argument( "--base-url", default="http://localhost:7999" )
    p.add_argument( "--question", default="What time is it right now?" )
    p.add_argument( "--learn-back-timeout", type=int, default=DEFAULT_LEARN_BACK_TIMEOUT_S,
                    help=f"seconds to wait for a QUEUED first ask to reach done/dead before failing as a timeout (default {DEFAULT_LEARN_BACK_TIMEOUT_S})" )
    p.add_argument( "--learn-back-poll", type=int, default=DEFAULT_LEARN_BACK_POLL_S,
                    help=f"seconds between polls while waiting (default {DEFAULT_LEARN_BACK_POLL_S})" )
    return p


def main( argv=None, runner=subprocess.run, http=None, now=None, out=print ):
    """
    Entry point. Dry-run unless --apply; receipts printed as JSON on the last line.

    Requires:
        - argv is a list of CLI args or None (sys.argv)
        - runner / http / now / out are injection seams for tests

    Ensures:
        - returns 0 on success, 2 when a verification failed
        - without --apply: ONLY count queries run — no pg_dump, no DELETE, no HTTP
        - with --apply + --verify-empty: the verdict comes from a fresh count_rows()
          call made after the delete transaction returned, never the tx's own row
        - raises on transport/psql errors (nothing is swallowed)
    """
    args   = build_parser().parse_args( argv )
    now    = now or datetime.datetime.now()
    tables = tables_for( args.synonyms, args.adjacent_caches )
    dbs    = databases_for( args.db )
    mode   = "APPLY" if args.apply else "DRY-RUN"
    out( f"[{mode}] databases={dbs} tables={tables}" )

    if args.verify_learn_back and len( dbs ) != 1:
        raise SystemExit( "--verify-learn-back needs a single --db (dev or test), not both" )

    receipts = { "mode": mode, "tables": tables, "databases": { } }
    rc       = 0
    for db in dbs:
        entry  = { }
        before = count_rows( db, tables, runner=runner )
        entry[ "before" ] = before
        out( f"  {db}: before {before}" )
        if args.apply:
            entry[ "backup" ] = backup( db, tables, args.backup_dir, now, runner=runner )
            out( f"  {db}: backup -> {entry[ 'backup' ]}" )
            tx_before, tx_after = dump( db, tables, runner=runner )
            entry[ "tx_before" ] = tx_before
            entry[ "tx_after" ]  = tx_after     # the transaction's own row — pre-commit, kept for the record, not trusted
            after = count_rows( db, tables, runner=runner )   # independent read AFTER the transaction returned
            entry[ "after" ] = after
            out( f"  {db}: after  {after} (fresh count; tx row said {tx_after})" )
            if args.verify_empty:
                leftover = verify_empty( after )
                entry[ "verify_empty" ] = "pass" if not leftover else f"FAIL: not empty {leftover}"
                if leftover: rc = 2
                out( f"  {db}: verify-empty {entry[ 'verify_empty' ]}" )
        else:
            out( f"  {db}: would back up {tables} to {args.backup_dir} then DELETE (re-run with --apply)" )
        if args.verify_learn_back and not args.apply:
            out( f"  {db}: DRY-RUN — would log in and ask {args.question!r} through /api/v2/ask (writes a snapshot); nothing sent. Learn-back runs only with --apply." )
            entry[ "learn_back" ] = "skipped: dry-run"
        elif args.verify_learn_back:
            if http is None:
                import requests as http
            email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
            password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
            if not email or not password:
                raise SystemExit( "set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD for --verify-learn-back" )
            lb = verify_learn_back( db, args.base_url, email, password, args.question, http, runner=runner,
                                    timeout_s=args.learn_back_timeout, interval_s=args.learn_back_poll )
            entry[ "learn_back" ] = lb
            if lb[ "failures" ]: rc = 2
            out( f"  {db}: learn-back {'pass' if not lb[ 'failures' ] else 'FAIL: ' + '; '.join( lb[ 'failures' ] )}" )
        receipts[ "databases" ][ db ] = entry

    out( json.dumps( receipts, indent=2, default=str ) )
    return rc


if __name__ == "__main__":
    sys.exit( main() )
