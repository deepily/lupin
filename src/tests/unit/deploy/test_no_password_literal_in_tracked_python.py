"""
No password-shaped LITERAL survives in tracked Python — companion to row `856882e4`.

THE DEFECT THIS EXISTS TO CATCH
-------------------------------
`856882e4` converted the compose files, and `test_compose_no_plaintext_password_literal.py`
holds that surface. But the same literal went on living in Python, as the default arm of
`os.environ.get( "DB_PASSWORD", ... )` and as an inline connection URL. A literal on the
tip of a PUBLIC repo is committed whether or not anything reads it, so removing it from
compose alone left the tree still carrying it.

WHY A SECOND FILE RATHER THAN A CASE IN THE FIRST: the compose test scans three named
files with a `*_PASSWORD:` assignment regex. Python carries the value in shapes that
regex cannot see — a positional second argument to `os.environ.get`, a substring of a
`postgresql://user:pw@host` URL, a dict value, a line of prose in a docstring. The only
scan that catches all of those is a plain substring sweep over every tracked `.py`.

WHAT IT ASSERTS
---------------
The literal appears in NO tracked Python file. Docstrings and comments are scanned too,
for the same reason the compose test scans commented-out lines.

THE LITERAL IS ASSEMBLED FROM FRAGMENTS BELOW, deliberately, so that this file does not
itself contain the string it bans. Without that, the guard would either have to exempt
itself — and an exempt file is where the next literal lands — or fail forever on its
own source.

Venue: :7999-eligible. Pure file reads; no docker, no network, no DB.
"""
import os
import subprocess

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()

# Assembled, never written whole — see the module docstring.
BANNED_LITERAL = "dev_" + "password"

# The fail-loud shape that replaces it. Named here so the failure message can point at
# a form rather than just forbid a string.
REMEDY = (
    'read it with os.environ.get( "DB_PASSWORD" ) and raise when it is missing, '
    "the way the cloud branch of cosa/rest/db/database.py already does; the value "
    "belongs in the UNTRACKED .env beside docker-compose.yml"
)


def _tracked_python_files():
    """
    Every tracked `.py` path in the repository, relative to the project root.

    Requires:
        - PROJECT_ROOT is a git working tree

    Ensures:
        - returns paths git currently tracks, so untracked scratch files and
          ignored trees are out of scope
        - returns [] if git is unavailable, which the guard test turns into a skip
          rather than a false green

    Raises:
        - None
    """
    try:
        out = subprocess.run(
            [ "git", "-C", PROJECT_ROOT, "ls-files", "*.py" ],
            capture_output=True, text=True, timeout=60
        )
    except ( OSError, subprocess.SubprocessError ):
        return []
    if out.returncode != 0: return []
    return [ line for line in out.stdout.splitlines() if line.strip() ]


def _offenders( files=None, root=None, skipped=None ):
    """
    Every ( path, line_number ) in tracked Python carrying the banned literal.

    Ensures:
        - scans docstrings and comments as well as code
        - a non-UTF8 file is READ AS BYTES rather than skipped, so it stays in the sweep
        - a file that cannot be opened at all is skipped rather than crashing the sweep,
          and is recorded in `skipped` so the omission is visible (row 5c3f3d94)
        - the files/root arguments exist so the sweep can be driven against a
          throwaway tree in BOTH directions, clean and dirty
    """
    found = []
    root  = PROJECT_ROOT if root is None else root
    for rel in ( _tracked_python_files() if files is None else files ):
        path = os.path.join( root, rel )
        try:
            with open( path, "rb" ) as f:
                raw = f.read()
        except OSError as e:
            # Cannot be opened at all. Skip so one bad path cannot take the guard down —
            # but record it, because a file this sweep never read is a file it never cleared.
            if skipped is not None: skipped.append( f"{rel}: {type( e ).__name__}: {e}" )
            continue

        # Decode permissively rather than skipping. A non-UTF8 file used to drop OUT of a
        # SECURITY sweep entirely; you cannot certify a file you refused to read. Line
        # numbering is preserved because replacement never removes a newline.
        for n, line in enumerate( raw.decode( "utf-8", errors="replace" ).splitlines(), start=1 ):
            if BANNED_LITERAL in line: found.append( ( rel, n ) )
    return found


def test_the_sweep_can_actually_see_the_literal( tmp_path ):
    """
    CONTROL: the instrument that reports clean must be able to see what it clears.

    Puts the literal back — in a throwaway file the sweep's own reader is pointed at —
    and asserts the reader finds it. If this ever fails, the guard below is green
    because it is blind, not because the tree is clean.

    Ensures:
        - a planted line containing the literal is detected
        - a similar line without it is not
    """
    planted = tmp_path / "planted.py"
    planted.write_text( 'password = os.environ.get( "DB_PASSWORD", "%s" )\n' % BANNED_LITERAL )

    with open( planted, "r", encoding="utf-8" ) as f:
        hits = [ n for n, line in enumerate( f, start=1 ) if BANNED_LITERAL in line ]

    assert hits == [ 1 ]
    assert BANNED_LITERAL not in 'password = os.environ.get( "DB_PASSWORD" )'


def test_this_guard_does_not_contain_the_string_it_bans():
    """
    The guard must not be the one file exempted from the guard.

    The literal is assembled from fragments so this file can be scanned like any
    other. If someone ever spells it out here, the sweep starts reporting its own
    source and the next real literal hides in the noise.

    Ensures:
        - this file's own source is clean by the same test applied to the tree
    """
    with open( __file__, "r", encoding="utf-8" ) as f: source = f.read()
    assert BANNED_LITERAL not in source


