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


@pytest.fixture
def ini_flags_absent( monkeypatch ):
    """
    Make the two approval FLAG keys read as ABSENT from the shipped INI.

    🔴 WHY THIS EXISTS, AND WHY IT IS NOT THE OVERRIDE FIXTURE. `isolated` moves the
    OVERRIDE file into tmp_path, which is the whole isolation these tests used to
    need — because with no override the getters fell through to an INI that shipped
    `False`, and False was the answer they wanted. On 2026-09-02 Rick turned both
    flags ON (`f3870751`), the shipped INI became the live value, and five tests went
    red having never asserted anything about an override at all. **They were passing
    on a config the repository ships, not on a fixture they controlled.**

    ⚠️ IT CANNOT BE DONE THROUGH THE OVERRIDE FILE. `_read_overrides` returns
    "no override" for a MISSING file and, deliberately, also for a CORRUPT one — both
    then fall through to `_ini_value`, and only an absent INI key reaches the hard
    fallback. Three of the five arms are precisely the missing-or-corrupt cases, so
    pinning through that file would make the pin and the subject under test the same
    object.

    ⚠️ AND IT PINS TWO KEYS, NOT THE READER. `get_approvers` also goes through
    `_ini_value`, and blanking that would silently change what `is_approver` answers
    in tests that never asked for it. Only the two flags are intercepted; everything
    else reaches the real reader.

    Ensures:
        - `_ini_value` returns None for the enforcement and holding-default keys
        - every other key reaches the real reader unchanged
    """
    real  = approval._ini_value
    flags = ( approval.INI_KEY_ENFORCEMENT, approval.INI_KEY_DEFAULT_TO_HOLDING )

    def pinned( key, return_type, fallback ):
        if key in flags: return None
        return real( key, return_type, fallback )

    monkeypatch.setattr( approval, "_ini_value", pinned )


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

def test_a_missing_override_file_does_not_enforce( isolated, ini_flags_absent ):
    """
    The fallback is False on purpose: a gate that fails CLOSED on a missing file
    takes the board down for everyone with no obvious cause. Being wrong in this
    direction is loud and recoverable; the other direction is silent and total.

    🔴 READ THE SCOPE BEFORE TRUSTING THIS TEST — IT IS NARROWER THAN ITS NAME.
    With both sources absent this proves `FALLBACK_ENFORCEMENT_ACTIVE` is False and
    is reached. It no longer says anything about PRODUCTION: since `f3870751` the
    shipped INI says True, so a missing override file now ENFORCES. The docstring
    above argues a deliberate fail-OPEN and the code no longer has that property.

    ⚠️ NOT REPAIRED HERE, DELIBERATELY. Rachel found it; the fix is a rename plus a
    new arm with both sources absent, and whether the fail-open promise still stands
    is Rick's call, not a repair to fold into a pinning pass. Mr Radio is putting it
    to him. Pinned as-is and flagged.
    """
    assert not isolated.exists()
    assert approval.get_enforcement_active() is False


def test_a_corrupt_override_file_is_reported_and_does_not_raise( isolated, ini_flags_absent, capsys ):
    """
    A bad settings file must not take the board down — and must not be SILENT
    either, or an operator's write looks disregarded with no clue why.
    """
    isolated.write_text( "{ this is not json" )
    # Written directly rather than through `_write`, so the mtime reset that helper
    # performs has to be done by hand here. `_read_overrides` serves its cache when
    # the file's whole-second mtime has not moved, so without this the read can be
    # answered from a previous test's parse.
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


def test_a_json_file_holding_something_other_than_an_object_is_tolerated( isolated, ini_flags_absent, capsys ):
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


# ---------------------------------------------------------------------------
# PHASE 4 — NEW TICKETS START IN THE HOLDING AREA
#
# The writer, landed LAST on purpose. Ship it before the reader and every create
# fleet-wide falls into a bin nobody can open — 072ef7e/d4f6c29 in a different
# costume, and that one cost this fleet two days.
# ---------------------------------------------------------------------------

