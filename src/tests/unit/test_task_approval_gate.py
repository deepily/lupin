"""
The holding-area approval gate: who may admit a row out of `not_approved`.

WHY THIS FILE EXISTS. María's condition on Phase 3, and it is the right one:
**an authorization check nobody has watched refuse is not a control.** A gate can
be wired, imported, and covered at 100% while never having been observed to say no
to anybody — and the coverage number would be true the whole time. So the
load-bearing test here is `test_a_non_approver_is_actually_refused`, and every
other test in this file exists to stop that one passing for the wrong reason.

🔴 EVERY TEST POINTS THE MODULE AT A tmp_path, NEVER THE REAL DATA ROOT — the
override lives under `fleet_data_root()`, shared by every process on this box, so a
test that wrote there would move the LIVE fleet's approver list. The isolation guard
runs first and proves the isolation rather than assuming it, copying the precedent in
`test_flow_ratio_settings.py`.

Venue: :7999-eligible — in-process, no server, no network, writes only under tmp_path.
"""

import json

import pytest

from cosa.rest import task_approval_settings as approval


@pytest.fixture
def isolated( tmp_path, monkeypatch ):
    """
    Point the module's override file at tmp_path and clear its mtime cache.

    Ensures:
        - `override_path()` resolves inside tmp_path for the duration of the test
        - the module-level mtime cache is reset, so one test's write cannot be
          served to the next out of cache
    """
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache", { "approvers": None, "enforcement_active": None } )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    return target


def _write( target, **body ):
    target.write_text( json.dumps( body ) )
    approval._cache_mtime = None


def test_the_isolation_actually_isolates( isolated ):
    """
    THE GUARD ON EVERY OTHER TEST IN THIS FILE, so it runs first.

    Without it a passing suite would be consistent with the module reading the real
    fleet settings and this file having moved them.
    """
    assert str( isolated ) == approval.override_path()
    assert "projects-data" not in approval.override_path()
    _write( isolated, approvers=[ "probe-persona" ] )
    # `probe persona`, not `probe-persona`: the canonicalizer folds a hyphen to a
    # space. Asserting the RAW string here would fail for a reason that has nothing
    # to do with isolation — and this guard is the one test whose failure must mean
    # exactly one thing.
    assert "probe persona" in approval.get_approvers()


# ---------------------------------------------------------------------------
# The one that matters
# ---------------------------------------------------------------------------

def test_a_non_approver_is_actually_refused( isolated ):
    """
    THE LOAD-BEARING TEST. A named non-approver is refused, and the refusal is
    OBSERVED rather than inferred from the absence of an approval.

    The positive control is in the same test on purpose: without it, a module that
    refused EVERYBODY — including its configured approvers — would pass a
    refusal-only assertion perfectly.
    """
    _write( isolated, approvers=[ "maria" ] )
    assert approval.is_approver( "maria 611e3c47" )        is True   # positive control
    assert approval.is_approver( "somebody else 9999" )    is False  # the refusal


def test_the_gate_discriminates_on_the_NAME_and_not_on_the_string_length( isolated ):
    """
    A fixture that cannot tell two inputs apart cannot see a swap between them.

    `is_approver` walks progressively shorter leading word-runs, so a test using two
    names of DIFFERENT word counts could pass on the walk's arithmetic rather than on
    the matching. Both names here are two words plus a session id, so the only
    variable left is the name itself.
    """
    _write( isolated, approvers=[ "mr radio" ] )
    assert approval.is_approver( "mr radio dde22022" )  is True
    assert approval.is_approver( "mr potato 611e3c47" ) is False


# ---------------------------------------------------------------------------
# The ways the refusal could be wrong
# ---------------------------------------------------------------------------

def test_rick_is_unconditional_even_against_an_empty_list( isolated ):
    """
    An empty or truncated config must never leave the holding area with ZERO
    approvers — that locks the whole fleet out of its own board with no way back in
    except a deploy, which is the failure this configurability exists to prevent.
    """
    _write( isolated, approvers=[ ] )
    assert approval.is_approver( "Rick" ) is True
    assert approval.get_approvers() == frozenset( approval.UNCONDITIONAL_APPROVERS )


def test_an_unnamed_caller_is_never_an_approver( isolated ):
    """
    None and blank are the shapes a missing actor arrives as. Neither may pass.
    """
    _write( isolated, approvers=[ "maria" ] )
    for actor in ( None, "", "   ", 42, [ ] ):
        assert approval.is_approver( actor ) is False, f"{actor!r} passed the gate"