@pytest.mark.xfail(
    strict = True,
    reason = (
        "HELD, NOT EXCUSED — 16 literals across 8 files are still in the tree because "
        "the fail-loud conversion (Tiffany, rows 856882e4 / 3ff9820f / b26088de) rides "
        "behind the recreate gate: a bare pytest process does not read .env, so shipping "
        "it tonight would break six workers and the VM. strict=True means this flips to a "
        "HARD FAILURE the moment the tree goes clean, which is the signal to delete this "
        "marker. It cannot rot into a permanent excuse."
    )
)
def test_no_password_literal_in_tracked_python():
    """
    The banned literal appears in no tracked Python file.

    Ensures:
        - the failure message names every file and line, so the fix is mechanical
        - a repository with no git available SKIPS rather than passing vacuously
    """
    if not _tracked_python_files():
        pytest.skip( "git ls-files returned nothing — cannot enumerate tracked Python here" )

    skipped   = [ ]
    offenders = _offenders( skipped=skipped )

    assert skipped == [ ], (
        f"{len( skipped )} tracked Python file(s) could not be opened, so this sweep never "
        f"cleared them — a file it did not read is not a file it certified:\n  "
        + "\n  ".join( skipped ) )

    assert not offenders, (
        f"{len( offenders )} plaintext password literal(s) at the tip of a PUBLIC repo:\n  "
        + "\n  ".join( f"{rel}:{n}" for rel, n in offenders )
        + f"\n{REMEDY} (rows 856882e4 / 012e35a9)."
    )


def test_the_sweep_reports_clean_on_a_tree_with_no_literal( tmp_path ):
    """
    The other direction: a clean tree comes back empty, not merely un-crashed.

    A guard that can only ever fail is as useless as one that can only ever pass.

    Ensures:
        - a file using the fail-loud form yields no offenders
        - putting the literal back into that same tree yields exactly one offender
    """
    ( tmp_path / "clean.py" ).write_text(
        'password = os.environ.get( "DB_PASSWORD" )\n'
        'if not password: raise RuntimeError( "DB_PASSWORD is not set" )\n'
    )
    assert _offenders( files=[ "clean.py" ], root=str( tmp_path ) ) == []

    # Put it back — the literal returns and the sweep must go red on it.
    ( tmp_path / "dirty.py" ).write_text( 'password = os.environ.get( "DB_PASSWORD", "%s" )\n' % BANNED_LITERAL )
    assert _offenders( files=[ "clean.py", "dirty.py" ], root=str( tmp_path ) ) == [ ( "dirty.py", 1 ) ]


def test_unreadable_and_missing_files_do_not_crash_the_sweep( tmp_path ):
    """
    A file the sweep cannot decode is skipped, never fatal.

    One undecodable file must not take down the guard for the whole tree — that
    turns a hard failure into a green by way of an error nobody reads.

    Ensures:
        - a non-UTF8 file and a missing path are skipped
        - a readable offender alongside them is still reported
    """
    ( tmp_path / "binary.py" ).write_bytes( b"\xff\xfe\x00 not utf-8 \xff" )
    ( tmp_path / "dirty.py" ).write_text( 'pw = "%s"\n' % BANNED_LITERAL )

    assert _offenders( files=[ "binary.py", "missing.py", "dirty.py" ], root=str( tmp_path ) ) == [ ( "dirty.py", 1 ) ]


def test_a_non_utf8_file_is_still_searched( tmp_path ):
    """
    The blind spot row 5c3f3d94 closed. A non-UTF8 file used to raise UnicodeDecodeError and
    drop OUT of this SECURITY sweep entirely — you cannot certify a file you refused to read.
    Reddens if the reader goes back to skipping on a decode error.

    The literal is taken from the module under test, never typed here.
    """
    payload = b"\xff\xfe garbage " + BANNED_LITERAL.encode() + b" more \xff\n"
    ( tmp_path / "binary_with_literal.py" ).write_bytes( payload )

    assert _offenders( files=[ "binary_with_literal.py" ], root=str( tmp_path ) ) == [ ( "binary_with_literal.py", 1 ) ]


def test_an_unopenable_file_is_recorded_rather_than_vanishing( tmp_path ):
    """
    A file the sweep cannot open at all is still skipped — one bad path must not take the
    guard down — but it is now RECORDED, so the omission is visible. Reddens if the skip
    goes back to being silent.
    """
    locked = tmp_path / "locked.py"
    locked.write_text( "x = 1\n" )
    locked.chmod( 0o000 )
    skipped = [ ]

    try:
        assert _offenders( files=[ "locked.py" ], root=str( tmp_path ), skipped=skipped ) == [ ]
        assert len( skipped ) == 1 and skipped[ 0 ].startswith( "locked.py: PermissionError" )
    finally:
        locked.chmod( 0o644 )


def test_tracked_file_listing_is_empty_when_git_is_unavailable( monkeypatch ):
    """
    No git means SKIP, never a vacuous green.

    Ensures:
        - a git invocation that raises yields an empty listing
        - a git invocation that returns non-zero yields an empty listing
    """
    def _raises( *a, **k ): raise OSError( "no git on this box" )
    monkeypatch.setattr( subprocess, "run", _raises )
    assert _tracked_python_files() == []

    class _Failed:
        returncode = 128
        stdout     = ""
    monkeypatch.setattr( subprocess, "run", lambda *a, **k: _Failed() )
    assert _tracked_python_files() == []
