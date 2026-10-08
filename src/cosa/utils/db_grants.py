"""
The expected privilege matrix of the three database roles, and a read-only check of it.

The matrix below is the one place that says who may do what to which table. `init-db-roles.sql`
grants the same thing; a unit test reads that file and fails when the two disagree. The check asks
Postgres, with `has_table_privilege` and `has_database_privilege`, so it runs as any login, a
plain one included, and changes nothing.

A database with no public tables fails the check: a zero is "nothing was checked", not "all good".
"""

import re
import shlex
import sys
import traceback

APP_ROLE   = "lupin_app"
HOST_ROLE  = "lupin_host"
TEST_ROLE  = "lupin_test"
DEV_DB     = "lupin_db_dev"
TEST_DB    = "lupin_db_test"

GUARDED_TABLE = "approval_settings"
ALL_PRIVILEGES = ( "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER" )
HOST_PRIVILEGES = ( "SELECT", "INSERT", "UPDATE", "DELETE" )
HOST_BARRED     = ( "INSERT", "UPDATE", "DELETE", "TRUNCATE" )

# ( database, role, privilege, scope, table, expected ). scope is "all" tables, "only" the named one,
# or "except" the named one. expected False means the role must NOT hold the privilege.
TABLE_RULES = tuple(
    [ ( DEV_DB,  APP_ROLE,  p, "all",    "",            True ) for p in ALL_PRIVILEGES ]
  + [ ( DEV_DB,  HOST_ROLE, p, "except", GUARDED_TABLE, True ) for p in HOST_PRIVILEGES ]
  + [ ( DEV_DB,  HOST_ROLE, "SELECT", "only", GUARDED_TABLE, True ) ]
  + [ ( DEV_DB,  HOST_ROLE, p, "only",   GUARDED_TABLE, False ) for p in HOST_BARRED ]
  + [ ( TEST_DB, APP_ROLE,  p, "all",    "",            True ) for p in ALL_PRIVILEGES ]
  + [ ( TEST_DB, TEST_ROLE, p, "all",    "",            True ) for p in ALL_PRIVILEGES ]
)

SEQUENCE_PRIVILEGES = ( "USAGE", "SELECT", "UPDATE" )

# ( database, role, privilege ): every public sequence must grant it. A table with a serial column cannot take
# an insert without it, so a gap here fails as "permission denied for sequence" and not as a missing table grant.
SEQUENCE_RULES = tuple(
    [ ( DEV_DB,  APP_ROLE,  p ) for p in SEQUENCE_PRIVILEGES ]
  + [ ( DEV_DB,  HOST_ROLE, p ) for p in SEQUENCE_PRIVILEGES ]
  + [ ( TEST_DB, APP_ROLE,  p ) for p in SEQUENCE_PRIVILEGES ]
  + [ ( TEST_DB, TEST_ROLE, p ) for p in SEQUENCE_PRIVILEGES ]
)

# ( database, role, expected ): may the role CONNECT to the database
CONNECT_RULES = (
    ( DEV_DB,  APP_ROLE,  True ), ( DEV_DB,  HOST_ROLE, True ), ( DEV_DB,  TEST_ROLE, False ),
    ( TEST_DB, APP_ROLE,  True ), ( TEST_DB, TEST_ROLE, True ), ( TEST_DB, HOST_ROLE, False ),
)

_SAFE = re.compile( r"^[a-z_]*$" )


def databases():
    """The databases the matrix describes, in a fixed order."""
    return ( DEV_DB, TEST_DB )


def roles_of( database ):
    """The roles the matrix names for one database."""
    return sorted( { r[ 1 ] for r in TABLE_RULES if r[ 0 ] == database } | { r[ 1 ] for r in CONNECT_RULES if r[ 0 ] == database }
                   | { r[ 1 ] for r in SEQUENCE_RULES if r[ 0 ] == database } )


