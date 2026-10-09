#!/usr/bin/python3 -I
"""
Install the test login's database secret files on a new host, in one command.

Run once from an operator account:  sudo src/scripts/install_db_secrets.py
Check without changing anything:    sudo src/scripts/install_db_secrets.py --check

It does the three steps that used to be typed by hand, and carries nothing between them:
    1. copies src/scripts/lupin_install_db_secrets.py to /usr/local/sbin/lupin-install-db-secrets
       (root-owned, mode 0755), so sudo never runs a file the repository can change;
    2. writes /etc/sudoers.d/lupin-install-db-secrets, only after `visudo -cf` accepts the line and
       again after `visudo -c` accepts the whole set (a failure there removes the new line);
    3. runs the installed copy, which makes /etc/lupin/secrets/db_test_password.

Everything that can be checked is checked before the first change. A refusal prints what stopped it
and which of the three steps were not done. A rerun on a finished host reports "unchanged" for each.

What stays manual is listed in src/docs/db-secrets-install.md. It covers the app password file, the
operator's password file, the lupin_test role, Cloud SQL, terraform and the VM push.

It uses the standard library only. It finds the payload beside itself, not through LUPIN_ROOT, because
sudo drops the environment.

Exit codes (install):
    0   done, or --check found everything in place.
    2   an argument it does not know.
    15, 16, 17   the payload's own refusals about the operator account, ~/.lupin/db_test_pw, db_app_password.
    20  not root.
    21  not run through sudo from an operator account.
    22  the payload in the repository is missing or a link.
    23  visudo was not found.
    26  visudo refused the new sudoers line; nothing was installed.
    27  visudo refused the whole set after the line went in; the line was taken out again.
    Any other nonzero code is the installed copy's own, passed through.
Exit codes (--check): 0 everything in place, 1 something missing or different, 2 could not look.
"""

import hashlib
import importlib.util
import os
import pwd
import re
import shutil
import subprocess
import sys

COPY_PATH     = "/usr/local/sbin/lupin-install-db-secrets"
SUDOERS_PATH  = "/etc/sudoers.d/lupin-install-db-secrets"
SECRETS_DIR   = "/etc/lupin/secrets"
PAYLOAD_NAME  = "lupin_install_db_secrets.py"
COPY_MODE     = 0o755
SUDOERS_MODE  = 0o440
USER_PATTERN  = re.compile( r"^[a-z_][a-z0-9_-]*$" )
STEPS         = ( "copy of the payload", "sudoers line", "run of the installed copy" )
TAG           = "install-db-secrets"


class Refusal( Exception ):
    """A reason to stop, with the exit code it maps to."""

    def __init__( self, code, reason ):
        super().__init__( reason )
        self.code = code


class Host:
    """
    Every outside thing the installer touches, in one place so tests can replace it.

    Requires:
        - nothing; every default is the real thing

    Ensures:
        - paths and calls can be overridden one by one
    """

    def __init__( self, **overrides ):
        self.geteuid      = os.geteuid
        self.lookup       = pwd.getpwuid
        self.which        = shutil.which
        self.runner       = run_command
        self.chown        = os.chown
        self.out          = sys.stdout
        self.payload_path = os.path.join( os.path.dirname( os.path.abspath( __file__ ) ), PAYLOAD_NAME )
        self.copy_path    = COPY_PATH
        self.sudoers_path = SUDOERS_PATH
        self.secrets_dir  = SECRETS_DIR
        self.python       = sys.executable
        for name, value in overrides.items():
            if not hasattr( self, name ): raise TypeError( f"Host has no setting {name!r}" )
            setattr( self, name, value )


def run_command( command, env=None ):
    """
    Run a command and return ( exit code, its output ).

    Requires:
        - command is a list of strings

    Ensures:
        - stdout and stderr come back together as one string
    """
    done = subprocess.run( command, capture_output=True, text=True, env=env )
    return done.returncode, done.stdout + done.stderr