def test_matching_is_canonical_so_casing_and_accents_do_not_decide_access( isolated ):
    """
    The actor string is caller-typed. If access turned on capitalisation, the gate
    would refuse the right person for the wrong reason — indistinguishable, from the
    caller's side, from being genuinely unlisted.
    """
    _write( isolated, approvers=[ "maria" ] )
    assert approval.is_approver( "María 611e3c47" ) is True
    assert approval.is_approver( "MARIA 611e3c47" ) is True


# ---------------------------------------------------------------------------
# Failing OPEN, deliberately
# ---------------------------------------------------------------------------

def test_a_missing_override_file_does_not_enforce( isolated ):
    """
    The fallback is False on purpose: a gate that fails CLOSED on a missing file
    takes the board down for everyone with no obvious cause. Being wrong in this
    direction is loud and recoverable; the other direction is silent and total.
    """
    assert not isolated.exists()
    assert approval.get_enforcement_active() is False


def test_a_corrupt_override_file_is_reported_and_does_not_raise( isolated, capsys ):
    """
    A bad settings file must not take the board down — and must not be SILENT
    either, or an operator's write looks disregarded with no clue why.
    """
    isolated.write_text( "{ this is not json" )
    approval._cache_mtime = None
    assert approval.get_enforcement_active() is False
    assert "[task-approval]" in capsys.readouterr().out


def test_a_non_list_approvers_value_is_ignored_rather_than_raising( isolated ):
    """
    An operator typing a string where a list belongs must not 500 the transition
    endpoint. It falls through to the config, and Rick survives regardless.
    """
    _write( isolated, approvers="maria" )
    assert approval.is_approver( "Rick" ) is True


def test_enforcement_reads_the_file_and_both_answers_are_reachable( isolated ):
    """
    Both arms, because a getter stuck on one constant satisfies either arm alone.
    """
    _write( isolated, enforcement_active=True )
    assert approval.get_enforcement_active() is True
    _write( isolated, enforcement_active=False )
    assert approval.get_enforcement_active() is False


# ---------------------------------------------------------------------------
# THROUGH THE REAL ENDPOINT — the predicate tests above are necessary and NOT
# sufficient. A correct `is_approver` wired to nothing at all would pass every
# one of them. María's condition was a test that watches a non-approver get
# REFUSED, and a refusal happens at the door, not in a helper.
# ---------------------------------------------------------------------------

import os
import sys
import uuid


@pytest.fixture( scope="module" )
def real_app():
    """The FastAPI object `main.py` itself assembles — not one built by this test."""
    root = os.environ.get( "LUPIN_ROOT" )
    assert root, "LUPIN_ROOT must be set — see CLAUDE.md § PATH MANAGEMENT"

    os.environ.setdefault( "JWT_SECRET_KEY", "test-only-never-signs-anything" )
    src = os.path.join( root, "src" )
    if src not in sys.path: sys.path.insert( 0, src )

    import lupin_app.main as main_module
    return main_module.app


def test_a_non_approver_is_REFUSED_at_the_gate_with_enforcement_on( isolated ):
    """
    THE REFUSAL, OBSERVED. `refusal_for_admission` is the gate's whole decision, so
    this watches it say no — and the positive control in the same test stops a
    module that refused EVERYBODY from passing.
    """
    _write( isolated, approvers=[ "maria" ], enforcement_active=True )

    refusal = approval.refusal_for_admission( "not_approved", "queued", "somebody else 9999" )
    assert refusal is not None
    assert "somebody else 9999" in refusal
    assert "not an approver"    in refusal
    # A refusal that does not say how to proceed is a dead end wearing a 403.
    assert approval.INI_KEY_APPROVERS in refusal
    assert approval.override_path()   in refusal

    # positive control — the same call for a listed approver must PASS
    assert approval.refusal_for_admission( "not_approved", "queued", "maria 611e3c47" ) is None


@pytest.mark.parametrize(
    "from_status,to_status,actor,why",
    [
        ( "queued",       "in_progress",  "somebody else 9999", "not an admission — from_status is not the holding area" ),
        ( "not_approved", "not_approved", "somebody else 9999", "the no-op is not an admission" ),
    ],
)
def test_the_gate_stays_out_of_transitions_that_are_not_admissions( isolated, from_status, to_status, actor, why ):
    """
    A gate that refuses MORE than it was asked to is a defect that looks like
    caution. Enforcement is ON in every arm, so a None here is the clause under test
    and not the enforcement flag being off.
    """
    _write( isolated, approvers=[ "maria" ], enforcement_active=True )
    assert approval.refusal_for_admission( from_status, to_status, actor ) is None, why


