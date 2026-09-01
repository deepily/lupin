"""
Tests for the checked-hash mechanical control (row 9b5b97de, decision f313fc2d).

🔴 THE NEGATIVE CONTROL IS THE POINT OF THIS FILE, not a courtesy at the end of it.
The row that commissioned this control says so in as many words: "a check that cannot fail is
this fleet's defect of the day — do not add another." So the end-to-end tests here are
written as A/B PAIRS in subprocesses: the same package, the same same-size same-second edit,
once WITHOUT the control and once WITH it. The unpatched arm must serve stale bytecode. If it
ever stops doing so, this whole file is measuring nothing, and the pair says so out loud
rather than quietly going green.

Subprocesses are not a stylistic choice either. The defect is CROSS-PROCESS — a fresh
interpreter reads the stale pyc off disk — so an in-process test cannot observe it at all.
"""

import json
import os
import struct
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from cosa.utils import checked_hash_pyc as chp


# ── header-level unit coverage ────────────────────────────────────────────────────────

def _pyc_bytes( flags ):
    return b"\x00" * 4 + struct.pack( "<I", flags ) + b"\x00" * 8 + b"CODE"


def test_pyc_mode_names_all_three_modes_from_bytes():
    assert chp.pyc_mode( _pyc_bytes( 0b11 ) ) == "checked-hash"
    assert chp.pyc_mode( _pyc_bytes( 0b01 ) ) == "unchecked-hash"
    assert chp.pyc_mode( _pyc_bytes( 0b00 ) ) == "timestamp"


def test_pyc_mode_distinguishes_unchecked_hash_from_timestamp():
    """
    Unchecked-hash is NEVER revalidated, so it is worse than timestamp, not a milder form of
    it. Collapsing the two is the exact defect Tiberius found in the shell verifier's failure
    sentence, so it gets its own test rather than riding on the table above.
    """
    assert chp.pyc_mode( _pyc_bytes( 0b01 ) ) != chp.pyc_mode( _pyc_bytes( 0b00 ) )


def test_pyc_mode_reads_a_path( tmp_path ):
    target = tmp_path / "x.pyc"
    target.write_bytes( _pyc_bytes( 0b11 ) )
    assert chp.pyc_mode( str( target ) ) == "checked-hash"


def test_pyc_mode_reports_unreadable_rather_than_raising( tmp_path ):
    assert chp.pyc_mode( str( tmp_path / "absent.pyc" ) ) == "unreadable"
    assert chp.pyc_mode( b"\x00\x00" )                    == "unreadable"


def test_to_checked_hash_leaves_the_code_object_byte_identical():
    """
    The swap must touch bytes 4:16 and nothing else — that is what makes it safe to do
    without an unmarshal/remarshal round trip.
    """
    original  = _pyc_bytes( 0b00 )
    converted = chp.to_checked_hash( original, b"def f(): pass\n" )
    assert chp.pyc_mode( converted ) == "checked-hash"
    assert bytes( converted[ 16: ] ) == bytes( original[ 16: ] )
    assert bytes( converted[ :4 ] )  == bytes( original[ :4 ] )
    assert len( converted )          == len( original )


def test_to_checked_hash_is_a_no_op_on_short_data_and_on_hash_based_data():
    assert chp.to_checked_hash( b"\x00\x01", b"src" )         == b"\x00\x01"
    already = _pyc_bytes( 0b11 )
    assert chp.to_checked_hash( already, b"src" )             is already


def test_to_checked_hash_hashes_the_source_it_is_given():
    """Two different sources must produce two different header hashes."""
    a = chp.to_checked_hash( _pyc_bytes( 0b00 ), b"one" )
    b = chp.to_checked_hash( _pyc_bytes( 0b00 ), b"two" )
    assert bytes( a[ 8:16 ] ) != bytes( b[ 8:16 ] )