def test_the_default_mint_status_is_queued_until_somebody_turns_it_on( isolated, ini_flags_absent ):
    """
    The arm that must hold on an ABSENT config: an unreadable settings file must not
    silently start burying every seat's filed work behind a human.

    ⚠️ "Today's behaviour, unchanged" is no longer true of the running system and the
    line has been removed rather than left to mislead. Since `f3870751` the shipped
    INI turns the holding default ON, so a real create mints `not_approved`. What
    this arm asserts is the FALLBACK, with both sources absent — which is what its
    name has always meant and what it silently stopped testing when the INI moved.
    """
    assert not isolated.exists()
    assert approval.default_mint_status() == "queued"


def test_the_flag_actually_moves_the_default_both_ways( isolated ):
    """
    Both arms, one variable. A getter stuck on either constant satisfies one arm
    alone — and the OFF arm is the one that proves the flip is real rather than the
    module simply never having read the file.
    """
    _write( isolated, default_to_holding=True )
    assert approval.default_mint_status() == "not_approved"
    _write( isolated, default_to_holding=False )
    assert approval.default_mint_status() == "queued"


def test_the_holding_area_status_is_mintable_but_parked_is_not():
    """
    `not_approved` joins the mint whitelist; `parked` deliberately does not, and the
    contrast is the point. Parking is a human ruling EXISTING work not-now, so it
    needs a park_reason quoting a row that already exists. A holding-area row has no
    history to quote — being unexamined is its whole content, and it is the state a
    row is BORN in rather than one it is moved to.
    """
    from cosa.rest import task_store_rules as rules
    assert rules.validate_create_status( "not_approved", None, None ) == [ ]
    assert rules.validate_create_status( "parked",       None, None ) != [ ]
    assert rules.validate_create_status( "done",         None, None ) != [ ]


def test_an_unreadable_config_leaves_the_default_at_queued( isolated, monkeypatch ):
    """
    The safe direction, asserted rather than assumed. This runs on every create, so
    a raise here 500s the whole write path — and a config failure that silently
    turned the holding area ON would be the worst possible way to learn about it.
    """
    def _boom( *args, **kwargs ): raise RuntimeError( "config is unavailable" )
    monkeypatch.setattr( approval, "ConfigurationManager", _boom )
    assert not isolated.exists()
    assert approval.default_mint_status() == "queued"


@pytest.mark.parametrize( "text,expected",
    [ ( "True", "not_approved" ), ( "on", "not_approved" ), ( "1", "not_approved" ),
      ( "False", "queued" ), ( "banana", "queued" ), ( "", "queued" ) ] )
def test_the_INI_string_drives_the_default_both_ways( isolated, monkeypatch, text, expected ):
    """
    The INI arm, reached only when the override file names no `default_to_holding`.
    `banana` is the arm proving this is a membership test and not truthiness on a
    non-empty string.
    """
    _write( isolated, approvers=[ "maria" ] )
    monkeypatch.setattr( approval, "_ini_value", lambda *a, **k: text )
    assert approval.default_mint_status() == expected


def test_an_EXPLICIT_status_is_distinguishable_from_an_omitted_one():
    """
    🔴 THE MECHANISM THE WHOLE PHASE-4 SUBSTITUTION RESTS ON.

    An explicit `status="queued"` and an omitted `status` both arrive at the router
    as the string `"queued"` — the field default makes them identical by value. So
    without `model_fields_set` there is no way to honour a caller who deliberately
    asked for a queued mint: they would be silently redirected into the holding area
    with no way to say what they meant.

    Asserted on the Pydantic model itself rather than through the endpoint, because
    this is a property of the model and the router only consumes it. If a future
    Pydantic upgrade changes `model_fields_set`, this reddens HERE, naming the cause,
    instead of the substitution quietly starting to override explicit callers.
    """
    from cosa.rest.routers.tasks import TaskCreateIn

    common = { "item_class": "task", "title": "t", "created_by": "mr radio dde22022",
               "project": "lupin" }

    omitted  = TaskCreateIn( **common )
    explicit = TaskCreateIn( **common, status="queued" )

    # Identical by VALUE — which is exactly why value cannot be the discriminator.
    assert omitted.status == explicit.status == "queued"

    # ...and distinguishable by INTENT, which is what the router reads.
    assert "status" not in omitted.model_fields_set
    assert "status"     in explicit.model_fields_set


