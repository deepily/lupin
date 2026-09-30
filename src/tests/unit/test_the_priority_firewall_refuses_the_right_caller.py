#!/usr/bin/env python3
"""
The priority firewall — three rules, three refusals, and a POSITIVE arm for each.

Row b8205986. Rick's broadcast e254ec7d, 2026-09-07.

🔴 EVERY RULE GETS A POSITIVE ARM, AND THAT IS THE ACCEPTANCE, NOT A NICETY. The row
says so: "plus a POSITIVE arm per rule (the permitted actor SUCCEEDS), or the test
proves only that the door can refuse." A gate that refuses everybody passes every
negative test ever written for it.

⚠️ WHAT THESE TESTS CANNOT PROVE, said here so nobody quotes them for more than they
carry. Rules 2-3 rest on a bridge role the session writes about ITSELF. A test that
passes `bridge_role="manager"` has DECLARED the caller a manager; it has not shown
that a real caller could not declare the same. So these are tests of a POLICY CONTROL,
not of a security boundary — exactly as the module's own docstring says, and exactly
as Rick ruled knowing the consequence.

RULE 1 IS THE EXCEPTION and is tested as such: it keys on a validated account, so
`test_rule_1_ignores_a_declared_role_entirely` genuinely shows that no string a caller
types gets them P0.
"""
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import task_priority_firewall as fw


RICK_EMAIL = "ricardo.felipe.ruiz@gmail.com"


@pytest.fixture
def operator( monkeypatch ):
    """
    A caller whose VALIDATED account resolves to the operator.

    Patched at `approver_persona_for_account` — the module's own import — so the test
    STATES the account mapping instead of depending on whatever the live INI happens
    to hold today. The INI is an operator-editable file; a test that reads it asserts
    the operator's current preference, which is exactly the defect that reddened six
    tests in test_spawn_sessions.py this same morning.
    """
    monkeypatch.setattr( fw, "approver_persona_for_account",
                         lambda email: "rick" if email == RICK_EMAIL else None )
    return RICK_EMAIL


# ── RULE 1: P0 is the operator's alone ────────────────────────────────────────

class TestRule1OperatorOnlyP0:
    def test_rule_1_refuses_a_manager_setting_p0( self, operator ):
        # THE test of this row. A manager passes rule 2 and must STILL be refused P0 —
        # if the two checks were ordered the other way, this is what would slip
        # through, and it is the one Rick said "full stop" about.
        refusal = fw.refusal_for_priority_change( "P1", "P0", bridge_role="manager" )
        assert refusal is not None
        assert "P0" in refusal
        assert "operator" in refusal.lower()

    def test_rule_1_refuses_a_worker_setting_p0( self, operator ):
        assert fw.refusal_for_priority_change( "P3", "P0" ) is not None

    def test_rule_1_refuses_p0_on_create_too( self, operator ):
        # Rule 1 is about the VALUE, not the door. Create is the other way in, and a
        # firewall that guards only the edit path is half a firewall.
        assert fw.refusal_for_priority_create( "P0", bridge_role="manager" ) is not None

    def test_rule_1_POSITIVE_the_operator_sets_p0( self, operator ):
        # The positive arm. Without it, every assertion above is satisfied by a gate
        # that refuses everyone — including Rick.
        assert fw.refusal_for_priority_change( "P1", "P0", account_email=operator ) is None
        assert fw.refusal_for_priority_create( "P0", account_email=operator ) is None

    def test_rule_1_ignores_a_declared_role_entirely( self, operator ):
        # The forgery claim rule 1 CAN carry: no string a caller types gets them P0.
        for claimed in ( "manager", "operator", "rick", "admin", "MANAGER" ):
            assert fw.refusal_for_priority_change( "P1", "P0", bridge_role=claimed ) is not None

    def test_rule_1_ignores_a_bridge_that_says_manager( self, operator ):
        # Same claim through the OTHER source. One arm per source, because one arm
        # cannot speak for the path it did not touch.
        assert fw.refusal_for_priority_change( "P1", "P0", actor="maria 536c8ff7",
                                               manager_fn=lambda sid: True ) is not None