# ── scope ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "path, roots, expected", [
    ( "/repo/src/a.py",                 ( "/repo/src", ), True  ),
    ( "/repo/other/a.py",               ( "/repo/src", ), False ),
    ( "/repo/src/cosa/.venv/pkg/a.py",  ( "/repo/src", ), False ),
    ( "/repo/x/site-packages/a.py",     (),               False ),
    ( "/anywhere/a.py",                 (),               True  ),
    ( "/repo/src/",                     ( "/repo/src/", ), False ),
] )
def test_in_scope_honours_roots_and_excludes_vendored_trees( path, roots, expected ):
    assert chp._in_scope( path, roots ) is expected


def test_in_scope_returns_false_rather_than_raising_on_a_bad_path():
    assert chp._in_scope( None, ( "/repo/src", ) ) is False


# ── install / uninstall ───────────────────────────────────────────────────────────────

@pytest.fixture
def clean_install():
    """Guarantee the interpreter is left unpatched no matter how a test exits."""
    chp.uninstall()
    yield
    chp.uninstall()


def test_install_is_idempotent_and_uninstall_restores( clean_install ):
    import importlib._bootstrap_external as bootstrap
    before = bootstrap.SourceFileLoader.__dict__[ "_cache_bytecode" ]

    assert chp.install( roots=[] )  is True     # newly installed
    assert chp.is_installed()       is True
    assert chp.install( roots=[] )  is chp.ALREADY_INSTALLED   # not installed twice
    assert bootstrap.SourceFileLoader.__dict__[ "_cache_bytecode" ] is not before

    assert chp.uninstall()          is True
    assert chp.is_installed()       is False
    assert bootstrap.SourceFileLoader.__dict__[ "_cache_bytecode" ] is before
    assert chp.uninstall()          is False    # nothing left to remove


@pytest.mark.parametrize( "outcome", [ chp.ALREADY_INSTALLED, chp.UNSUPPORTED_INTERPRETER ] )
def test_a_non_install_outcome_refuses_to_be_a_boolean_and_names_the_verb_that_answers( outcome ):
    """
    🔴 THE CONFLATION GUARD, and it must RAISE rather than pick a side.

    `install()` answers "did THIS call newly install the patch?"; `is_installed()`
    answers "is the patch ACTIVE?". For a caller who meant the second,
    ALREADY_INSTALLED is a SUCCESS — so every truthiness answer is wrong for
    somebody, and a quiet one rebuilds the original defect one level out. Ruled by
    Mr Radio 🦉 2026-08-31: raise, and name the verb that answers the other question.

    The message is asserted, not just the exception type. A TypeError that does not
    say what to call instead leaves the caller exactly as stuck as a silent False.
    """
    with pytest.raises( TypeError ) as caught:
        bool( outcome )

    assert "is_installed()" in str( caught.value ), (
        f"the refusal must name the verb that answers 'is the patch active?', "
        f"or it tells the caller they are wrong without telling them what is "
        f"right.\ngot: {caught.value}"
    )
    assert str( outcome ) in str( caught.value ), (
        f"the refusal must name WHICH outcome it refused.\ngot: {caught.value}"
    )


def test_a_non_install_outcome_is_still_a_usable_string():
    """
    The other half: only the implicit bool is refused. These values stay printable
    and comparable, because a value you cannot put in a log message is a worse
    answer than the False it replaced.
    """
    assert str( chp.ALREADY_INSTALLED )       == "already-installed"
    assert chp.ALREADY_INSTALLED              != chp.UNSUPPORTED_INTERPRETER
    assert f"{chp.UNSUPPORTED_INTERPRETER}"   == "unsupported-interpreter"


def test_the_newly_installed_path_still_returns_a_real_bool( clean_install ):
    """
    The refusal must not reach the SUCCESS path. `install()` returns a genuine
    True when it newly installs, so `if install():` keeps working for the caller
    whose question really was "did I install it?".
    """
    result = chp.install( roots=[] )

    assert result is True
    assert bool( result ) is True          # must NOT raise on this path


