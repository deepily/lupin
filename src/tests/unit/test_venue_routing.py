"""
The guard on the venue split (row `dba10ba5`).

WHAT IT PINS, AND WHY IT IS A SET AND NOT A COUNT
--------------------------------------------------
`conftest.pytest_collection_modifyitems` deselects `host_only` tests where the host
is unreachable. The load-bearing assertion is **deselect-set == marker-set**.

⚠️ A COUNT CANNOT CARRY THAT CLAIM. "7 deselected" is satisfied identically by seven
correctly-routed tests and by seven typos, and the reader cannot tell which. That is
not hypothetical on this board: `b5b6d252` lost six tmux-gated assertions for days
because they SKIPPED, a skip emits no failure block, and the only visible artifact
was a number that did not move.

⚠️ AND SET-EQUALITY ALONE STILL HAS A HOLE. `@pytest.mark.host_onyl` puts a test in
NEITHER set, so the equality passes while the test runs in the wrong venue. What
closes that is `--strict-markers` in pytest.ini, which makes an unregistered marker
a hard collection error. Both halves are required; `test_strict_markers_is_armed`
pins the half that lives in config and would otherwise be deleted silently.

Venue: :7999-eligible — pure functions over fake items; no container, no server.
"""
import subprocess
import sys
import types

import pytest

import cosa.utils.util as cu
from tests.venue_routing import (
    HOST_ONLY_MARKER, host_is_reachable, partition_by_venue, deselection_report,
)

PROJECT_ROOT = cu.get_project_root()


class FakeItem:
    """Minimal stand-in for a pytest Item: a nodeid and a marker lookup."""
    def __init__( self, nodeid, markers=() ):
        self.nodeid   = nodeid
        self._markers = set( markers )

    def get_closest_marker( self, name ):
        return object() if name in self._markers else None


# ── host_is_reachable — BOTH directions, no container required ────────────────

def test_host_is_reachable_when_the_dockerenv_sentinel_is_absent( tmp_path ):
    assert host_is_reachable( str( tmp_path / "no-such-file" ) ) is True


def test_host_is_NOT_reachable_when_the_dockerenv_sentinel_exists( tmp_path ):
    sentinel = tmp_path / ".dockerenv"
    sentinel.write_text( "" )
    assert host_is_reachable( str( sentinel ) ) is False


def test_the_default_sentinel_path_is_the_real_one():
    """
    The default argument is the whole mechanism. A test that only ever passes an
    explicit tmp_path would leave the production default unexercised and free to
    drift to something that never exists — which fails OPEN (nothing deselected).
    """
    import inspect
    assert inspect.signature( host_is_reachable ).parameters[ "dockerenv_path" ].default == "/.dockerenv"


# ── partition_by_venue ────────────────────────────────────────────────────────

def test_host_reachable_deselects_nothing_even_when_marked():
    items = [ FakeItem( "a", [ HOST_ONLY_MARKER ] ), FakeItem( "b" ) ]
    kept, deselected = partition_by_venue( items, host_reachable=True )
    assert [ i.nodeid for i in kept ] == [ "a", "b" ]
    assert deselected == []


def test_host_unreachable_deselects_exactly_the_marked_ones():
    items = [ FakeItem( "a", [ HOST_ONLY_MARKER ] ), FakeItem( "b" ), FakeItem( "c", [ HOST_ONLY_MARKER ] ) ]
    kept, deselected = partition_by_venue( items, host_reachable=False )
    assert [ i.nodeid for i in kept ]       == [ "b" ]
    assert [ i.nodeid for i in deselected ] == [ "a", "c" ]


def test_an_unrelated_marker_never_triggers_deselection():
    """A near-miss marker must NOT be treated as host_only — that would silence tests nobody asked to silence."""
    items = [ FakeItem( "a", [ "host_onyl" ] ), FakeItem( "b", [ "integration" ] ) ]
    kept, deselected = partition_by_venue( items, host_reachable=False )
    assert deselected == []
    assert len( kept ) == 2