def test_the_router_substitutes_only_on_an_omitted_status( monkeypatch ):
    """
    The substitution itself, exercised the way the router does it, with the flag ON
    so a `"queued"` result can only come from the explicit-intent branch.

    The negative arm is the load-bearing one: without it, a router that ALWAYS
    substituted would pass the positive arm perfectly.
    """
    from cosa.rest.routers.tasks import TaskCreateIn
    monkeypatch.setattr( approval, "default_mint_status", lambda: "not_approved" )

    common = { "item_class": "task", "title": "t", "created_by": "mr radio dde22022",
               "project": "lupin" }

    def _mint( payload ):
        # the router's two lines, verbatim in shape
        return ( approval.default_mint_status()
                 if "status" not in payload.model_fields_set else payload.status )

    assert _mint( TaskCreateIn( **common ) )                    == "not_approved"
    assert _mint( TaskCreateIn( **common, status="queued" ) )   == "queued"
    assert _mint( TaskCreateIn( **common, status="blocked" ) )  == "blocked"


# ---------------------------------------------------------------------------
# THE CONFIG KEYS ARE REACHABLE — the twin of a defect María found in her lane
#
# 🔴 EVERY OTHER TEST IN THIS FILE EITHER WRITES THE OVERRIDE FILE OR MONKEYPATCHES
# `_ini_value`. So none of them ever reads `lupin-app.ini`, and a typo in a key name
# — in the module OR in the INI — is INVISIBLE to all of them: `_ini_value` swallows
# the miss, returns the fallback, and the suite stays green while the operator's
# configured value is silently ignored.
#
# That is the same shape as the defect María measured on the client side the same
# day: 34 tests reading `notifications.js` as TEXT all passed while a stray brace
# would have stopped the browser parsing it at all. A suite can be entirely green
# about a config nothing loads, exactly as it can be about an app that does not start.
#
# ⚠️ These assert the key RESOLVES, never what it resolves TO. The values are an
# operator's to change without breaking a test — pinning them here would convert
# Rick's runtime switches back into things that need a code edit, which is the
# defect this whole module exists to remove.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "key_attr", [ "INI_KEY_APPROVERS", "INI_KEY_ENFORCEMENT", "INI_KEY_DEFAULT_TO_HOLDING" ] )
def test_each_INI_key_this_module_names_actually_exists_in_the_config( key_attr ):
    """
    Reads the REAL config through the REAL ConfigurationManager — the one path no
    other test in this file takes.
    """
    from cosa.config.configuration_manager import ConfigurationManager

    key   = getattr( approval, key_attr )
    value = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get( key, return_type="string" )
    assert value is not None, (
        f"{key_attr} names {key!r}, which the config does not resolve. `_ini_value` "
        f"swallows this and returns the fallback, so the operator's configured value "
        f"is ignored with nothing failing anywhere."
    )


def test_the_config_probe_can_actually_fail():
    """
    THE POSITIVE CONTROL ON THE TEST ABOVE, and it is not decoration: without it, a
    ConfigurationManager that returned a non-None value for EVERY key — including
    ones that do not exist — would pass the parametrized test three times over and
    prove nothing at all.
    """
    from cosa.config.configuration_manager import ConfigurationManager

    absent = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get(
        "task approval a key that deliberately does not exist", return_type="string"
    )
    assert absent is None, (
        "the config manager answered a key that does not exist — the test above "
        "cannot distinguish a present key from an absent one and proves nothing"
    )


# ---------------------------------------------------------------------------
# THE HOLDING AREA IS SELF-EXPIRING
#
# 🔨 RICK RULED 2026-09-02, by voice: `not_approved` expires "like a chase on a
# parked row." Same mechanism — computed at READ time, never written back, no
# daemon and no sweeper. A sweeper that stops running leaves rows buried forever,
# silently; a predicate that stops running returns nothing at all, loudly.
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone


@pytest.fixture
def clock():
    return datetime.now( timezone.utc )


def _iso( now, **delta ):
    return ( now + timedelta( **delta ) ).isoformat()


def test_a_holding_row_hides_while_its_chase_is_in_the_future( clock ):
    """The silence the chase buys, and the only arm that returns True."""
    from cosa.rest.task_store_owed import holding_is_active
    assert holding_is_active( "not_approved", _iso( clock, hours=4 ), clock ) is True


def test_an_EXPIRED_holding_row_stops_hiding_itself( clock ):
    """
    THE RULING, and the arm the whole feature exists for. Without it the holding
    area fills from both ends — new tickets in, demotions back — and nothing ever
    forces anyone to look at it.
    """
    from cosa.rest.task_store_owed import holding_is_active
    assert holding_is_active( "not_approved", _iso( clock, hours=-4 ), clock ) is False


def test_a_chase_nobody_can_read_surfaces_the_row_rather_than_hiding_it( clock ):
    """
    FAIL-LOUD-TOWARD-VISIBLE. A row must never hide indefinitely on the strength of
    a field nobody can parse — that is a permanent silence bought by a typo.
    """
    from cosa.rest.task_store_owed import holding_is_active
    for junk in ( None, "", "not-a-date", 42, [ ] ):
        assert holding_is_active( "not_approved", junk, clock ) is False, f"{junk!r} bought silence"


def test_the_chase_arithmetic_never_touches_a_row_of_another_status( clock ):
    """
    Status is checked FIRST. A `parked` row with a live chase must not be reported
    as an active HOLDING row — the two predicates answer about different statuses
    and must not overlap, or a parked row would hide twice for one reason.
    """
    from cosa.rest.task_store_owed import holding_is_active
    for status in ( "queued", "in_progress", "blocked", "parked", "review", "done", "wont_fix" ):
        assert holding_is_active( status, _iso( clock, hours=4 ), clock ) is False


def test_the_boundary_matches_parked_EXACTLY_rather_than_by_coincidence( clock ):
    """
    Rick said "like a chase on a parked row", so `chase == now` must resolve the same
    way in both. Asserted as an EQUALITY between the two predicates rather than as a
    literal False: if the parked boundary is ever re-cut, this reddens instead of the
    two silently drifting apart.
    """
    from cosa.rest.task_store_owed import holding_is_active, park_is_active
    at_now = clock.isoformat()
    assert holding_is_active( "not_approved", at_now, clock ) == park_is_active( "parked", at_now, clock )


def test_the_python_predicate_and_its_SQL_twin_agree( clock ):
    """
    🔴 THE DIVERGENCE THIS MODULE'S LAYOUT EXISTS TO CATCH. Two implementations of one
    rule, each individually plausible; only their disagreement is wrong, and nothing
    in either one's output would reveal it.

    Compared as compiled SQL against the parked twin's, since both must have the same
    SHAPE — a NULL guard, a status test and a `>` comparison. The `isnot( None )` is
    load-bearing in SQL and NOT redundant: a comparison against NULL yields NULL
    rather than False, so without it a chase-less row would be neither in the set nor
    out of it. The Python side reaches the same verdict by a different mechanism,
    which is exactly why both need testing.
    """
    from cosa.rest.task_store_owed import holding_is_active_clause, park_is_active_clause
    from cosa.rest.postgres_models import TaskItem

    holding = str( holding_is_active_clause( TaskItem, clock ) )
    parked  = str( park_is_active_clause(  TaskItem, clock ) )

    assert "IS NOT NULL" in holding, "the NULL guard is missing — a chase-less row would be neither in nor out"
    assert "next_chase_ts >" in holding
    # Same shape as the predicate it was modelled on: a reader comparing them should
    # find nothing to compare but the status constant.
    assert holding.replace( "status_1", "S" ) == parked.replace( "status_1", "S" )