def test_install_patches_the_concrete_class_not_the_shadowed_base( clean_install ):
    """
    🔴 THE REGRESSION GUARD FOR THE FIRST CUT'S DEFECT. SourceFileLoader defines its OWN
    _cache_bytecode, shadowing SourceLoader's. A patch on the base reports a clean install
    and is never called — measured, and it is why this assertion names both classes.
    """
    import importlib._bootstrap_external as bootstrap
    base_before = bootstrap.SourceLoader.__dict__[ "_cache_bytecode" ]
    chp.install( roots=[] )
    assert "_cache_bytecode" in bootstrap.SourceFileLoader.__dict__
    assert bootstrap.SourceLoader.__dict__[ "_cache_bytecode" ] is base_before


def test_install_reports_an_unsupported_interpreter_when_the_machinery_differs( monkeypatch, clean_install ):
    import importlib._bootstrap_external as bootstrap

    class _Unpatchable:
        __dict__ = {}                       # no _cache_bytecode to capture

    monkeypatch.setattr( bootstrap, "SourceFileLoader", _Unpatchable, raising=True )
    assert chp.install( roots=[] ) is chp.UNSUPPORTED_INTERPRETER
    assert chp.is_installed()      is False


def test_install_reports_an_unsupported_interpreter_when_the_patch_cannot_be_applied( monkeypatch, clean_install ):
    """
    The class HAS the method to capture, so install() gets past the lookup, and then the
    assignment itself is refused. An earlier cut of this test declared `__dict__` as a class
    attribute, which a class body silently ignores — so the lookup raised KeyError and the
    test passed on the WRONG branch, one `return False` too early. It measured nothing about
    a failed assignment, which is the whole thing it is named for.
    """
    import importlib._bootstrap_external as bootstrap

    class _Meta( type ):
        def __setattr__( cls, name, value ): raise TypeError( "immutable" )

    class _Immutable( metaclass=_Meta ):
        def _cache_bytecode( self, source_path, cache_path, data ): pass

    assert "_cache_bytecode" in _Immutable.__dict__, "the lookup must SUCCEED for this test to mean anything"
    monkeypatch.setattr( bootstrap, "SourceFileLoader", _Immutable, raising=True )
    assert chp.install( roots=[] ) is chp.UNSUPPORTED_INTERPRETER
    assert chp.is_installed()      is False


def test_uninstall_reports_false_when_restoration_fails( monkeypatch, clean_install ):
    import importlib._bootstrap_external as bootstrap
    chp.install( roots=[] )

    class _Meta( type ):
        def __setattr__( cls, name, value ): raise TypeError( "immutable" )

    class _Immutable( metaclass=_Meta ): pass

    monkeypatch.setattr( bootstrap, "SourceFileLoader", _Immutable, raising=True )
    assert chp.uninstall() is False


def test_converted_count_is_reported( clean_install ):
    assert chp.converted_count() >= 0


# ── the patched write path, exercised IN-PROCESS ──────────────────────────────────────
#
# The end-to-end tests below drive this closure through real imports, but those run in
# SUBPROCESSES — which is the only way to observe a cross-process defect, and also the reason
# coverage never sees the closure's body. These call it directly so every branch of the
# funnel is measured in the process doing the measuring.

class _FakeLoader:
    """Stands in for SourceFileLoader: the patch only ever asks it for the source bytes."""

    def __init__( self, source=b"def f(): pass\n", explode=False ):
        self.source  = source
        self.explode = explode
        self.written = None

    def get_data( self, path ):
        if self.explode: raise OSError( "unreadable source" )
        return self.source