def build_check_sql( database ):
    """
    The read-only query that lists what is wrong in one database.

    Requires:
        - database is named in the matrix

    Ensures:
        - every output row is `database|kind|role|object|privilege`, kind one of tables, norole,
          missing, unexpected; the tables row carries the count of public tables in the object column
        - the query reads catalogs and calls has_*_privilege only
    """
    assert database in databases(), f"no privilege matrix for {database}"
    values = ",\n    ".join(
        f"( '{role}', '{priv}', '{scope}', '{table}', {str( expected ).lower()} )"
        for db, role, priv, scope, table, expected in TABLE_RULES if db == database )
    connects = ",\n    ".join( f"( '{role}', {str( expected ).lower()} )" for db, role, expected in CONNECT_RULES if db == database )
    sequences = ",\n    ".join( f"( '{role}', '{priv.lower()}' )" for db, role, priv in SEQUENCE_RULES if db == database )
    for word in [ r[ 1 ] for r in TABLE_RULES ] + [ r[ 2 ] for r in TABLE_RULES ] + [ r[ 4 ] for r in TABLE_RULES ] + [ r[ 1 ] for r in SEQUENCE_RULES ]:
        assert _SAFE.match( word.lower() ), f"unsafe word in the matrix: {word!r}"
    return f"""WITH wanted( role, priv, scope, tname, expected ) AS ( VALUES
    {values}
), connects( role, expected ) AS ( VALUES
    {connects}
), wanted_seq( role, priv ) AS ( VALUES
    {sequences}
), tabs AS (
  SELECT c.oid, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public' AND c.relkind IN ( 'r', 'p' )
), seqs AS (
  SELECT c.oid, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public' AND c.relkind = 'S'
), present AS ( SELECT rolname FROM pg_roles )
SELECT current_database() || '|tables||' || count(*) || '|' FROM tabs
UNION ALL
SELECT current_database() || '|norole|' || r.role || '||' FROM ( SELECT DISTINCT role FROM wanted UNION SELECT role FROM connects UNION SELECT role FROM wanted_seq ) r
 WHERE r.role NOT IN ( SELECT rolname FROM present )
UNION ALL
SELECT current_database() || '|' || CASE WHEN w.expected THEN 'missing' ELSE 'unexpected' END || '|' || w.role || '|' || t.relname || '|' || w.priv
  FROM wanted w
  JOIN tabs t ON w.scope = 'all' OR ( w.scope = 'only' AND t.relname = w.tname ) OR ( w.scope = 'except' AND t.relname <> w.tname )
 WHERE CASE WHEN w.role IN ( SELECT rolname FROM present ) THEN has_table_privilege( w.role, t.oid, w.priv ) <> w.expected ELSE false END
UNION ALL
SELECT current_database() || '|missing|' || q.role || '|' || s.relname || '|' || upper( q.priv )
  FROM wanted_seq q CROSS JOIN seqs s
 WHERE CASE WHEN q.role IN ( SELECT rolname FROM present ) THEN NOT has_sequence_privilege( q.role, s.oid, q.priv ) ELSE false END
UNION ALL
SELECT current_database() || '|' || CASE WHEN k.expected THEN 'missing' ELSE 'unexpected' END || '|' || k.role || '|' || current_database() || '|CONNECT'
  FROM connects k
 WHERE CASE WHEN k.role IN ( SELECT rolname FROM present ) THEN has_database_privilege( k.role, current_database(), 'CONNECT' ) <> k.expected ELSE false END
ORDER BY 1;
"""


def parse_rows( text ):
    """
    Split the check's output into rows.

    Ensures:
        - returns a list of ( database, kind, role, object, privilege ) tuples, blank lines skipped
    Raises:
        - ValueError naming the line when it does not have five fields
    """
    rows = []
    for line in text.splitlines():
        if not line.strip(): continue
        fields = line.strip().split( "|" )
        if len( fields ) != 5: raise ValueError( f"the check printed a line that is not a result row: {line!r}" )
        rows.append( tuple( fields ) )
    return rows