# ── RULE 2: raising to P1-P4 needs the operator or a manager ──────────────────

class TestRule2RaiseNeedsAManager:
    def test_rule_2_refuses_a_worker_raising_into_the_band( self ):
        for wanted in ( "P1", "P2", "P3", "P4" ):
            refusal = fw.refusal_for_priority_change( "P5", wanted )
            assert refusal is not None, f"a roleless caller was allowed to raise to {wanted}"
            assert wanted in refusal

    def test_rule_2_POSITIVE_a_manager_raises_into_the_band( self ):
        for wanted in ( "P1", "P2", "P3", "P4" ):
            assert fw.refusal_for_priority_change( "P5", wanted, bridge_role="manager" ) is None

    def test_rule_2_POSITIVE_the_operator_raises_into_the_band( self, operator ):
        assert fw.refusal_for_priority_change( "P5", "P1", account_email=operator ) is None

    def test_rule_2_does_not_police_a_lowering( self ):
        # The boundary this module deliberately does NOT own — demotion is Rick's
        # 11:58 ruling and lands on the admission path. Asserted so a later reader
        # adding a demotion check here watches a NAMED test go red first, rather
        # than discovering two modules policing one rule.
        assert fw.refusal_for_priority_change( "P1", "P5" ) is None
        assert fw.refusal_for_priority_change( "P0", "P3" ) is None

    def test_rule_2_does_not_police_a_no_op( self ):
        for p in ( "P0", "P1", "P5" ):
            assert fw.refusal_for_priority_change( p, p ) is None

    def test_a_p0_no_op_is_allowed_but_a_p0_upgrade_is_not( self ):
        # The pair that pins the check ORDER, and it caught a real defect: the first
        # cut ran rule 1 before the no-op check, so re-sending P0 at an already-P0 row
        # was refused. Rick's sentence is about an UPGRADE, and a no-op upgrades
        # nothing. BOTH arms, because either one alone is satisfied by the wrong order.
        assert fw.refusal_for_priority_change( "P0", "P0" ) is None
        assert fw.refusal_for_priority_change( "P1", "P0" ) is not None

    def test_rule_2_with_no_current_priority_still_guards_the_band( self ):
        # A row whose current priority is unreadable must not become a free raise.
        assert fw.refusal_for_priority_change( None, "P1" ) is not None


# ── RULE 3: a worker's create is P5 ───────────────────────────────────────────

class TestRule3WorkerCreatesAtTheFloor:
    def test_rule_3_refuses_a_worker_creating_above_the_floor( self ):
        for wanted in ( "P1", "P2", "P3", "P4" ):
            refusal = fw.refusal_for_priority_create( wanted )
            assert refusal is not None
            assert fw.WORKER_CREATE_PRIORITY in refusal

    def test_rule_3_POSITIVE_a_worker_files_at_the_floor( self ):
        # The normal case, and the one an over-eager gate would break silently.
        assert fw.refusal_for_priority_create( "P5" ) is None

    def test_rule_3_POSITIVE_a_manager_creates_above_the_floor( self ):
        for wanted in ( "P1", "P2", "P3", "P4" ):
            assert fw.refusal_for_priority_create( wanted, bridge_role="manager" ) is None

    def test_rule_3_POSITIVE_the_operator_creates_above_the_floor( self, operator ):
        assert fw.refusal_for_priority_create( "P1", account_email=operator ) is None

    def test_rule_3_refuses_rather_than_downgrading( self ):
        # Recorded as a test because it was a JUDGEMENT CALL, not an obvious reading.
        # Rick's "they can only file a P5 ticket" reads either way. A quiet downgrade
        # is friendlier and lets a worker believe they filed a P1 for a week. If he
        # wants the downgrade, this test is what should redden first.
        assert fw.refusal_for_priority_create( "P1" ) is not None


# ── The seams the rules rest on ───────────────────────────────────────────────