@pytest.fixture
def patched_write( clean_install ):
    """Install, and hand back the patched function plus a recorder for what reached disk."""
    import importlib._bootstrap_external as bootstrap
    seen = {}

    original = bootstrap.SourceFileLoader.__dict__[ "_cache_bytecode" ]

    def _spy( self, source_path, cache_path, data ):
        seen[ "data" ] = bytes( data )

    bootstrap.SourceFileLoader._cache_bytecode = _spy
    try:
        chp.install( roots=[] )
        yield bootstrap.SourceFileLoader.__dict__[ "_cache_bytecode" ], seen
    finally:
        chp.uninstall()
        bootstrap.SourceFileLoader._cache_bytecode = original


def test_patched_write_converts_a_timestamp_pyc_in_scope( patched_write ):
    write, seen = patched_write
    before = chp.converted_count()
    write( _FakeLoader(), "/repo/src/a.py", "/repo/src/__pycache__/a.pyc", _pyc_bytes( 0b00 ) )
    assert chp.pyc_mode( seen[ "data" ] ) == "checked-hash"
    assert chp.converted_count() == before + 1


def test_patched_write_passes_an_already_hash_based_pyc_straight_through( patched_write ):
    write, seen = patched_write
    before = chp.converted_count()
    payload = _pyc_bytes( 0b11 )
    write( _FakeLoader(), "/repo/src/a.py", "/x.pyc", payload )
    assert seen[ "data" ] == payload
    assert chp.converted_count() == before, "an untouched write must not count as converted"


def test_patched_write_counts_nothing_when_the_swap_declines_a_truncated_pyc( patched_write ):
    """
    An 8-byte buffer reads as "timestamp" (its flags word is zero) but is too short to carry
    a 16-byte header, so to_checked_hash returns it untouched. The counter must NOT move —
    otherwise the install's receipt would report conversions it never made.
    """
    write, seen = patched_write
    before   = chp.converted_count()
    truncated = b"\x00" * 4 + struct.pack( "<I", 0 )
    write( _FakeLoader(), "/repo/src/a.py", "/x.pyc", truncated )
    assert seen[ "data" ] == truncated
    assert chp.converted_count() == before


def test_patched_write_leaves_out_of_scope_paths_alone( clean_install ):
    import importlib._bootstrap_external as bootstrap
    seen = {}
    original = bootstrap.SourceFileLoader.__dict__[ "_cache_bytecode" ]
    bootstrap.SourceFileLoader._cache_bytecode = lambda self, s, c, d: seen.__setitem__( "data", bytes( d ) )
    try:
        chp.install( roots=[ "/repo/src" ] )
        write = bootstrap.SourceFileLoader.__dict__[ "_cache_bytecode" ]
        write( _FakeLoader(), "/somewhere/else/a.py", "/x.pyc", _pyc_bytes( 0b00 ) )
        assert chp.pyc_mode( seen[ "data" ] ) == "timestamp"
    finally:
        chp.uninstall()
        bootstrap.SourceFileLoader._cache_bytecode = original


def test_patched_write_fails_open_when_the_source_cannot_be_read( patched_write ):
    """
    🔴 THE FAIL-OPEN BRANCH, measured in-process. An unreadable source must degrade to
    CPython's own bytes — the status quo — never to a raised exception, because from a
    sitecustomize this runs inside every interpreter start in the repo.
    """
    write, seen = patched_write
    payload = _pyc_bytes( 0b00 )
    write( _FakeLoader( explode=True ), "/repo/src/a.py", "/x.pyc", payload )
    assert seen[ "data" ] == payload
    assert chp.pyc_mode( seen[ "data" ] ) == "timestamp"