def evaluate( database, rows ):
    """
    Turn one database's rows into a report.

    Requires:
        - rows are the parsed rows of build_check_sql( database )

    Ensures:
        - returns { database, tables, roles, problems, ok }; problems is a list of
          ( kind, role, object, privilege ) and ok is True only when it is empty
        - zero public tables is a problem of kind empty, never a pass
    Raises:
        - ValueError when the rows hold no tables row for the database, since nothing was checked
    """
    mine   = [ r for r in rows if r[ 0 ] == database ]
    counts = [ r for r in mine if r[ 1 ] == "tables" ]
    if len( counts ) != 1: raise ValueError( f"{database}: the check returned no table count, so nothing was checked" )
    tables   = int( counts[ 0 ][ 3 ] )
    problems = [ ( r[ 1 ], r[ 2 ], r[ 3 ], r[ 4 ] ) for r in mine if r[ 1 ] != "tables" ]
    if tables == 0: problems.insert( 0, ( "empty", "", database, "" ) )
    return { "database": database, "tables": tables, "roles": len( roles_of( database ) ), "problems": problems, "ok": not problems }


_VERBS = {
    "missing"    : lambda role, obj, priv: f"{role} cannot {priv} {obj}",
    "unexpected" : lambda role, obj, priv: f"{role} can {priv} {obj} and must not",
    "norole"     : lambda role, obj, priv: f"role {role} does not exist",
    "empty"      : lambda role, obj, priv: f"{obj} has no public tables, so nothing was checked",
}


def _grouped( problems ):
    """One ( kind, role, object, "P1, P2" ) per kind, role and object, keeping first-seen order."""
    order, privileges = [], {}
    for kind, role, obj, priv in problems:
        key = ( kind, role, obj )
        if key not in privileges: order.append( key ); privileges[ key ] = []
        privileges[ key ].append( priv )
    return [ ( kind, role, obj, ", ".join( p for p in privileges[ ( kind, role, obj ) ] if p ) ) for kind, role, obj in order ]


def format_report( reports, remedy, limit=None ):
    """
    The lines the check prints.

    Ensures:
        - one summary line per database, `name: N tables, K roles, M problems`, then one line per problem
        - with limit, the problems of each database are grouped by role and object and cut after limit lines, with
          a line saying how many more there are, so a database with no grants at all does not flood a log
        - when any database has a problem, the last line is the remedy
    """
    lines = []
    for report in reports:
        lines.append( f"{report[ 'database' ]}: {report[ 'tables' ]} tables, {report[ 'roles' ]} roles, {len( report[ 'problems' ] )} problems" )
        problems = report[ "problems" ] if limit is None else _grouped( report[ "problems" ] )
        shown    = problems if limit is None else problems[ :limit ]
        lines += [ "  " + _VERBS[ kind ]( role, obj, priv ) for kind, role, obj, priv in shown ]
        if len( shown ) < len( problems ): lines.append( f"  ... and {len( problems ) - len( shown )} more; run db_roles --check for the full list" )
    if not all( report[ "ok" ] for report in reports ): lines.append( remedy )
    return lines


def remedy_for( psql_command, reports ):
    """
    The one command that repairs what the reports found.

    Ensures:
        - a missing role needs the full provisioning, which needs the password files, so the line says so
        - anything else is the grants-only run
    """
    if any( kind == "norole" for report in reports for kind, *_ in report[ "problems" ] ):
        return "remedy: a role is missing; run the full provisioning (db_roles with the three password files), which needs root"
    return f"remedy: python -m cosa.utils.db_roles --psql {shlex.quote( psql_command )} --grants-only --apply"


def check_with_psql( psql_command, run_fn, which=None ):
    """
    Run the check through a psql command and return ( exit_code, lines ).

    Requires:
        - psql_command connects to any database as a login that can connect to every database checked
        - run_fn( command, input, text ) behaves like subprocess.run

    Ensures:
        - exit 0 when every database is clean, 1 when any has a problem, 2 when psql failed or its
          output could not be read, which is not a pass
    """
    chosen  = tuple( which ) if which else databases()
    script  = "".join( f"\\connect {db}\n{build_check_sql( db )}" for db in chosen )
    command = shlex.split( psql_command ) + [ "-v", "ON_ERROR_STOP=1", "-q", "-tA" ]
    done    = run_fn( command, input=script, text=True, capture_output=True )
    if done.returncode != 0: return 2, [ f"the check could not run: psql exited {done.returncode}: {done.stderr.strip()[ -300: ]}" ]
    try:
        rows    = parse_rows( done.stdout )
        reports = [ evaluate( db, rows ) for db in chosen ]
    except ValueError as error:
        return 2, [ f"the check could not read psql's answer: {error}" ]
    lines = format_report( reports, remedy_for( psql_command, reports ) )
    return ( 0 if all( r[ "ok" ] for r in reports ) else 1 ), lines


