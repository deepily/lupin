"""
Item 3a of Rick's keying ruling (2026-09-03, row db56ac6d): the self-respin MARKER
writer must key on the SEAT's own repo, not on the ambient one.

WHAT WAS WRONG. `self_respin_core._resolve_base_dir()` called `fleet_data_root()` with
no argument. That resolves `cu.get_project_root()` — the LUPIN_ROOT env var, which is
identical for every process on this box. So a seat sitting in planning-is-prompting
wrote its marker under `lupin`. Measured 2026-09-02: 69 markers under lupin, 0 under
every other data root, and one of them naming a planning-is-prompting memento in its
own `memento_path` while sitting in lupin's directory — the writer contradicting its
own payload about which repo it is in.

WHY THESE TESTS ENTER AT `perform_self_respin` AND NOT AT `_resolve_base_dir` ALONE.
The incident is a seat firing the verb with no `base_dir` — the live path, via
`self_respin_from_bridge`, which passes none. Every pre-existing test in this tree
hands `perform_self_respin` an explicit `base_dir=str( tmp_path )`, so the resolution
branch was never executed by any of them; that is why the defect could sit there at
100% coverage. A test that only called the helper would prove the helper and say
nothing about whether the verb reaches it.

WHAT IS REAL HERE AND WHAT IS INJECTED. `fleet_data_root` is the REAL function, aimed
at a tmp directory through its own `DEEPILY_DATA_DIR` env var — so the repo→directory
mapping under test is production's, not a fake's. The memento slot is a real slot
written by the shared seeder, and the slot gate is the real `_default_verify_slot`.
Only tmux, the ask and the detached-clear spawn are stood down.

THE NEGATIVE CONTROL IS `test_a_same_repo_seat_still_lands_on_the_root_it_lands_on_today`
and it is SUPPOSED TO SURVIVE a revert of the fix. Without it, "the marker moved" would
be satisfied by code that moves it always — which would be a different defect wearing
this fix's clothes.
"""

import datetime
import json
import os

import pytest

import lupin_mcp.self_respin_core as sr
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import DATA_DIR_ENV, fleet_data_root
from tests.helpers.memento_slot_seed import seed_root_slot


UTC       = datetime.timezone.utc
_SEAT_SID = "0e3df8ca-1111-2222-3333-444455556666"
_PERSONA  = "rio"


def _now():
    return datetime.datetime.now( UTC )


def _seat_repo( tmp_path, name ):
    """A seat's repo root on disk. Not a git repo — `_main_repo_path` falls back to
    the resolved path when git cannot answer, which is exactly the shape we want:
    the directory NAME is what fleet_data_root keys on."""
    root = tmp_path / "projects" / name
    root.mkdir( parents=True, exist_ok=True )
    return root


def _data_dir( tmp_path ):
    """Point the REAL fleet_data_root at a tmp tree via its own env var."""
    d = tmp_path / "projects-data"
    d.mkdir( parents=True, exist_ok=True )
    return d


def _fire( repo_root, *, base_dir=None, memento_path, nonce, scheduled=None ):
    """Drive the real verb down the go-path with only the world stood down."""
    return sr.perform_self_respin(
        _SEAT_SID,
        persona          = _PERSONA,
        memento_path     = memento_path,
        memento_nonce    = nonce,
        pre_clear_status = "over_budget",
        pre_clear_pct    = 61.0,
        now              = _now(),
        resolve_tmux_fn  = lambda sid: "cc-rio-3a",
        ask_fn           = lambda: "yes",
        schedule_fn      = ( scheduled.append if scheduled is not None else ( lambda argv: None ) ),
        base_dir         = base_dir,
        repo_root        = str( repo_root ),
    )


def _seed( repo_root ):
    nonce        = "3a-cycle-nonce"
    memento_path = seed_root_slot( repo_root, _PERSONA, _SEAT_SID, nonce_uuid=nonce, nonce_ts=_now() )
    return memento_path, nonce


# ---------------------------------------------------------------------------
# THE KILL ARMS — each fails when the writer goes back to the ambient root
# ---------------------------------------------------------------------------
def test_the_marker_lands_under_the_seats_own_repo_not_the_ambient_one( tmp_path, monkeypatch ):
    """
    The whole finding, at the layer the incident entered at: a seat in
    `planning-is-prompting` fires the verb with NO base_dir, and its marker must land
    in planning-is-prompting's data directory — not in the ambient repo's.
    """
    seat    = _seat_repo( tmp_path, "planning-is-prompting" )
    ambient = _seat_repo( tmp_path, "lupin" )
    data    = _data_dir( tmp_path )
    monkeypatch.setenv( DATA_DIR_ENV, str( data ) )
    monkeypatch.setenv( "LUPIN_ROOT", str( ambient ) )       # the ambient root, as on the live box
    ( data / "planning-is-prompting" ).mkdir()
    ( data / "lupin" ).mkdir()

    memento_path, nonce = _seed( seat )
    r = _fire( seat, memento_path=memento_path, nonce=nonce )

    assert r.status == "scheduled", r.reason
    seat_marker    = data / "planning-is-prompting" / f".self-respin-{_SEAT_SID}.json"
    ambient_marker = data / "lupin"                / f".self-respin-{_SEAT_SID}.json"
    assert seat_marker.exists(),        "the seat's own repo holds no marker"
    assert not ambient_marker.exists(), "the marker landed under the AMBIENT root — the defect"
    assert json.loads( seat_marker.read_text() )[ "session_id" ] == _SEAT_SID


