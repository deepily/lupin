#!/usr/bin/python3 -I
"""
Make the compose secret files of the test login. Run as root, through one sudoers line.

src/scripts/install_db_secrets.py copies this file to /usr/local/sbin/lupin-install-db-secrets, owned by
root with mode 0755, and writes the sudoers line; do not copy it by hand. Run it from there with no arguments. Anyone who can write to the repository can edit the repository
copy, so sudo must never run that one.

It uses the standard library only and runs nothing from the repository. It refuses to run from a copy
with the wrong owner, mode or directory.

It reads one source, the operator's ~/.lupin/db_test_pw, which holds the test role's password.
It writes /etc/lupin/secrets/db_test_password (mode 0440, root:1002) from it.
It repairs the owner and mode of db_app_password, which must already exist. It never prints a password.

Exit codes:
    0   done.
    2   an argument was given.
    10  the copy is not owned by root.
    11  its mode is not 0755.
    12  not root.
    13  its directory is not root's alone.
    14  it was reached through a link.
    15  not run through sudo from an operator account.
    16  the source file is not safe to read.
    17  db_app_password is missing, a link or empty.
"""

import os
import pwd
import stat
import sys

# These mirror cosa.utils.db_secret_files on purpose: the file cannot import the repository.
# A unit test fails when either side moves.
SECRETS_DIR = "/etc/lupin/secrets"
GROUP_ID    = 1002
FILE_MODE   = 0o440
DIR_MODE    = 0o750
APP_FILE    = "db_app_password"
TEST_FILE   = "db_test_password"
SOURCE_NAME = os.path.join( ".lupin", "db_test_pw" )
SELF_MODE   = 0o755


class Refusal( Exception ):
    """A reason to stop, with the exit code it maps to."""
    def __init__( self, code, reason ):
        super().__init__( reason )
        self.code = code


def check_copy( path, stat_fn=os.lstat, realpath_fn=None ):
    """
    Refuse to run from a copy that anyone but root could have changed.

    Requires:
        - path is the path this script was started from

    Ensures:
        - raises Refusal 14 when the path is a link or resolves elsewhere
        - raises Refusal 10 when the file is not owned by uid 0
        - raises Refusal 11 when its mode is not exactly 0755
        - raises Refusal 13 when its directory is not owned by root or is writable by group or others
    """
    realpath_fn = realpath_fn or os.path.realpath
    if realpath_fn( path ) != os.path.abspath( path ) or stat.S_ISLNK( stat_fn( path ).st_mode ):
        raise Refusal( 14, f"{path} is reached through a link; run the root-owned copy by its real path" )
    info = stat_fn( path )
    if info.st_uid != 0: raise Refusal( 10, f"{path} is owned by uid {info.st_uid}, not root; install the copy as root" )
    if stat.S_IMODE( info.st_mode ) != SELF_MODE:
        raise Refusal( 11, f"{path} has mode {stat.S_IMODE( info.st_mode ):04o}, expected {SELF_MODE:04o}" )
    folder = stat_fn( os.path.dirname( path ) )
    if folder.st_uid != 0 or folder.st_mode & 0o022:
        raise Refusal( 13, f"{os.path.dirname( path )} is not root's alone (owner {folder.st_uid}, mode {stat.S_IMODE( folder.st_mode ):04o})" )


def read_source( env, lookup_fn=pwd.getpwuid ):
    """
    Read the test password from the operator's file, without trusting the path.

    Requires:
        - env carries SUDO_UID, set by sudo

    Ensures:
        - returns the stripped password
        - raises Refusal 15 without a non-root SUDO_UID that names an account
        - raises Refusal 16 when the file is a link, not a regular file, not owned by that account,
          writable by group or others, or empty
    """
    try:
        uid = int( env[ "SUDO_UID" ] )
        home = lookup_fn( uid ).pw_dir
    except ( KeyError, ValueError ):
        raise Refusal( 15, "run this through sudo from your own account" )
    if uid == 0: raise Refusal( 15, "run this through sudo from an operator account, not from root's own shell" )
    path = os.path.join( home, SOURCE_NAME )
    try:
        fd = os.open( path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK )
    except OSError as error:
        raise Refusal( 16, f"{path} cannot be opened safely: {error.__class__.__name__}" )
    info = os.fstat( fd )
    if not stat.S_ISREG( info.st_mode ) or info.st_uid != uid or info.st_mode & 0o022:
        os.close( fd )
        raise Refusal( 16, f"{path} must be a regular file owned by uid {uid} and not writable by others" )
    with os.fdopen( fd ) as handle: password = handle.read().strip()
    if not password: raise Refusal( 16, f"{path} is empty" )
    return password