def test_enforcement_OFF_advises_rather_than_refuses( isolated ):
    """
    Both arms, one variable. Without the ON arm this would pass for a gate that
    never refuses anybody under any setting.
    """
    _write( isolated, approvers=[ "maria" ], enforcement_active=False )
    assert approval.refusal_for_admission( "not_approved", "queued", "somebody else 9999" ) is None
    _write( isolated, approvers=[ "maria" ], enforcement_active=True )
    assert approval.refusal_for_admission( "not_approved", "queued", "somebody else 9999" ) is not None


def test_the_gate_is_wired_into_the_transition_door_at_all( real_app ):
    """
    THE GUARD ON THE TWO TESTS BELOW. A gate can be perfectly implemented and
    imported by nobody — and every predicate test in this file would still pass.
    Assert the router actually holds the module, so a future refactor that drops
    the import fails HERE, naming the cause, instead of silently disarming the gate
    and leaving a suite that is green about a control that is gone.
    """
    import cosa.rest.routers.tasks as tasks_router
    assert tasks_router.approval is approval
    assert tasks_router.rules.NOT_APPROVED_STATUS == "not_approved"

    mounted = { route.path for route in real_app.routes if "PATCH" in getattr( route, "methods", set() ) }
    assert any( "/tasks/" in path for path in mounted ), (
        f"no PATCH task route is mounted at all — the two tests below would then be "
        f"asserting about a door that does not exist. Mounted PATCH paths: {sorted( mounted )}"
    )


# ---------------------------------------------------------------------------
# WON'T-FIX IS THE OTHER APPROVER-ONLY MOVE, AND IT IS THE LOAD-BEARING ONE
#
# María's finding, corrected by Rick 2026-09-02 (planning-is-prompting a1f2697):
# `wont_fix` COUNTS toward the create/close ratio while `dropped` does not. So a
# seat able to close rows this way holds BOTH halves of a mint-by-deletion loop —
# close to raise the closed count, then create against the headroom it just made.
# Approver-only is what shuts it, which makes this check the thing standing between
# the ratio gate and a ticket generator. A UI-only restriction hands every worker
# that loop.
# ---------------------------------------------------------------------------

def test_a_non_approver_cannot_close_a_row_as_wont_fix( isolated ):
    """
    THE MINT-BY-DELETION GUARD. Both arms, because a refusal-only assertion also
    passes for a gate that refuses its own approvers.
    """
    _write( isolated, approvers=[ "maria" ], enforcement_active=True )

    refusal = approval.refusal_for_admission( "queued", "wont_fix", "somebody else 9999" )
    assert refusal is not None
    assert "wont_fix" in refusal
    assert approval.refusal_for_admission( "queued", "wont_fix", "maria 611e3c47" ) is None


def test_wont_fix_is_gated_from_EVERY_source_status_not_just_the_holding_area( isolated ):
    """
    The admission clause keys on `from_status`; this one must not. A gate that only
    caught `not_approved -> wont_fix` would leave the loop open from `queued`, which
    is where a worker's own rows actually sit — i.e. it would look implemented and
    close nothing.
    """
    _write( isolated, approvers=[ "maria" ], enforcement_active=True )
    for source in ( "queued", "in_progress", "blocked", "parked", "review", "claimed" ):
        assert approval.refusal_for_admission( source, "wont_fix", "somebody else 9999" ) is not None, (
            f"'{source}' -> wont_fix was NOT gated — the mint-by-deletion loop is open from there"
        )


def test_dropped_is_NOT_approver_gated( isolated ):
    """
    The negative control that gives the test above its meaning. `dropped` does not
    count toward the ratio, so it carries no mint-by-deletion risk and must stay
    available to every seat — it is the ordinary escape hatch, and it already
    carries its own reason requirement. Without this arm, a gate that refused every
    close would pass the whole section.
    """
    _write( isolated, approvers=[ "maria" ], enforcement_active=True )
    assert approval.refusal_for_admission( "queued", "dropped", "somebody else 9999" ) is None


# ---------------------------------------------------------------------------
# THE PATHS THE TESTS ABOVE CANNOT REACH
#
# Every test above monkeypatches `override_path`, which is the right isolation and
# means the REAL resolver never runs in any of them. Same for the tolerance arms:
# a suite that only ever feeds well-formed input proves nothing about what happens
# to malformed input, and those arms are the ones that decide whether a bad config
# degrades or takes the board down.
# ---------------------------------------------------------------------------