def test_the_marker_and_its_own_payload_name_the_same_repo( tmp_path, monkeypatch ):
    """
    The measured signature of the defect was a marker whose `memento_path` named one
    repo while the FILE sat under another. Pin the agreement, not just the location:
    a reader must never have to choose between two facts in one file.
    """
    seat    = _seat_repo( tmp_path, "planning-is-prompting" )
    ambient = _seat_repo( tmp_path, "lupin" )
    data    = _data_dir( tmp_path )
    monkeypatch.setenv( DATA_DIR_ENV, str( data ) )
    monkeypatch.setenv( "LUPIN_ROOT", str( ambient ) )
    ( data / "planning-is-prompting" ).mkdir()
    ( data / "lupin" ).mkdir()

    memento_path, nonce = _seed( seat )
    assert _fire( seat, memento_path=memento_path, nonce=nonce ).status == "scheduled"

    marker_file = data / "planning-is-prompting" / f".self-respin-{_SEAT_SID}.json"
    payload     = json.loads( marker_file.read_text() )
    assert str( seat ) in payload[ "memento_path" ]
    assert marker_file.parent.name == seat.name


def test_two_seats_in_different_repos_get_different_data_roots( tmp_path, monkeypatch ):
    """
    The discriminating reading. Under the ambient rule these two are the SAME
    directory, whatever repo either seat is in — that sameness IS the defect.
    """
    monkeypatch.setenv( DATA_DIR_ENV, str( _data_dir( tmp_path ) ) )
    a = sr._resolve_base_dir( str( _seat_repo( tmp_path, "planning-is-prompting" ) ) )
    b = sr._resolve_base_dir( str( _seat_repo( tmp_path, "lupin-mobile" ) ) )
    assert a != b
    assert os.path.basename( a ) == "planning-is-prompting"
    assert os.path.basename( b ) == "lupin-mobile"


def test_an_unsupplied_repo_root_is_resolved_from_the_seats_own_cwd( tmp_path, monkeypatch ):
    """
    `self_respin` runs IN the seat's own process, so the seat's cwd is the seat's repo.
    With no repo_root supplied the helper must ASK — `resolve_repo_root()` — rather than
    fall through to the ambient env var.
    """
    seat    = _seat_repo( tmp_path, "lupin-mobile" )
    ambient = _seat_repo( tmp_path, "lupin" )
    monkeypatch.setenv( DATA_DIR_ENV, str( _data_dir( tmp_path ) ) )
    monkeypatch.setenv( "LUPIN_ROOT", str( ambient ) )
    monkeypatch.setattr( sr, "resolve_repo_root", lambda: str( seat ) )

    assert os.path.basename( sr._resolve_base_dir( None ) ) == "lupin-mobile"


# ---------------------------------------------------------------------------
# THE SURVIVORS — these pass with and without the fix, ON PURPOSE
# ---------------------------------------------------------------------------
def test_a_same_repo_seat_still_lands_on_the_root_it_lands_on_today( tmp_path, monkeypatch ):
    """
    NEGATIVE CONTROL — SURVIVES the revert, and must.

    The overwhelmingly common case is a seat whose repo IS the ambient repo. For it the
    ruling must be a no-op: the same directory, byte for byte, as before. Without this
    arm, "the marker moved" would be satisfied by code that moves it unconditionally.
    """
    seat = _seat_repo( tmp_path, "lupin" )
    data = _data_dir( tmp_path )
    monkeypatch.setenv( DATA_DIR_ENV, str( data ) )
    monkeypatch.setenv( "LUPIN_ROOT", str( seat ) )
    ( data / "lupin" ).mkdir()

    todays_root = str( fleet_data_root() )                  # what the AMBIENT rule returns
    assert sr._resolve_base_dir( str( seat ) ) == todays_root

    memento_path, nonce = _seed( seat )
    assert _fire( seat, memento_path=memento_path, nonce=nonce ).status == "scheduled"
    assert ( data / "lupin" / f".self-respin-{_SEAT_SID}.json" ).exists()


def test_an_explicit_base_dir_still_wins_over_the_seats_repo( tmp_path, monkeypatch ):
    """
    SURVIVES the revert, and must: `base_dir` is the caller's override seam and every
    other suite in this tree depends on it. The ruling changes what happens when the
    caller supplies NOTHING; it must not change what happens when the caller supplies
    something.
    """
    seat     = _seat_repo( tmp_path, "planning-is-prompting" )
    data     = _data_dir( tmp_path )
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    monkeypatch.setenv( DATA_DIR_ENV, str( data ) )
    ( data / "planning-is-prompting" ).mkdir()

    memento_path, nonce = _seed( seat )
    assert _fire( seat, base_dir=str( explicit ), memento_path=memento_path, nonce=nonce ).status == "scheduled"

    assert ( explicit / f".self-respin-{_SEAT_SID}.json" ).exists()
    assert not ( data / "planning-is-prompting" / f".self-respin-{_SEAT_SID}.json" ).exists()