def install( directory, password, chown_fn=os.chown ):
    """
    Make the secret directory and files right, and say what happened to each.

    Requires:
        - the caller is root and password is the non-empty test password

    Ensures:
        - the directory is mode 0750, root:GROUP_ID
        - db_app_password keeps its content and gets mode 0440, root:GROUP_ID; raises Refusal 17 when it is
          absent, a link or empty
        - db_test_password holds the password at mode 0440, root:GROUP_ID, written beside itself and renamed
        - returns { name: "unchanged" | "repaired" | "written" }, never a password
    """
    report = { }
    if not os.path.isdir( directory ): os.makedirs( directory, mode=DIR_MODE )
    chown_fn( directory, 0, GROUP_ID )
    os.chmod( directory, DIR_MODE )
    app = os.path.join( directory, APP_FILE )
    if os.path.islink( app ) or not os.path.isfile( app ) or os.path.getsize( app ) == 0:
        raise Refusal( 17, f"{app} must exist first as a plain, non-empty file; make it with the runbook step that creates the app password" )
    report[ APP_FILE ] = _fix_attributes( app, chown_fn )
    path = os.path.join( directory, TEST_FILE )
    if _holds( path, password ):
        report[ TEST_FILE ] = _fix_attributes( path, chown_fn )
        return report
    state = "repaired" if os.path.lexists( path ) else "written"
    temp = path + ".new"
    if os.path.lexists( temp ): os.unlink( temp )
    # Created at 0440 and exclusively, so the password is never in a readable file or a followed link.
    with os.fdopen( os.open( temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE ), "w" ) as handle: handle.write( password + "\n" )
    os.chmod( temp, FILE_MODE )
    chown_fn( temp, 0, GROUP_ID )
    os.replace( temp, path )
    report[ TEST_FILE ] = state
    return report


def _holds( path, password ):
    """Say whether path is a plain file holding exactly this password."""
    if os.path.islink( path ) or not os.path.isfile( path ): return False
    with open( path ) as handle: return handle.read().strip() == password


def _owner_of( path ):
    """Return ( uid, gid ) of a path."""
    info = os.stat( path )
    return info.st_uid, info.st_gid


def _fix_attributes( path, chown_fn ):
    """Set mode 0440 and root:GROUP_ID on a file; return "unchanged" or "repaired"."""
    if stat.S_IMODE( os.stat( path ).st_mode ) == FILE_MODE and _owner_of( path ) == ( 0, GROUP_ID ): return "unchanged"
    chown_fn( path, 0, GROUP_ID )
    os.chmod( path, FILE_MODE )
    return "repaired"


def main( argv=None, env=None, geteuid=os.geteuid, self_path=None, directory=SECRETS_DIR, chown_fn=os.chown,
          stat_fn=os.lstat, lookup_fn=pwd.getpwuid, out=sys.stdout ):
    """
    Run the whole step and return the exit code.

    Requires:
        - the arguments after the program name are empty

    Ensures:
        - checks the copy, then root, then the source, then writes; any refusal prints its reason and returns its code
        - prints one line per file and never a password
    """
    argv = sys.argv if argv is None else argv
    env = os.environ if env is None else env
    try:
        if len( argv ) > 1: raise Refusal( 2, "takes no arguments; the sudoers line allows none" )
        check_copy( argv[ 0 ] if self_path is None else self_path, stat_fn )
        if geteuid() != 0: raise Refusal( 12, "must run as root; use sudo" )
        password = read_source( env, lookup_fn )
        for name, what in install( directory, password, chown_fn ).items():
            print( f"lupin-install-db-secrets: {os.path.join( directory, name )}: {what}", file=out )
    except Refusal as refusal:
        print( f"lupin-install-db-secrets: refused: {refusal}", file=out )
        return refusal.code
    return 0


if __name__ == "__main__":   # pragma: no cover  (thin entry point; main() is what is tested)
    sys.exit( main() )
