r"""
The compose secret files, made and checked by the provisioner.

Two services read a database password from a mounted secret file: the app login, and the test login that
creates throwaway databases. Making those files by hand on one host does not scale to every install. The
provisioner makes them from the same password files it already reads, and the read-only check reports any gap.

The files live in one directory, `/etc/lupin/secrets` by default. Each is owned by root, group 1002, mode 0440.
Group 1002 is the group the compose services join, so the service can read the file and a seat cannot.
Writing them needs root, and that is the one sudo step: the same command on every host.

    sudo python -m cosa.utils.db_roles --psql "..." --app-pw-file F --host-pw-file F --test-pw-file F \\
        --secrets-dir /etc/lupin/secrets --apply

`--check --secrets-dir DIR` adds the files to the read-only check. Add the password files to also compare each value.
"""

import os
import stat

DEFAULT_DIR   = "/etc/lupin/secrets"
GROUP_ID      = 1002
MODE          = 0o440
DIR_MODE      = 0o750
APP_FILE      = "db_app_password"
TEST_FILE     = "db_test_password"
FILE_NAMES  = ( APP_FILE, TEST_FILE )


def _owner_of( path ):
    """Return ( uid, gid ) of a path without following a link."""
    info = os.lstat( path )
    return info.st_uid, info.st_gid


def _read_text( path ):
    with open( path ) as handle: return handle.read()


def wanted( app_pw, test_pw ):
    """
    Pair each secret file name with the password it must hold.

    Requires:
        - app_pw and test_pw are the passwords read from the provisioner's password files

    Ensures:
        - returns { file name: password } for the files in FILE_NAMES, no others
    """
    return { APP_FILE: app_pw, TEST_FILE: test_pw }


def write_files( directory, values, group_id=GROUP_ID, geteuid=os.geteuid, chown=os.chown ):
    """
    Make or repair the secret files and say what happened to each.

    Requires:
        - values is { file name: password } with non-empty passwords
        - the caller is root, because the files belong to root

    Ensures:
        - refuses the whole run, writing nothing, when the caller is not root
        - creates the directory with mode 0750, owner root, group group_id, when it is missing
        - tightens an existing directory that has another mode or owner, and reports it as "directory": "repaired"
        - a file holding the right value, mode and owner is left alone and reported "unchanged"
        - otherwise the file is written beside itself, set to mode 0440 root:group_id, then renamed into place,
          and reported "written" when it was absent or "repaired" when it was wrong
        - the password is never returned or printed

    Raises:
        - PermissionError when the caller is not root
    """
    if geteuid() != 0: raise PermissionError( "writing the secret files needs root; run the command with sudo" )
    if not os.path.isdir( directory ):
        os.makedirs( directory, mode=DIR_MODE )
        chown( directory, 0, group_id )
        os.chmod( directory, DIR_MODE )
    report = { }
    if _dir_gaps( directory, group_id ):
        chown( directory, 0, group_id )
        os.chmod( directory, DIR_MODE )
        report[ "directory" ] = "repaired"
    for name, password in values.items():
        path = os.path.join( directory, name )
        state = _state( path, password, group_id )
        if state == "ok":
            report[ name ] = "unchanged"
            continue
        temp = path + ".new"
        if os.path.lexists( temp ): os.unlink( temp )
        # Created at 0440 and exclusively, so the password is never in a file others can read or in a followed link.
        with os.fdopen( os.open( temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, MODE ), "w" ) as handle: handle.write( password + "\n" )
        os.chmod( temp, MODE )
        chown( temp, 0, group_id )
        os.replace( temp, path )
        report[ name ] = "written" if state == "absent" else "repaired"
    return report


def _dir_gaps( directory, group_id ):
    """Return the lines saying how the directory differs from mode 0750 and owner root:group_id."""
    gaps  = [ ]
    mode  = stat.S_IMODE( os.stat( directory ).st_mode )
    owner = _owner_of( directory )
    if mode != DIR_MODE: gaps.append( f"secret directory {directory} has mode {mode:04o}, expected {DIR_MODE:04o}" )
    if owner != ( 0, group_id ): gaps.append( f"secret directory {directory} is owned by {owner[ 0 ]}:{owner[ 1 ]}, expected 0:{group_id}" )
    return gaps


def _state( path, password, group_id ):
    """Return "ok", "absent" or "wrong" for one file against its value, mode and owner."""
    if not os.path.lexists( path ): return "absent"
    if os.path.islink( path ): return "wrong"
    if stat.S_IMODE( os.stat( path ).st_mode ) != MODE: return "wrong"
    if _owner_of( path ) != ( 0, group_id ): return "wrong"
    try:
        return "ok" if _read_text( path ).strip() == password else "wrong"
    except OSError:
        return "wrong"


def unsearchable( directory ):
    """
    Say whether this login cannot search an existing directory.

    Ensures:
        - True only for an existing directory without search permission for this login
        - False for a missing directory (its files are absent, which a check can say) and a searchable one
    """
    return os.path.isdir( directory ) and not os.access( directory, os.X_OK )


def check_files( directory, values=None, group_id=GROUP_ID ):
    """
    List every gap in the secret files, read-only.

    Requires:
        - values, when given, is { file name: password } to compare each file's content with

    Ensures:
        - returns ( gaps, notes ), both lists of lines; only gaps make a check fail
        - a gap is a file that is absent, a link, empty, not mode 0440, not owned by root:group_id,
          or holding a password other than the given one
        - the first gap-line set ends with one remedy line
        - a file this login cannot read is a note, not a gap: the service group may read it and a seat may not
        - the content is compared only when values is given, and a note says so when it is not
        - a directory that is not mode 0750 and owner root:group_id is a gap too
        - a directory this login cannot search gives one note and no gap: the files cannot be seen, which is
          not the same as absent
        - never raises and prints no password
    """
    gaps, notes = [ ], [ ]
    if unsearchable( directory ):
        notes.append( f"note: {directory} cannot be searched by this login, so the secret files were not checked; run this as root or as a member of group {group_id}" )
        return gaps, notes
    if os.path.isdir( directory ): gaps.extend( _dir_gaps( directory, group_id ) )
    for name in FILE_NAMES:
        path = os.path.join( directory, name )
        if not os.path.lexists( path ):
            gaps.append( f"secret file {path} is absent" )
            continue
        if os.path.islink( path ):
            gaps.append( f"secret file {path} is a link" )
            continue
        mode  = stat.S_IMODE( os.stat( path ).st_mode )
        owner = _owner_of( path )
        if mode != MODE: gaps.append( f"secret file {path} has mode {mode:04o}, expected {MODE:04o}" )
        if owner != ( 0, group_id ): gaps.append( f"secret file {path} is owned by {owner[ 0 ]}:{owner[ 1 ]}, expected 0:{group_id}" )
        try:
            content = _read_text( path ).strip()
        except OSError:
            notes.append( f"note: secret file {path} cannot be read by this login, so its content was not checked" )
            continue
        if not content: gaps.append( f"secret file {path} is empty" )
        elif values is not None and content != values[ name ]: gaps.append( f"secret file {path} does not hold the password of the given password file" )
    if values is None: notes.append( "note: no password files were given, so the content of the secret files was not compared" )
    if gaps: gaps.append( f"remedy: sudo python -m cosa.utils.db_roles --secrets-dir {directory} --apply, with the three password files and --psql" )
    return gaps, notes