def sudoers_line( user, copy_path ):
    """
    Render the one line that lets user run the installed copy with no arguments.

    Requires:
        - user matches USER_PATTERN

    Ensures:
        - the trailing "" is kept: without it sudo would allow any arguments
    """
    return f'{user} ALL=(root) NOPASSWD: {copy_path} ""\n'


def load_payload( path ):
    """Import the payload file by its path and return the module."""
    spec   = importlib.util.spec_from_file_location( "lupin_install_db_secrets", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def owner_and_mode( path ):
    """Return ( uid, gid, permission bits ) of a path, following no link beyond the first stat."""
    info = os.stat( path )
    return info.st_uid, info.st_gid, info.st_mode & 0o7777


def sha256_of( data ):
    """Return the hex sha256 of bytes."""
    return hashlib.sha256( data ).hexdigest()


def operator_of( env, host ):
    """
    Name the account that ran sudo.

    Requires:
        - env is the environment sudo handed us

    Ensures:
        - returns ( uid, name ) for a non-root account whose SUDO_USER agrees with SUDO_UID
        - raises Refusal 21 otherwise, so a name taken from the environment is never trusted alone
    """
    try:
        uid  = int( env[ "SUDO_UID" ] )
        name = host.lookup( uid ).pw_name
    except ( KeyError, ValueError ):
        raise Refusal( 21, "run this through sudo from your own account: sudo src/scripts/install_db_secrets.py" )
    if uid == 0: raise Refusal( 21, "run this through sudo from an operator account, not from root's own shell" )
    if env.get( "SUDO_USER" ) != name: raise Refusal( 21, f"SUDO_USER does not name uid {uid} ({name}); run it again through sudo" )
    if not USER_PATTERN.match( name ): raise Refusal( 21, f"account name {name!r} cannot go into a sudoers line" )
    return uid, name


def preflight( env, host ):
    """
    Check everything that can be checked before the first change.

    Requires:
        - env is the environment sudo handed us

    Ensures:
        - returns { "user", "payload_bytes", "payload_module", "visudo" } when every check passes
        - raises Refusal for the first check that fails, having changed nothing
        - the payload's own source checks run here, so a bad ~/.lupin/db_test_pw stops the copy from running
    """
    if host.geteuid() != 0: raise Refusal( 20, "must run as root; use sudo" )
    uid, user = operator_of( env, host )
    path = host.payload_path
    if os.path.islink( path ) or not os.path.isfile( path ):
        raise Refusal( 22, f"{path} is missing or a link; run this from a clean checkout" )
    visudo = host.which( "visudo" )
    if visudo is None: raise Refusal( 23, "visudo was not found; install the sudo package first" )
    module = load_payload( path )
    try:
        module.read_source( env, host.lookup )
    except module.Refusal as refusal:
        raise Refusal( refusal.code, str( refusal ) )
    app = os.path.join( host.secrets_dir, module.APP_FILE )
    if os.path.islink( app ) or not os.path.isfile( app ) or os.path.getsize( app ) == 0:
        raise Refusal( 17, f"{app} must exist first as a plain, non-empty file; make it with the runbook step that creates the app password" )
    with open( path, "rb" ) as handle: data = handle.read()
    return { "user": user, "payload_bytes": data, "payload_module": module, "visudo": visudo }


def write_file( path, data, mode, host ):
    """
    Put data at path as root:root with this mode, written beside itself and renamed.

    Requires:
        - the caller is root

    Ensures:
        - returns "unchanged" when the bytes, mode and owner already match, "repaired" when the file existed, else "written"
        - the temporary file is created exclusively at the final mode, so the content is never in a looser file
    """
    existed = os.path.lexists( path )
    if existed and not os.path.islink( path ):
        with open( path, "rb" ) as handle: same = handle.read() == data
        if same and owner_and_mode( path ) == ( 0, 0, mode ): return "unchanged"
    temp = path + ".new"
    if os.path.lexists( temp ): os.unlink( temp )
    with os.fdopen( os.open( temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode ), "wb" ) as handle: handle.write( data )
    os.chmod( temp, mode )
    host.chown( temp, 0, 0 )
    os.replace( temp, path )
    return "repaired" if existed else "written"


def install_copy( facts, host ):
    """Step 1: copy the payload to the root-owned place."""
    return write_file( host.copy_path, facts[ "payload_bytes" ], COPY_MODE, host )


def install_sudoers( facts, host ):
    """
    Step 2: write the sudoers line, once visudo accepts it.

    If visudo then refuses the whole set, the new line is taken out again.

    Requires:
        - facts came from preflight

    Ensures:
        - returns "unchanged", "written" or "repaired"
        - raises Refusal 26 with no sudoers file changed when visudo -cf refuses the line
        - raises Refusal 27 with the previous file (or none) restored when visudo -c refuses the set
        - the temporary name contains a dot, so sudo itself ignores it while it is being checked
    """
    data     = sudoers_line( facts[ "user" ], host.copy_path ).encode()
    path     = host.sudoers_path
    previous = None
    if os.path.lexists( path ) and not os.path.islink( path ):
        with open( path, "rb" ) as handle: previous = handle.read()
    temp = path + ".new"
    if os.path.lexists( temp ): os.unlink( temp )
    with os.fdopen( os.open( temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, SUDOERS_MODE ), "wb" ) as handle: handle.write( data )
    host.chown( temp, 0, 0 )
    code, text = host.runner( [ facts[ "visudo" ], "-cf", temp ] )
    os.unlink( temp )
    if code != 0: raise Refusal( 26, f"visudo refused the sudoers line: {text.strip()}" )
    state = write_file( path, data, SUDOERS_MODE, host )
    code, text = host.runner( [ facts[ "visudo" ], "-c" ] )
    if code != 0:
        if previous is None: os.unlink( path )
        else: write_file( path, previous, SUDOERS_MODE, host )
        raise Refusal( 27, f"visudo refused the whole set; the new line was taken out again: {text.strip()}" )
    return state


def run_installed( facts, env, host ):
    """
    Step 3: run the installed copy, which makes db_test_password.

    Ensures:
        - returns the lines the copy printed
        - raises Refusal with the copy's own exit code when it refuses
    """
    code, text = host.runner( [ host.python, "-I", host.copy_path ], env )
    if code != 0: raise Refusal( code, f"the installed copy refused:\n{text.strip()}" )
    return text.strip()


def install( env, host ):
    """
    Run the preflight and the three steps, and say what each did.

    Ensures:
        - on a refusal, prints the reason and which steps were not done, and returns the refusal's code
        - on success, prints one line per step and the copy's own lines, and returns 0
    """
    done = [ ]
    try:
        facts = preflight( env, host )
        for name, step in ( ( STEPS[ 0 ], install_copy ), ( STEPS[ 1 ], install_sudoers ) ):
            state = step( facts, host )
            done.append( name )
            print( f"{TAG}: {name}: {state}", file=host.out )
        text = run_installed( facts, env, host )
        print( f"{TAG}: {STEPS[ 2 ]}:", file=host.out )
        print( text, file=host.out )
    except Refusal as refusal:
        todo = [ step for step in STEPS if step not in done ]
        print( f"{TAG}: refused: {refusal}", file=host.out )
        print( f"{TAG}: done: {', '.join( done ) or 'nothing'}; did not: {', '.join( todo )}", file=host.out )
        return refusal.code
    return 0


def check( env, host ):
    """
    Report the state of each piece and change nothing.

    Ensures:
        - returns 0 when everything is in place, 1 when something is missing or different, 2 when something could not be looked at
        - a piece that needs root to see is reported as "cannot look" when not root, never as missing
    """
    if os.path.islink( host.payload_path ) or not os.path.isfile( host.payload_path ):
        print( f"{TAG}: payload: cannot look ({host.payload_path} is missing or a link)", file=host.out )
        return 2
    with open( host.payload_path, "rb" ) as handle: want = handle.read()
    rows = [ ( "copy of the payload", _copy_state( host.copy_path, want ) ) ]
    if host.geteuid() != 0:
        rows.append( ( "sudoers line", "cannot look (not root)" ) )
        rows.append( ( "secret files", "cannot look (not root)" ) )
    else:
        rows.append( ( "sudoers line", _sudoers_state( host.sudoers_path, env.get( "SUDO_USER" ), host.copy_path ) ) )
        rows.append( ( "secret files", _secrets_state( host, env ) ) )
    for name, state in rows: print( f"{TAG}: {name}: {state}", file=host.out )
    states = [ state for _, state in rows ]
    if any( not state.startswith( ( "ok", "cannot look" ) ) for state in states ): return 1
    return 2 if any( state.startswith( "cannot look" ) for state in states ) else 0


def _copy_state( path, want ):
    """Say whether the installed copy matches the repository's payload."""
    if not os.path.lexists( path ): return "missing"
    if os.path.islink( path ): return "different: a link"
    uid, gid, mode = owner_and_mode( path )
    if uid != 0 or mode != COPY_MODE: return f"different: owner {uid}, mode {mode:04o}"
    with open( path, "rb" ) as handle: have = handle.read()
    if have != want: return f"different: sha256 {sha256_of( have )[ :12 ]} against the repository's {sha256_of( want )[ :12 ]}"
    return f"ok (sha256 {sha256_of( want )[ :12 ]})"


def _sudoers_state( path, user, copy_path ):
    """Say whether the sudoers file holds this operator's line."""
    if user is None or not USER_PATTERN.match( user ): return "cannot look (not run through sudo, so the operator is unknown)"
    if not os.path.lexists( path ): return "missing"
    if os.path.islink( path ): return "different: a link"
    with open( path ) as handle: have = handle.read()
    if have != sudoers_line( user, copy_path ): return "different: the line is not the expected one"
    uid, gid, mode = owner_and_mode( path )
    if uid != 0 or mode != SUDOERS_MODE: return f"different: owner {uid}, mode {mode:04o}"
    return "ok"


def _secrets_state( host, env ):
    """Say whether the secret directory and both files are right."""
    module = load_payload( host.payload_path )
    if not os.path.isdir( host.secrets_dir ): return "missing: the directory"
    problems = [ ]
    for name in ( module.APP_FILE, module.TEST_FILE ):
        path = os.path.join( host.secrets_dir, name )
        if not os.path.isfile( path ) or os.path.islink( path ):
            problems.append( f"{name} missing" )
            continue
        uid, gid, mode = owner_and_mode( path )
        if ( uid, gid, mode ) != ( 0, module.GROUP_ID, module.FILE_MODE ): problems.append( f"{name} owner {uid}:{gid} mode {mode:04o}" )
    if problems: return "different: " + "; ".join( problems )
    try:
        password = module.read_source( env, host.lookup )
    except module.Refusal as refusal:
        return f"cannot look (the operator's password file: {refusal})"
    if not module._holds( os.path.join( host.secrets_dir, module.TEST_FILE ), password ):
        return "different: db_test_password does not hold the password in ~/.lupin/db_test_pw"
    return "ok"


def main( argv=None, env=None, host=None ):
    """
    Entry point: install, or --check.

    Requires:
        - argv holds the program name and at most --check

    Ensures:
        - returns the exit code documented at the top of the file
    """
    argv = sys.argv if argv is None else argv
    env  = os.environ if env is None else env
    host = Host() if host is None else host
    if len( argv ) > 2 or ( len( argv ) == 2 and argv[ 1 ] != "--check" ):
        print( f"{TAG}: refused: usage: sudo install_db_secrets.py [--check]", file=host.out )
        return 2
    if len( argv ) == 2: return check( env, host )
    return install( env, host )


if __name__ == "__main__":   # pragma: no cover  (thin entry point; main() is what is tested)
    sys.exit( main() )
