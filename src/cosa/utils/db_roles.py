"""
Provision the three database roles of the approval-settings guard rail.

Feeds `src/scripts/sql/init-db-roles.sql` to a superuser `psql`. The passwords are read from
files and sent to psql on stdin as `\\set` lines. They never appear in an argument list or a
process listing, and a dry run prints the plan with every password redacted.

A dry run is the default. Nothing touches a database unless `--apply` is given. Applying needs
the three password files to exist. The app's file must be unreadable to a seat, so it is
root-owned. Setting that up is host administration, which this module neither performs nor
works around.

    python -m cosa.utils.db_roles --app-pw-file F --host-pw-file F --test-pw-file F \\
        --psql "docker exec -i lupin-postgres psql -U lupin_dev -d lupin_db_dev" [--reassign] [--apply]

`--rollback` is the cutover's way back. It hands every dev-database object that `lupin_app` owns
back to `lupin_dev` and runs nothing else: no role, password or grant is touched. It reads no
password file, so the three file options may be left out.

    python -m cosa.utils.db_roles --psql "..." --rollback [--apply]

`--grants-only` repeats the grants, the revoke on approval_settings and the default privileges, and nothing
else. It creates no role and resets no password, so it reads no password file and needs no root.
It is the repair after a migration or a test created a table the roles cannot yet reach.

    python -m cosa.utils.db_roles --psql "..." --grants-only [--apply]
"""

import argparse
import os
import shlex
import subprocess
import sys

SQL_RELATIVE_PATH = "src/scripts/sql/init-db-roles.sql"

# A value that would break out of a psql single-quoted meta-command argument. Generated
# passwords are hex; refusing these is simpler and safer than escaping them.
_UNSAFE_CHARS = ( "'", "\\", "\n", "\r", "\x00" )


def read_secret( path ):
    """
    Read one password file and return its stripped content.

    Requires:
        - path names a readable file

    Ensures:
        - returns the content with surrounding whitespace stripped
        - raises ValueError, naming the file, if it is missing, unreadable, empty, or holds a
          character that cannot be sent safely in a psql meta-command (quote, backslash, newline)
    """
    try:
        with open( path ) as handle: value = handle.read().strip()
    except OSError as error:
        raise ValueError( f"password file {path} could not be read: {error.__class__.__name__}" ) from error
    if not value: raise ValueError( f"password file {path} is empty" )
    if any( c in value for c in _UNSAFE_CHARS ):
        raise ValueError( f"password file {path} holds a quote, backslash or newline; use a hex password" )
    return value


def build_psql_stdin( app_pw, host_pw, test_pw, sql_text, reassign=False, redact=False, rollback=False, grants_only=False ):
    """
    Build the psql stdin: three password `\\set` lines, an optional reassign line, the SQL.

    The SQL travels on stdin rather than as `\\i <path>`. The psql may run inside the postgres
    container (`docker exec -i ... psql`), where a host path does not exist.

    Requires:
        - the three passwords are non-empty strings free of the unsafe characters
        - sql_text is the content of init-db-roles.sql

    Ensures:
        - redact=True replaces each password with "<redacted>" and the SQL with a one-line
          marker, so the text is safe and short to print
        - reassign=True adds the cutover-only ownership transfer
        - rollback=True gives one `\\set rollback 1` line and the SQL, with no password line, so the three password arguments are ignored
        - grants_only=True gives one `\\set grants_only 1` line and the SQL, with no password line, so the three password arguments are ignored
        - ends with a newline
    """
    shown = lambda value: "<redacted>" if redact else value
    if rollback:      lines = [ "\\set rollback 1" ]
    elif grants_only: lines = [ "\\set grants_only 1" ]
    else:
        lines = [
            f"\\set app_pw  '{shown( app_pw )}'",
            f"\\set host_pw '{shown( host_pw )}'",
            f"\\set test_pw '{shown( test_pw )}'",
        ]
    if reassign: lines.append( "\\set reassign 1" )
    if redact: lines.append( f"-- <{len( sql_text.splitlines() )} lines of init-db-roles.sql follow here on a real run>" )
    else:      lines.append( sql_text.rstrip( "\n" ) )
    return "\n".join( lines ) + "\n"


def main( argv=None, run_fn=subprocess.run, out=sys.stdout ):
    """
    Plan or apply the role provisioning.

    Ensures:
        - without --apply: prints the psql command and the redacted stdin, runs nothing, returns 0
        - with --apply: runs the psql command with the real stdin and returns its exit code
        - a bad password file, or an unreadable SQL file, returns 2 and prints why, before anything runs
        - with --rollback or --grants-only no password file is read, and --reassign is refused
        - without either, all three password files are required
    """
    parser = argparse.ArgumentParser( description=__doc__.split( "\n\n" )[ 0 ] )
    parser.add_argument( "--app-pw-file",  default=None )
    parser.add_argument( "--host-pw-file", default=None )
    parser.add_argument( "--test-pw-file", default=None )
    parser.add_argument( "--psql", required=True, help="the whole superuser psql command, connected to lupin_db_dev" )
    parser.add_argument( "--sql", default=None, help="init-db-roles.sql path (default: from LUPIN_ROOT)" )
    direction = parser.add_mutually_exclusive_group()
    direction.add_argument( "--reassign", action="store_true", help="CUTOVER ONLY: move dev-database ownership to lupin_app" )
    direction.add_argument( "--rollback", action="store_true", help="CUTOVER ONLY: move it back to lupin_dev; no role, password or grant changes" )
    direction.add_argument( "--grants-only", action="store_true", help="repeat the grants and default privileges only; no role or password is touched" )
    parser.add_argument( "--apply", action="store_true", help="run it; without this the plan is only printed" )
    args = parser.parse_args( argv )

    app_pw = host_pw = test_pw = None
    if not ( args.rollback or args.grants_only ):
        pw_files = ( args.app_pw_file, args.host_pw_file, args.test_pw_file )
        if any( path is None for path in pw_files ):
            parser.error( "--app-pw-file, --host-pw-file and --test-pw-file are required unless --rollback or --grants-only is given" )
        try:
            app_pw, host_pw, test_pw = ( read_secret( path ) for path in pw_files )
        except ValueError as error:
            print( f"db_roles: {error}", file=out )
            return 2

    sql_path = args.sql
    if sql_path is None:
        root     = os.environ.get( "LUPIN_ROOT", "/var/lupin" )
        sql_path = os.path.join( root, SQL_RELATIVE_PATH )
    try:
        with open( sql_path ) as handle: sql_text = handle.read()
    except OSError as error:
        print( f"db_roles: SQL file {sql_path} could not be read: {error.__class__.__name__}", file=out )
        return 2
    command = shlex.split( args.psql ) + [ "-v", "ON_ERROR_STOP=1", "-q" ]

    if not args.apply:
        print( "db_roles: DRY RUN (nothing was run). Add --apply to run it.", file=out )
        print( "command: " + shlex.join( command ), file=out )
        print( "stdin:", file=out )
        print( build_psql_stdin( app_pw, host_pw, test_pw, sql_text, args.reassign, redact=True, rollback=args.rollback, grants_only=args.grants_only ), file=out, end="" )
        return 0

    stdin = build_psql_stdin( app_pw, host_pw, test_pw, sql_text, args.reassign, rollback=args.rollback, grants_only=args.grants_only )
    return run_fn( command, input=stdin, text=True ).returncode


if __name__ == "__main__":   # pragma: no cover  (thin entry point; main() is what is tested)
    sys.exit( main() )