# ---------------------------------------------------------------------------
# THE GRANDFATHER QUESTION — the P0's last genuinely-open item (row 8af64f5a)
#
# The P0 body says Phase 4 should "grandfather the 13 live rows to approved". The
# word appears nowhere in the tree, and the audit that found that stopped there:
# it MAY be unnecessary by construction, and that was explicitly NOT established.
#
# These two tests establish it, and they are written so a later change that MAKES
# a grandfather step necessary reddens instead of passing quietly:
#
#   1. there is no status to grandfather TO, and
#   2. the flip's one effect is reachable only from a CREATE, so it cannot touch
#      a row that already exists.
#
# ⚠️ Both are readings of THIS tree. Neither says a grandfather step is unnecessary
# in general — they say the two things that would make one necessary here are absent.
# ---------------------------------------------------------------------------

def test_there_is_no_approved_status_to_grandfather_rows_to():
    """
    The P0's "grandfather the 13 live rows to approved" names an operation with no
    target: the store has `not_approved` and no `approved`.

    The positive control is load-bearing — without it a renamed or emptied
    VALID_STATUSES would satisfy the negative assertion perfectly.
    """
    from cosa.rest import task_store_rules as rules

    assert "not_approved" in rules.VALID_STATUSES          # positive control
    assert "approved" not in rules.VALID_STATUSES

    # And nothing a row can already hold is hidden by the holding-area vocabulary:
    # BOARD_INVISIBLE is the terminal set plus not_approved, so a queued /
    # in_progress / blocked / parked / claimed / review row stays exactly as visible
    # after the flip as before it.
    pre_existing = set( rules.VALID_STATUSES ) - set( rules.TERMINAL_STATUSES ) - { "not_approved" }
    assert pre_existing, "the sweep found no pre-existing statuses — the corpus is empty, not clean"
    assert pre_existing.isdisjoint( set( rules.BOARD_INVISIBLE_STATUSES ) )


def test_the_holding_default_can_only_reach_a_create_never_an_existing_row():
    """
    `default_mint_status()` is the whole of the flip. It is called from exactly one
    place — inside `create_task` — so flipping the flag cannot reach a stored row.

    Corpus is git-derived (tracked, non-test `.py` under src/) so the count is a fact
    about the repository rather than about whatever is lying in this working tree.
    The definition site is asserted separately as the positive control: without it, a
    search that matched nothing at all would pass.
    """
    import subprocess

    from cosa.rest import task_approval_settings as approval

    root  = subprocess.run( [ "git", "rev-parse", "--show-toplevel" ],
                            capture_output=True, text=True, check=True ).stdout.strip()
    # 🔴 A PLAIN DIRECTORY PREFIX, NEVER "src/**/*.py" — a git pathspec is not shell
    # globstar: `**/` requires an intervening directory, so that form silently drops
    # every file sitting directly in `src/` and returns a confident partial answer.
    hits  = subprocess.run( [ "git", "grep", "-l", "default_mint_status", "--", "src/" ],
                            cwd=root, capture_output=True, text=True ).stdout.split()
    files = { h for h in hits
              if h.endswith( ".py" ) and "/tests/" not in h
              and not h.rsplit( "/", 1 )[ -1 ].startswith( "test_" ) }

    assert "src/cosa/rest/task_approval_settings.py" in files, \
        "the definition site is missing — the search found nothing, which is not the same as no callers"
    assert files == { "src/cosa/rest/task_approval_settings.py",
                      "src/cosa/rest/routers/tasks.py" }, \
        f"a new reader of the holding default appeared: {sorted( files )}"

    # ...and the one caller substitutes ONLY when the payload named no status, so a
    # status that already exists on a row is never the thing being defaulted.
    from cosa.rest.routers.tasks import TaskCreateIn
    common = { "item_class": "task", "title": "t", "created_by": "mr radio dde22022",
               "project": "lupin" }
    assert "status" not in TaskCreateIn( **common ).model_fields_set
    assert "status"     in TaskCreateIn( **common, status="queued" ).model_fields_set
    assert approval.default_mint_status() in ( "queued", "not_approved" )
