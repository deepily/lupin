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

`--rollback` is the cutover's way back. It hands every object that `lupin_app` owns in the test and dev
databases back to `lupin_dev`. It runs nothing else: no role, password or grant is touched, and the template
database stays. It reads no password file, so the three file options may be left out.

    python -m cosa.utils.db_roles --psql "..." --rollback [--apply]

`--drop-template` removes the template database and nothing else, and reads no password file.

    python -m cosa.utils.db_roles --psql "..." --drop-template [--apply]

`--grants-only` repeats the grants, the revoke on approval_settings and the default privileges, and makes
the template database if it is missing. Nothing else runs. It creates no role and resets no password, so it reads no password file and needs no root.
It is the repair after a migration or a test created a table the roles cannot yet reach.

    python -m cosa.utils.db_roles --psql "..." --grants-only [--apply]

`--check` changes nothing. It asks Postgres what each role may do to every public table of both
databases and compares the answer with the matrix in `cosa.utils.db_grants`. Each gap is printed
with the one repair command. It also reports the template database `lupin_template_vector`, which tests clone,
when it is missing, is not a template or accepts connections.
Exit 0 is clean, 1 is a gap or a database with no tables, 2 is a check that could not run.

    python -m cosa.utils.db_roles --psql "..." --check [--database lupin_db_test]

A login that may connect to one database only, such as lupin_test or lupin_host, names it with `--database`.
Without it the check asks both and exits 2 for the one that login cannot reach.
"""

import argparse
import os
import shlex
import subprocess
import sys

from cosa.utils import db_grants, db_secret_files

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


def build_psql_stdin( app_pw, host_pw, test_pw, sql_text, reassign=False, redact=False, rollback=False, grants_only=False, drop_template=False ):
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
        - drop_template=True gives one `\\set drop_template 1` line and the SQL, with no password line, so the three password arguments are ignored
        - ends with a newline
    """
    shown = lambda value: "<redacted>" if redact else value
    if rollback:        lines = [ "\\set rollback 1" ]
    elif grants_only:   lines = [ "\\set grants_only 1" ]
    elif drop_template: lines = [ "\\set drop_template 1" ]
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


def main( argv=None, run_fn=subprocess.run, out=sys.stdout, geteuid=os.geteuid, chown=os.chown ):
    """
    Plan or apply the role provisioning.

    Ensures:
        - with --check: reads and prints only, never writes, and returns db_grants.check_with_psql's exit code
        - without --apply: prints the psql command and the redacted stdin, runs nothing, returns 0
        - with --apply: runs the psql command with the real stdin and returns its exit code
        - a bad password file, or an unreadable SQL file, returns 2 and prints why, before anything runs
        - with --check, --rollback or --grants-only no password file is read, and --reassign is refused
        - without either, all three password files are required
        - --secrets-dir adds the root-owned secret files: written after a successful run, listed by a dry run,
          checked by --check, and refused with --rollback, --grants-only, --drop-template and --reassign
        - a run that would write them but is not root is refused before psql runs
    """
    parser = argparse.ArgumentParser( description=__doc__.split( "\n\n" )[ 0 ] )
    parser.add_argument( "--app-pw-file",  default=None )
    parser.add_argument( "--host-pw-file", default=None )
    parser.add_argument( "--test-pw-file", default=None )
    parser.add_argument( "--psql", required=True, help="the whole superuser psql command, connected to lupin_db_dev" )
    parser.add_argument( "--sql", default=None, help="init-db-roles.sql path (default: from LUPIN_ROOT)" )
    direction = parser.add_mutually_exclusive_group()
    direction.add_argument( "--reassign", action="store_true", help="CUTOVER ONLY: move ownership in the dev and test databases to lupin_app" )
    direction.add_argument( "--rollback", action="store_true", help="CUTOVER ONLY: move it back to lupin_dev; no role, password or grant changes" )
    direction.add_argument( "--check", action="store_true", help="read-only: list every missing or unexpected privilege; exit 1 when there is one" )
    direction.add_argument( "--grants-only", action="store_true", help="repeat the grants and default privileges, and make the template database if missing; no role or password is touched" )
    direction.add_argument( "--drop-template", action="store_true", help="remove the template database lupin_template_vector and nothing else" )
    parser.add_argument( "--apply", action="store_true", help="run it; without this the plan is only printed" )
    parser.add_argument( "--secrets-dir", default=None, help="the directory of the compose secret files; see cosa.utils.db_secret_files" )
    parser.add_argument( "--secrets-group-id", type=int, default=db_secret_files.GROUP_ID, help="group of the secret files; the compose services join it" )
    parser.add_argument( "--database", action="append", choices=db_grants.databases(), help="with --check: check only this database (repeatable)" )
    args = parser.parse_args( argv )

    if args.database and not args.check: parser.error( "--database is only meaningful with --check" )
    if args.secrets_dir and ( args.rollback or args.grants_only or args.drop_template or args.reassign ):
        parser.error( "--secrets-dir needs the full run: it cannot be combined with --rollback, --grants-only, --drop-template or --reassign" )
    if args.check:
        code, lines = db_grants.check_with_psql( args.psql, run_fn, which=args.database )
        for line in lines: print( line, file=out )
        if args.secrets_dir:
            values = None
            if args.app_pw_file and args.test_pw_file:
                try:
                    values = db_secret_files.wanted( read_secret( args.app_pw_file ), read_secret( args.test_pw_file ) )
                except ValueError as error:
                    print( f"db_roles: {error}", file=out )
                    return 2
            gaps, notes = db_secret_files.check_files( args.secrets_dir, values, args.secrets_group_id )
            for line in gaps + notes: print( line, file=out )
            if gaps: code = max( code, 1 )
        return code

    app_pw = host_pw = test_pw = None
    if not ( args.rollback or args.grants_only or args.drop_template ):
        pw_files = ( args.app_pw_file, args.host_pw_file, args.test_pw_file )
        if any( path is None for path in pw_files ):
            parser.error( "--app-pw-file, --host-pw-file and --test-pw-file are required unless --rollback, --grants-only or --drop-template is given" )
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
    if args.secrets_dir and args.apply and geteuid() != 0:
        print( "db_roles: writing the secret files needs root; nothing was run. Repeat the command with sudo.", file=out )
        return 2

    if not args.apply:
        print( "db_roles: DRY RUN (nothing was run). Add --apply to run it.", file=out )
        print( "command: " + shlex.join( command ), file=out )
        print( "stdin:", file=out )
        print( build_psql_stdin( app_pw, host_pw, test_pw, sql_text, args.reassign, redact=True, rollback=args.rollback, grants_only=args.grants_only, drop_template=args.drop_template ), file=out, end="" )
        if args.secrets_dir: print( "then, as root, in " + args.secrets_dir + ": " + ", ".join( db_secret_files.FILE_NAMES ), file=out )
        return 0

    stdin = build_psql_stdin( app_pw, host_pw, test_pw, sql_text, args.reassign, rollback=args.rollback, grants_only=args.grants_only, drop_template=args.drop_template )
    code = run_fn( command, input=stdin, text=True ).returncode
    if code != 0 or not args.secrets_dir: return code
    values = db_secret_files.wanted( app_pw, test_pw )
    for name, what in db_secret_files.write_files( args.secrets_dir, values, args.secrets_group_id, geteuid, chown ).items():
        print( f"db_roles: secret file {os.path.join( args.secrets_dir, name )}: {what}", file=out )
    return 0


if __name__ == "__main__":   # pragma: no cover  (thin entry point; main() is what is tested)
    sys.exit( main() )