class TestNormalizePriority:
    def test_known_values_normalize( self ):
        assert fw.normalize_priority( " p0 " ) == "P0"
        assert fw.normalize_priority( "P5" )   == "P5"

    def test_unknown_and_absent_return_none( self ):
        for bad in ( None, "", "   ", "banana", "P9", 3, [ "P1" ] ):
            assert fw.normalize_priority( bad ) is None

    def test_an_unknown_value_is_not_this_modules_to_refuse( self ):
        # It belongs to task_store_rules.VALID_PRIORITIES. Two modules policing one
        # rule is two rules that agree until they do not.
        assert fw.refusal_for_priority_change( "P1", "P9" ) is None
        assert fw.refusal_for_priority_create( "banana" ) is None
        assert fw.refusal_for_priority_create( None ) is None


class TestCallerIsOperator:
    def test_an_unmapped_or_absent_account_is_not_the_operator( self, operator ):
        for bad in ( None, "", "   ", "someone@else.com", 42 ):
            assert fw.caller_is_operator( bad ) is False

    def test_the_mapped_account_is_the_operator( self, operator ):
        assert fw.caller_is_operator( operator ) is True

    def test_a_mapped_non_unconditional_persona_is_not_the_operator( self, monkeypatch ):
        # The allowlist names several approvers; only the UNCONDITIONAL one is Rick.
        # Without this, "is an approver" and "is Rick" would be the same predicate,
        # and rule 1 would quietly admit every manager on the allowlist.
        monkeypatch.setattr( fw, "approver_persona_for_account", lambda email: "maria" )
        assert fw.caller_is_operator( "maria@example.com" ) is False


class TestCallerIsManager:
    def test_an_explicit_manager_role_counts( self ):
        assert fw.caller_is_manager( "manager" ) is True
        assert fw.caller_is_manager( "MANAGER" ) is True

    def test_any_other_role_does_not( self ):
        for role in ( None, "", "   ", "worker", "author", "reviewer", 7 ):
            assert fw.caller_is_manager( role ) is False

    def test_the_operator_counts_without_a_role( self, operator ):
        assert fw.caller_is_manager( None, account_email=operator ) is True


class TestSessionIdFromActor:
    def test_a_single_word_persona_yields_its_session_id( self ):
        assert fw.session_id_from_actor( "maria 536c8ff7" ) == "536c8ff7"

    def test_a_multi_word_persona_yields_its_session_id( self ):
        # The reason it takes the LAST token rather than a fixed position: a persona
        # may be one word or three, and counting from the front is an enumeration
        # that goes wrong the first time somebody has a longer name.
        assert fw.session_id_from_actor( "mr radio 52f3fe21" ) == "52f3fe21"

    def test_a_full_uuid_is_accepted( self ):
        actor = "mr radio 52f3fe21-6928-4cf1-9a13-213e152bf42b"
        assert fw.session_id_from_actor( actor ) == "52f3fe21-6928-4cf1-9a13-213e152bf42b"

    def test_a_bare_persona_name_yields_nothing( self ):
        for bad in ( None, "", "   ", "maria", "mr radio", 7 ):
            assert fw.session_id_from_actor( bad ) is None

    def test_a_long_non_hex_tail_is_not_a_session_id( self ):
        # The character-CLASS test, not a length test — this is exactly the case a
        # length check alone would wave through.
        assert fw.session_id_from_actor( "somebody generalissimo" ) is None