def test_patched_write_defaults_its_roots_from_the_environment( monkeypatch, tmp_path ):
    """install() with roots=None must resolve scope from LUPIN_ROOT rather than owning everything."""
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    import importlib._bootstrap_external as bootstrap
    seen = {}
    original = bootstrap.SourceFileLoader.__dict__[ "_cache_bytecode" ]
    bootstrap.SourceFileLoader._cache_bytecode = lambda self, s, c, d: seen.__setitem__( "data", bytes( d ) )
    try:
        chp.uninstall()
        assert chp.install() is True
        write = bootstrap.SourceFileLoader.__dict__[ "_cache_bytecode" ]
        write( _FakeLoader(), str( tmp_path / "src" / "a.py" ), "/x.pyc", _pyc_bytes( 0b00 ) )
        assert chp.pyc_mode( seen[ "data" ] ) == "checked-hash"
    finally:
        chp.uninstall()
        bootstrap.SourceFileLoader._cache_bytecode = original


# ── roots / actor / ledger ────────────────────────────────────────────────────────────

def test_default_roots_is_empty_without_lupin_root( monkeypatch ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    assert chp._default_roots() == ()


def test_default_roots_points_at_src_when_lupin_root_is_set( monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    assert chp._default_roots() == ( str( tmp_path / "src" ), )


def test_actor_names_the_session_when_there_is_one( monkeypatch ):
    monkeypatch.setenv( "USER", "rruiz" )
    monkeypatch.setenv( "CLAUDE_CODE_SESSION_ID", "9c88c030-b353-4973" )
    assert chp.actor() == "rruiz/9c88c030"


def test_actor_falls_back_to_the_unix_user_alone( monkeypatch ):
    monkeypatch.setenv( "USER", "rruiz" )
    monkeypatch.delenv( "CLAUDE_CODE_SESSION_ID", raising=False )
    assert chp.actor() == "rruiz"


def test_actor_never_returns_empty( monkeypatch ):
    monkeypatch.delenv( "USER", raising=False )
    monkeypatch.delenv( "CLAUDE_CODE_SESSION_ID", raising=False )
    assert chp.actor() == "unknown"


def test_ledger_path_is_none_without_a_resolvable_root( monkeypatch ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    assert chp.ledger_path() is None


def test_ledger_path_lands_under_the_gitignored_io_tree( tmp_path ):
    assert chp.ledger_path( str( tmp_path ) ) == str( tmp_path / "io" / "pyc-mode-ledger.jsonl" )


def test_record_appends_one_parseable_line_per_call( tmp_path, monkeypatch ):
    monkeypatch.setenv( "USER", "rruiz" )
    monkeypatch.setenv( "CLAUDE_CODE_SESSION_ID", "9c88c030" )

    assert chp.record( "convert", { "checked-hash": 2417 }, "after purge", root=str( tmp_path ) )
    assert chp.record( "census",  { "timestamp": 1 },       "drifted",     root=str( tmp_path ) )

    lines = ( tmp_path / "io" / "pyc-mode-ledger.jsonl" ).read_text().strip().splitlines()
    assert len( lines ) == 2
    first = json.loads( lines[ 0 ] )
    assert first[ "event" ]  == "convert"
    assert first[ "actor" ]  == "rruiz/9c88c030"
    assert first[ "counts" ] == { "checked-hash": 2417 }
    assert first[ "pid" ]    == os.getpid()
    assert first[ "ts" ]


def test_record_defaults_its_optional_fields( tmp_path ):
    chp.record( "census", root=str( tmp_path ) )
    entry = json.loads( ( tmp_path / "io" / "pyc-mode-ledger.jsonl" ).read_text().strip() )
    assert entry[ "counts" ] == {}
    assert entry[ "note" ]   == ""


def test_record_returns_none_rather_than_raising_when_it_cannot_write( monkeypatch ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    assert chp.record( "convert" ) is None


def test_record_swallows_a_write_failure( tmp_path, monkeypatch ):
    blocker = tmp_path / "io"
    blocker.write_text( "I am a file, not a directory" )
    assert chp.record( "convert", root=str( tmp_path ) ) is None


# ── census ────────────────────────────────────────────────────────────────────────────

def _write_pyc( directory, name, flags ):
    directory.mkdir( parents=True, exist_ok=True )
    ( directory / name ).write_bytes( _pyc_bytes( flags ) )


def test_census_counts_this_interpreters_pycs_and_names_offenders( tmp_path ):
    tag   = f"cpython-{sys.version_info.major}{sys.version_info.minor}"
    cache = tmp_path / "pkg" / "__pycache__"
    _write_pyc( cache, f"good.{tag}.pyc",      0b11 )
    _write_pyc( cache, f"drifted.{tag}.pyc",   0b00 )
    _write_pyc( cache, f"unchecked.{tag}.pyc", 0b01 )

    counts, offenders = chp.census( [ str( tmp_path ) ] )
    assert counts == { "checked-hash": 1, "timestamp": 1, "unchecked-hash": 1 }
    assert len( offenders ) == 2
    assert all( "good." not in o for o in offenders )


def test_census_ignores_other_interpreters_and_pytest_rewritten_and_vendored( tmp_path ):
    """
    Three populations compileall neither owns nor can convert. Folding any of them into the
    verdict would make the gate permanently red and therefore ignored.
    """
    tag   = f"cpython-{sys.version_info.major}{sys.version_info.minor}"
    cache = tmp_path / "pkg" / "__pycache__"
    _write_pyc( cache, f"mine.{tag}.pyc",              0b11 )
    _write_pyc( cache, "old.cpython-310.pyc",          0b00 )
    _write_pyc( cache, f"t.{tag}-pytest-8.4.2.pyc",    0b00 )
    _write_pyc( tmp_path / ".venv" / "v" / "__pycache__", f"vendor.{tag}.pyc", 0b00 )

    counts, offenders = chp.census( [ str( tmp_path ) ] )
    assert counts    == { "checked-hash": 1 }
    assert offenders == []


def test_census_skips_an_unwalkable_root_rather_than_dying( tmp_path ):
    counts, offenders = chp.census( [ None, str( tmp_path ) ] )
    assert counts == {} and offenders == []


# ── END-TO-END A/B: the negative control ──────────────────────────────────────────────

_VICTIM = "def answer(): return 3\n"


def _build_tree( root ):
    pkg = root / "pkg"
    pkg.mkdir( parents=True, exist_ok=True )
    ( pkg / "__init__.py" ).write_text( "" )
    ( pkg / "victim.py"   ).write_text( _VICTIM )
    return pkg


def _run( root, code ):
    env = dict( os.environ, PYTHONPATH=f"{root}{os.pathsep}{Path( chp.__file__ ).parents[ 2 ]}" )
    return subprocess.run( [ sys.executable, "-c", textwrap.dedent( code ) ],
                           cwd=str( root ), capture_output=True, text=True, env=env )


def _install_prologue( roots="[]" ):
    """
    Build the child-side lines that make the patch's SCOPE explicit.

    ⚠️ THE `uninstall()` IS NOT REDUNDANT, and this is ONE function so there is one
    place to forget it rather than four. `src/sitecustomize.py` installs the patch at
    interpreter startup in EVERY process — these children included — using the DEFAULT
    roots derived from `LUPIN_ROOT`. A child that simply calls `install( roots=... )`
    therefore gets `ALREADY_INSTALLED` back and silently keeps the INHERITED scope,
    which does not contain `tmp_path`.

    Measured 2026-08-31 in one child, three ways: with `LUPIN_ROOT` set,
    `converted_count()` reads 0; with it unset it reads 2; importing the module with no
    shim on the path installs cleanly and reads 2. That is a test whose result is
    decided by the ambient environment rather than by the code under test, and it is
    the same "a no-op and a failure return the same answer" shape this row exists for.

    Requires:
        - roots is the literal SOURCE TEXT of the roots argument, not a list object

    Ensures:
        - returns child source leaving the patch installed with exactly `roots` in scope
        - binds `chp` for the caller's body
        - asserts the install was this child's own, so an inherited one cannot pass

    Raises:
        - None
    """
    return ( "from cosa.utils import checked_hash_pyc as chp\n"
             "chp.uninstall()\n"
             f"assert chp.install( roots={roots} ) is True\n" )


def _run_patched( root, body, roots="[]" ):
    """
    Run `body` in a child whose patch scope is stated rather than inherited.

    Requires:
        - body is child source, indented or not

    Ensures:
        - returns the CompletedProcess from `_run`

    Raises:
        - None
    """
    return _run( root, _install_prologue( roots ) + textwrap.dedent( body ) )


def _seed( root, patched ):
    out = _run( root, ( _install_prologue() if patched else "" ) + "import pkg.victim" )
    assert out.returncode == 0, out.stderr
    return root / "pkg" / "__pycache__" / f"victim.cpython-{sys.version_info.major}{sys.version_info.minor}.pyc"


def _mutate_same_size_same_second( root ):
    victim = root / "pkg" / "victim.py"
    before = victim.stat()
    victim.write_text( _VICTIM.replace( "return 3", "return 9" ) )
    assert len( victim.read_text() ) == len( _VICTIM ), "the mutation must not change size"
    os.utime( victim, ( before.st_atime, before.st_mtime ) )


@pytest.mark.parametrize( "patched, expected_mode, expected_seen", [
    ( False, "timestamp",    "3" ),      # NEGATIVE CONTROL — must serve STALE bytecode
    ( True,  "checked-hash", "9" ),      # the control — must see the edit
] )
def test_end_to_end_the_control_sees_a_same_size_same_second_edit_and_the_unpatched_arm_does_not(
        tmp_path, patched, expected_mode, expected_seen ):
    """
    The A/B pair that gives this file its meaning.

    The `patched=False` row is the NEGATIVE CONTROL and it is REQUIRED to fail in the
    interesting way: a fresh interpreter must serve bytecode compiled from source that no
    longer exists on disk. Should that row ever start reporting "9", the defect has gone away
    on its own or the fixture has stopped reproducing it, and the `patched=True` row proves
    nothing — so it is asserted, not merely observed.

    Measured 2026-08-30 on CPython 3.13.7:
        unpatched  cache=timestamp      source says 9, interpreter sees 3
        patched    cache=checked-hash   source says 9, interpreter sees 9
    """
    _build_tree( tmp_path )
    pyc = _seed( tmp_path, patched )
    assert chp.pyc_mode( str( pyc ) ) == expected_mode

    _mutate_same_size_same_second( tmp_path )

    out = _run( tmp_path, "import pkg.victim; print( pkg.victim.answer() )" )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == expected_seen


def test_end_to_end_the_control_covers_a_first_time_import_which_is_the_load_bearing_case( tmp_path ):
    """
    Item #2 from decision f313fc2d, the one the row calls load-bearing: a correctly converted
    tree drifts through ORDINARY FIRST-TIME IMPORTS, with nobody purging anything. A control
    that only guards purges answers the easy half. This asserts the hard half directly — no
    prior pyc exists, so there is no mode to inherit, and stock CPython writes timestamp.
    """
    _build_tree( tmp_path )
    assert not list( ( tmp_path / "pkg" ).glob( "__pycache__/*.pyc" ) ), "must be a virgin cache"

    pyc = _seed( tmp_path, patched=True )
    assert chp.pyc_mode( str( pyc ) ) == "checked-hash"


def test_end_to_end_the_control_reports_what_it_actually_converted( tmp_path ):
    """A receipt, not a claim: the install must be able to say how many writes it rewrote."""
    _build_tree( tmp_path )
    out = _run_patched( tmp_path, """
        import pkg.victim
        print( chp.converted_count() )
    """ )
    assert out.returncode == 0, out.stderr
    assert int( out.stdout.strip() ) >= 2          # pkg/__init__ and pkg/victim


def test_end_to_end_a_failure_inside_the_patch_falls_through_to_stock_behaviour( tmp_path ):
    """
    🔴 FAIL-OPEN IS THE PRICE OF THE SITECUSTOMIZE PLACEMENT, so it is tested rather than
    asserted in a comment. With the hash step sabotaged, the import must still SUCCEED and
    the pyc must still be written — degrading to exactly the drift this control improves on,
    never to a broken interpreter.
    """
    _build_tree( tmp_path )
    out = _run_patched( tmp_path, """
        def _boom( *a, **k ): raise RuntimeError( "sabotage" )
        chp.to_checked_hash = _boom
        import pkg.victim
        print( "IMPORT_OK", pkg.victim.answer() )
    """ )
    assert out.returncode == 0, out.stderr
    assert "IMPORT_OK 3" in out.stdout


def test_end_to_end_out_of_scope_writes_are_left_alone( tmp_path ):
    """
    The control owns repo source, not the world. A root it was not given must be untouched,
    so installing it never silently rewrites vendored or stdlib bytecode.
    """
    _build_tree( tmp_path )
    out = _run_patched( tmp_path, """
        import pkg.victim
        print( chp.converted_count() )
    """, roots='[ "/nonexistent/elsewhere" ]' )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "0"
    pyc = tmp_path / "pkg" / "__pycache__" / f"victim.cpython-{sys.version_info.major}{sys.version_info.minor}.pyc"
    assert chp.pyc_mode( str( pyc ) ) == "timestamp"


# ── the CLI that produces the trace ───────────────────────────────────────────────────

def test_main_reports_clean_and_writes_a_ledger_line( tmp_path, monkeypatch, capsys ):
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    tag = f"cpython-{sys.version_info.major}{sys.version_info.minor}"
    _write_pyc( tmp_path / "src" / "__pycache__", f"ok.{tag}.pyc", 0b11 )

    assert chp.main( [ str( tmp_path / "src" ) ] ) == 0
    out = capsys.readouterr().out
    assert "checked-hash=1" in out
    entry = json.loads( ( tmp_path / "io" / "pyc-mode-ledger.jsonl" ).read_text().strip() )
    assert entry[ "event" ]  == "census"
    assert entry[ "counts" ] == { "checked-hash": 1 }
    assert entry[ "note" ]   == "offenders=0"


def test_main_returns_one_and_names_offenders_on_a_drifted_tree( tmp_path, monkeypatch, capsys ):
    """
    🔴 THE NEGATIVE CONTROL FOR THE CHECK ITSELF. A check that cannot go red is worse than no
    check, because it reports safety it never measured. This drifts the tree on purpose and
    requires a non-zero exit AND the offending path named.
    """
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    tag = f"cpython-{sys.version_info.major}{sys.version_info.minor}"
    _write_pyc( tmp_path / "src" / "__pycache__", f"drifted.{tag}.pyc", 0b00 )

    assert chp.main( [ str( tmp_path / "src" ) ] ) == 1
    out = capsys.readouterr().out
    assert "timestamp=1" in out
    assert "drifted." in out


def test_main_defaults_its_roots_from_lupin_root( tmp_path, monkeypatch, capsys ):
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    ( tmp_path / "src" ).mkdir()
    assert chp.main() == 0
    assert str( tmp_path / "src" ) in capsys.readouterr().out


def test_main_refuses_rather_than_scanning_the_world_with_no_roots( monkeypatch, capsys ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    assert chp.main( [] ) == 1
    assert "no roots to scan" in capsys.readouterr().out


def test_main_says_so_when_the_ledger_cannot_be_written( tmp_path, monkeypatch, capsys ):
    """A trace that silently fails to record is worse than none — it looks like evidence."""
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    ( tmp_path / "src" ).mkdir()
    assert chp.main( [ str( tmp_path / "src" ) ] ) == 0
    assert "ledger: NOT WRITTEN" in capsys.readouterr().out