# ── the check over an app's own connection ───────────────────────────────────

STANDARD_PSQL = "docker exec -i lupin-postgres psql -U lupin_dev -d lupin_db_dev"


def query_runner( connection ):
    """
    Wrap a SQLAlchemy connection as the `run_query( sql )` that check_current_database takes.

    Requires:
        - connection is open; the caller closes it

    Ensures:
        - the returned function sends the sql unchanged and returns the first column of every row
    """
    return lambda sql: [ row[ 0 ] for row in connection.exec_driver_sql( sql ) ]


def check_current_database( run_query ):
    """
    Check the database the connection is on, when the matrix describes it.

    Requires:
        - run_query( sql ) returns the first column of each result row as a list

    Ensures:
        - returns the evaluate() report for the current database
        - returns None, asking nothing more, when the database is not one the matrix names

    Raises:
        - ValueError when the answer cannot be read, since nothing was checked
    """
    current = run_query( "SELECT current_database();" )[ 0 ]
    if current not in databases(): return None
    return evaluate( current, parse_rows( "\n".join( run_query( build_check_sql( current ) ) ) ) )


LOG_LINE_LIMIT = 30


def report_lines( report ):
    """The check's lines for one report, cut to a log-sized list, with the repair command."""
    remedy = remedy_for( STANDARD_PSQL, [ report ] )
    return format_report( [ report ], remedy, limit=LOG_LINE_LIMIT )


def emit_startup_grants_alarm( debug=False, engine_factory=None ):
    """
    Boot-path entry point: check the app's own database, log a gap loudly, never raise.

    It runs one catalog query over the app's own login. It swallows every exception, as the schema-drift
    alarm does, because a bug here must never abort a boot that would otherwise succeed.

    Ensures:
        - on a gap: writes a block headed critical, naming each missing grant, to stderr and returns the report
        - on a clean database: prints one summary line and returns None
        - off a database the matrix names, and on a cloud-backed deployment: returns None, asking nothing
        - on any internal failure: returns None after a bounded warning on stderr; never propagates

    Args:
        debug:          also prints a line when it skips
        engine_factory: optional zero-argument function returning a SQLAlchemy engine (None: the app's own URL)

    Returns:
        dict | None
    """
    try:
        from cosa.rest.db.database import is_cloud_backed
        if is_cloud_backed():
            if debug: print( "[db-grants] skipped: a cloud-backed deployment has its own roles" )
            return None
        if engine_factory is None:
            from sqlalchemy import create_engine
            from cosa.rest.db.auto_migrate import resolve_database_url
            engine_factory = lambda: create_engine( resolve_database_url( None ) )
        engine = engine_factory()
        try:
            with engine.connect() as connection: report = check_current_database( query_runner( connection ) )
        finally:
            engine.dispose()
        if report is None:
            if debug: print( "[db-grants] skipped: this database is not one the matrix describes" )
            return None
        if report[ "ok" ]:
            print( "[db-grants] " + report_lines( report )[ 0 ] )
            return None
        print( "[db-grants] CRITICAL: the database roles lack grants the matrix requires\n" + "\n".join( report_lines( report ) ), file=sys.stderr, flush=True )
        return report
    except Exception:
        try:
            print( "[db-grants] WARNING: grants check failed; continuing boot (fail-open).", file=sys.stderr )
            traceback.print_exc( file=sys.stderr )
        except Exception:  # pragma: no cover  (stderr itself is unwritable; nothing is left to report with)
            pass
        return None