class TestCallerIsManagerByBridge:
    def test_the_bridge_decides( self ):
        assert fw.caller_is_manager_by_bridge( "maria 536c8ff7",
                                               manager_fn=lambda sid: True ) is True
        assert fw.caller_is_manager_by_bridge( "maria 536c8ff7",
                                               manager_fn=lambda sid: False ) is False

    def test_the_bridge_is_asked_about_the_session_id_out_of_the_actor( self ):
        # Pins WHICH value crosses the seam. Without it, the resolver could ask the
        # bridge about the persona name and every assertion above would still pass.
        seen = [ ]
        fw.caller_is_manager_by_bridge( "mr radio 52f3fe21",
                                        manager_fn=lambda sid: seen.append( sid ) or True )
        assert seen == [ "52f3fe21" ], "the bridge was asked about the wrong thing"

    def test_no_session_id_means_no_manager_and_no_bridge_read( self ):
        called = [ ]
        result  = fw.caller_is_manager_by_bridge(
            "maria", manager_fn=lambda sid: called.append( sid ) or True )
        assert result is False
        assert called == [ ], "the bridge should not be consulted without a session id"

    def test_a_raising_bridge_fails_closed( self ):
        def boom( sid ): raise RuntimeError( "bridge unreadable" )
        assert fw.caller_is_manager_by_bridge( "maria 536c8ff7", manager_fn=boom ) is False

    def test_the_operator_outranks_the_bridge( self, operator ):
        # Even a bridge saying "not a manager" cannot demote Rick.
        assert fw.caller_is_manager_by_bridge( "rick 00000000", account_email=operator,
                                               manager_fn=lambda sid: False ) is True

    def test_the_LIVE_predicate_is_reachable_without_injection( self ):
        # 🔴 THE ARM THAT EXISTS BECAUSE COVERAGE FOUND IT MISSING. Every other test
        # here injects `manager_fn`, so the default branch — the one that imports the
        # real `is_manager_figure` — never executed once. That is precisely the
        # failure this module's own call site warns about: a gate shipped 2026-09-03
        # whose live path could not run, because all 25 of its tests injected past
        # the seam.
        #
        # It asserts a BOOL rather than True or False, deliberately. The answer
        # depends on what is on disk at `session_bridge`, and pinning it to a value
        # would make this test assert the state of the machine it runs on. What is
        # being proven is that the live path RUNS and RETURNS, not what it decides.
        result = fw.caller_is_manager_by_bridge( "nobody 00000000" )
        assert isinstance( result, bool )

    def test_an_unimportable_live_predicate_fails_closed( self, monkeypatch ):
        # The other half of the default branch. Doubt fails CLOSED here for the same
        # reason it does inside is_manager_figure: this gates a write.
        import builtins
        real_import = builtins.__import__

        def refuse( name, *args, **kwargs ):
            if "manager_figure" in name: raise ImportError( "no such module" )
            return real_import( name, *args, **kwargs )

        monkeypatch.setattr( builtins, "__import__", refuse )
        assert fw.caller_is_manager_by_bridge( "maria 536c8ff7" ) is False

    def test_the_bridge_path_actually_reaches_the_rules( self ):
        # THE WIRING TEST. Without it the resolver could be correct and unreachable —
        # a module at 100% that the rules never call, which is the "implemented but
        # not installed" shape.
        assert fw.refusal_for_priority_create( "P1", actor="maria 536c8ff7",
                                               manager_fn=lambda sid: True ) is None
        assert fw.refusal_for_priority_create( "P1", actor="maria 536c8ff7",
                                               manager_fn=lambda sid: False ) is not None
        assert fw.refusal_for_priority_change( "P5", "P2", actor="maria 536c8ff7",
                                               manager_fn=lambda sid: True ) is None
        assert fw.refusal_for_priority_change( "P5", "P2", actor="maria 536c8ff7",
                                               manager_fn=lambda sid: False ) is not None


class TestTheRefusalTellsYouHowToGetIn:
    def test_it_names_the_missing_account_rather_than_echoing_a_typed_name( self ):
        refusal = fw.refusal_for_priority_change( "P1", "P0", bridge_role="manager" )
        assert "no login account" in refusal

    def test_it_names_the_validated_account_when_there_is_one( self, monkeypatch ):
        monkeypatch.setattr( fw, "approver_persona_for_account", lambda email: None )
        refusal = fw.refusal_for_priority_change( "P1", "P0", account_email="nobody@example.com" )
        assert "nobody@example.com" in refusal

    def test_it_names_the_absent_role( self ):
        refusal = fw.refusal_for_priority_create( "P1" )
        assert "no declared role" in refusal


class TestModuleSmoke:
    def test_quick_smoke_test_runs_clean( self ):
        fw.quick_smoke_test()