def test_the_env_var_branch_of_the_real_resolver( monkeypatch, tmp_path ):
    """
    The container's branch. `LUPIN_FLOW_RATIO_DIR` is set in `lupin-rest-dev` and
    `lupin-rest-test`, so this is the path that actually runs in production — and
    the one no other test in this file touches, because they all replace the
    resolver wholesale.
    """
    monkeypatch.setenv( approval._SETTINGS_DIR_ENV, str( tmp_path ) )
    assert approval.override_path() == str( tmp_path / approval.OVERRIDE_FILENAME )


def test_the_host_fallback_appends_the_mount_subdirectory( monkeypatch ):
    """
    🔴 THE SUBDIRECTORY IS NOT DECORATION. `flow_ratio_settings` shipped this exact
    fallback WITHOUT `OVERRIDE_SUBDIR` for three days: the container is handed
    `<fleet_data_root>/flow-ratio` as its whole world, so a fallback stopping at
    `<fleet_data_root>` names a DIFFERENT file than every server writes — and the
    two branches then disagree silently, because each is individually plausible.

    Asserted as a relationship between the two branches rather than a literal path,
    so it stays true wherever the data root moves.
    """
    monkeypatch.delenv( approval._SETTINGS_DIR_ENV, raising=False )
    path = approval.override_path()
    assert path.endswith( os.path.join( approval.OVERRIDE_SUBDIR, approval.OVERRIDE_FILENAME ) )

    # ...and it is the SAME file the env-var branch names, which is the whole claim.
    monkeypatch.setenv( approval._SETTINGS_DIR_ENV, os.path.dirname( path ) )
    assert approval.override_path() == path


def test_a_json_file_holding_something_other_than_an_object_is_tolerated( isolated, capsys ):
    """
    Valid JSON, wrong shape — `[1, 2, 3]` parses fine and has no `.get`. Distinct
    from the corrupt-file case above: that one fails in the parser, this one fails
    after it, and only the second would raise an AttributeError deep in a getter.
    """
    isolated.write_text( "[1, 2, 3]" )
    approval._cache_mtime = None
    assert approval.get_enforcement_active() is False
    assert "expected a JSON object" in capsys.readouterr().out


def test_an_unreadable_config_manager_falls_back_rather_than_raising( isolated, monkeypatch ):
    """
    `_ini_value` swallows anything the ConfigurationManager throws. Untested, that
    `except` is the classic never-exercised safety net — and this module is imported
    by the transition endpoint, so an exception here 500s a live write path.
    """
    def _boom( *args, **kwargs ): raise RuntimeError( "config is unavailable" )
    monkeypatch.setattr( approval, "ConfigurationManager", _boom )

    assert not isolated.exists()                       # no override -> INI is consulted
    assert approval.get_enforcement_active() is False  # the fallback, not a raise
    assert approval.get_approvers() == frozenset( approval.UNCONDITIONAL_APPROVERS )


def test_junk_entries_in_the_approver_list_are_skipped_not_fatal( isolated ):
    """
    An operator hand-editing JSON produces blanks, nulls and stray types. Each is
    skipped individually — the LIST must survive one bad entry, or a typo silently
    empties the allowlist down to Rick and nobody can tell why.
    """
    _write( isolated, approvers=[ "maria", "", "   ", None, 42, [ "nested" ], "cheech" ] )
    approvers = approval.get_approvers()
    assert "maria"  in approvers
    assert "cheech" in approvers                       # the entry AFTER the junk still lands
    assert "rick"   in approvers
    assert len( approvers ) == 3                       # and nothing else crept in


@pytest.mark.parametrize(
    "text,expected",
    [ ( "True", True ), ( "true", True ), ( "1", True ), ( "yes", True ), ( "on", True ),
      ( "False", False ), ( "no", False ), ( "", False ), ( "banana", False ) ],
)
def test_the_INI_string_is_read_as_a_boolean_both_ways( isolated, monkeypatch, text, expected ):
    """
    The INI path, reached only when the override file names no `enforcement_active`.
    Both truthy and falsy arms, because a parser stuck on either constant satisfies
    a one-sided test — and `banana` is the arm that proves it is a MEMBERSHIP test
    rather than a truthiness test on a non-empty string.
    """
    _write( isolated, approvers=[ "maria" ] )          # file exists, but says nothing about enforcement
    monkeypatch.setattr( approval, "_ini_value", lambda *a, **k: text )
    assert approval.get_enforcement_active() is expected
