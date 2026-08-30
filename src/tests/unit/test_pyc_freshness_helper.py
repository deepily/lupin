"""
The opt-in staleness helper works, and — the load-bearing half — the hazard it defends against is
REAL in this interpreter right now.

A test that only asserts "with the helper, the value is correct" proves nothing: it passes just as
well on a machine where the race cannot happen, and it would have passed before the helper existed.
So every test here that shows a fix is paired with a NEGATIVE CONTROL that reproduces the failure
without it. If CPython ever changes its invalidation scheme, the controls go red and this file says
so out loud rather than quietly guarding nothing.

Row `d18ce9ef`. Measurement and remedy pricing:
`src/rnd/v0.2.1/2026.08.29-stale-pyc-defeats-mutation-testing.md`.
"""

import os
import subprocess
import sys

from pathlib import Path

import pytest

REPO_ROOT = Path( __file__ ).resolve().parents[ 3 ]
if str( REPO_ROOT / "src" ) not in sys.path: sys.path.insert( 0, str( REPO_ROOT / "src" ) )

from tests.helpers.pyc_freshness import (            # noqa: E402
    bytecode_files_for,
    drop_from_sys_modules,
    mutated_source,
    refresh_source,
)


def _build_pkg( tmp_path, lane ):
    """A throwaway importable package. Never production source — a probe must not edit the tree."""
    pkg = tmp_path / "probe_pkg"
    pkg.mkdir()
    ( pkg / "__init__.py" ).write_text( "", encoding="utf-8" )
    src = pkg / "m.py"
    src.write_text( f'LANE = "{lane}"\n', encoding="utf-8" )
    return src


def _read_lane( tmp_path ):
    """Import the probe module in a FRESH interpreter and report LANE. Cross-process, on purpose."""
    out = subprocess.run(
        [ sys.executable, "-c",
          f"import sys; sys.path.insert( 0, {str( tmp_path )!r} ); "
          f"import probe_pkg.m; print( probe_pkg.m.LANE )" ],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, f"probe import failed: {out.stderr}"
    return out.stdout.strip()


def _bake_stale_pyc( src ):
    """
    Manufacture the exact hazard: a .pyc whose recorded whole second and size both match a source
    that has since changed. `touch -r` is what makes it deterministic rather than a timing gamble.
    """
    tmp_path = src.parent.parent
    src.write_text( 'LANE = "dead"\n', encoding="utf-8" )
    _read_lane( tmp_path )                                       # compile the mutant
    src.write_text( 'LANE = "todo"\n', encoding="utf-8" )        # same size as "dead"

    pycs = bytecode_files_for( src )
    assert pycs, "no .pyc was produced — this probe cannot test what it claims to test"
    stat = pycs[ 0 ].stat()
    os.utime( src, ( stat.st_atime, stat.st_mtime ) )            # same whole second
    return pycs[ 0 ]


def test_negative_control_the_race_is_real_here( tmp_path ):
    """
    THE CONTROL. Without any remedy, a fresh interpreter reports the mutant while the file on disk
    says otherwise. If this ever goes green, the rest of this file is guarding a hazard that no
    longer exists and the helper's docstring is stale.

    Ensures:
        - the source reads "todo" and a fresh import reports "dead"
    """
    src = _build_pkg( tmp_path, "todo" )
    _bake_stale_pyc( src )

    assert src.read_text() == 'LANE = "todo"\n'
    assert _read_lane( tmp_path ) == "dead", (
        "the stale-pyc race did NOT reproduce. Either CPython changed its invalidation scheme or "
        "this probe stopped manufacturing the condition — in both cases every 'the helper fixes "
        "it' assertion in this file has become vacuous and must be re-derived, not trusted."
    )


def test_refresh_source_makes_the_next_import_honest( tmp_path ):
    """
    Ensures:
        - after refresh_source, a fresh interpreter reports what the file actually says
    """
    src = _build_pkg( tmp_path, "todo" )
    _bake_stale_pyc( src )
    assert _read_lane( tmp_path ) == "dead"          # hazard armed

    refresh_source( src )

    assert _read_lane( tmp_path ) == "todo"


def test_refresh_source_removes_the_stale_bytecode( tmp_path ):
    """
    Ensures:
        - the stale .pyc is gone afterwards, so the fix is mechanical rather than incidental
    """
    src  = _build_pkg( tmp_path, "todo" )
    stale = _bake_stale_pyc( src )
    assert stale.exists()

    refresh_source( src )

    assert not stale.exists()


def test_refresh_source_moves_the_mtime_BACKWARDS_not_forwards( tmp_path ):
    """
    Direction is a correctness property, not a detail. A FORWARD bump makes the next compile record
    a timestamp already in the future, so a later honest edit inside that second is the one that
    gets swallowed — the same defect, moved.

    Ensures:
        - the mtime after refresh_source is strictly earlier than before
    """
    src    = _build_pkg( tmp_path, "todo" )
    before = src.stat().st_mtime

    refresh_source( src )

    assert src.stat().st_mtime < before


def test_mutated_source_restores_on_exit_and_the_restore_is_visible( tmp_path ):
    """
    The restore edge is the one that bit: you read the file back, see the original, and the
    interpreter still runs the mutant.

    Ensures:
        - inside the block a fresh import sees the mutation
        - after the block a fresh import sees the original
    """
    src = _build_pkg( tmp_path, "todo" )
    _read_lane( tmp_path )                            # bake an honest pyc first

    with mutated_source( src, 'LANE = "dead"\n' ):
        assert _read_lane( tmp_path ) == "dead"

    assert src.read_text() == 'LANE = "todo"\n'
    assert _read_lane( tmp_path ) == "todo"


def test_mutated_source_restores_even_when_the_block_raises( tmp_path ):
    """
    A mutation probe whose assertion fails must still hand the tree back. Otherwise one red test
    leaves production source mutated for every seat sharing the checkout.

    Ensures:
        - the original bytes are restored when the block raises
        - the exception still propagates
    """
    src = _build_pkg( tmp_path, "todo" )

    with pytest.raises( RuntimeError, match="probe blew up" ):
        with mutated_source( src, 'LANE = "dead"\n' ):
            raise RuntimeError( "probe blew up" )

    assert src.read_text() == 'LANE = "todo"\n'
    assert _read_lane( tmp_path ) == "todo"


def test_drop_from_sys_modules_takes_submodules_too( tmp_path ):
    """
    Ensures:
        - the named module and its submodules leave sys.modules
        - the removed names are reported back
    """
    sys.path.insert( 0, str( tmp_path ) )
    try:
        _build_pkg( tmp_path, "todo" )
        import probe_pkg.m                                        # noqa: F401
        assert "probe_pkg.m" in sys.modules

        removed = drop_from_sys_modules( "probe_pkg" )

        assert "probe_pkg" not in sys.modules
        assert "probe_pkg.m" not in sys.modules
        assert removed == [ "probe_pkg", "probe_pkg.m" ]
    finally:
        sys.path.remove( str( tmp_path ) )
        drop_from_sys_modules( "probe_pkg" )