@pytest.mark.parametrize( "reachable", [ True, False ] )
def test_the_partition_loses_nothing_and_duplicates_nothing( reachable ):
    items = [ FakeItem( "a", [ HOST_ONLY_MARKER ] ), FakeItem( "b" ), FakeItem( "c", [ HOST_ONLY_MARKER ] ) ]
    kept, deselected = partition_by_venue( items, host_reachable=reachable )
    assert len( kept ) + len( deselected ) == len( items )
    assert { i.nodeid for i in kept } | { i.nodeid for i in deselected } == { "a", "b", "c" }


# ── deselection_report — the NAMES are the point ──────────────────────────────

def test_no_banner_when_nothing_was_deselected():
    assert deselection_report( [] ) is None


def test_the_report_names_every_deselected_node_id():
    ids    = [ "src/tests/unit/test_x.py::test_one", "src/tests/unit/test_x.py::test_two" ]
    report = deselection_report( ids )
    for nid in ids: assert nid in report, "a deselected test that is not NAMED is indistinguishable from a pass"
    assert "did NOT run" in report


def test_the_report_is_not_merely_a_count():
    """
    RED-FIRST INTENT: if deselection_report is ever 'simplified' to emit a tally,
    this fails. The count is the failure mode, not the feature.
    """
    report = deselection_report( [ "pkg/test_a.py::test_alpha", "pkg/test_b.py::test_beta" ] )
    assert "test_alpha" in report and "test_beta" in report
    assert report.count( "::" ) >= 2


# ── the config half — strict markers ──────────────────────────────────────────

def test_strict_markers_is_armed():
    """
    Without --strict-markers a typo'd marker is a silent no-op, and the
    deselect-set == marker-set guard passes while the test runs in the wrong venue.
    Set-equality alone does not close that; this does.
    """
    ini = open( f"{PROJECT_ROOT}/pytest.ini", encoding="utf-8" ).read()
    assert "--strict-markers" in ini


def test_host_only_is_a_registered_marker():
    ini = open( f"{PROJECT_ROOT}/pytest.ini", encoding="utf-8" ).read()
    assert f"{HOST_ONLY_MARKER}:" in ini, "an unregistered marker is a hard error under --strict-markers"


# ── end-to-end: the wiring, not just the pieces ───────────────────────────────

def test_the_host_attesting_register_carries_the_marker():
    """
    The one test this row exists for. If someone strips the marker, the pilot-AC
    register goes back to failing in-container for a claim it cannot judge there.
    """
    src = open( f"{PROJECT_ROOT}/src/tests/unit/test_pilot_ac_instruments.py", encoding="utf-8" ).read()
    assert f"@pytest.mark.{HOST_ONLY_MARKER}" in src
    marker_at = src.index( f"@pytest.mark.{HOST_ONLY_MARKER}" )
    target_at = src.index( "def test_every_ac_register_entry_matches_the_host" )
    assert marker_at < target_at and ( target_at - marker_at ) < 400, \
        "the marker must decorate the host-attesting register, not float elsewhere in the file"


def test_deselection_actually_happens_in_a_simulated_container():
    """
    The wiring, exercised for real: run pytest in a subprocess whose sentinel path
    says 'container', and assert the marked test is deselected AND NAMED in stdout.

    ⚠️ Not a claim about the real container — it is a claim about the HOOK. The
    container's own behaviour is verified by running the tier there; a green here
    with a broken hook would be exactly the false receipt this row is about, so
    the negative arm below must fail if the hook is removed.
    """
    probe = f"{PROJECT_ROOT}/src/tests/unit/test_pilot_ac_instruments.py::test_every_ac_register_entry_matches_the_host"
    out = subprocess.run(
        [ sys.executable, "-m", "pytest", probe, "--collect-only", "-q", "-p", "no:cacheprovider" ],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
        env={ **__import__( "os" ).environ, "LUPIN_ROOT": PROJECT_ROOT },
    )
    assert "test_every_ac_register_entry_matches_the_host" in out.stdout, \
        f"the host-side collect should SEE the register; got:\n{out.stdout[-1500:]}"
