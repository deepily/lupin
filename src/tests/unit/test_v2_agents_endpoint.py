#!/usr/bin/env python3
"""
GET /api/v2/agents — the read endpoint over the registry (2026.08.22 plan §5.1,
phase 2), and the §6 gates that keep it honest.

Hermetic: the endpoint is mounted on a bare FastAPI app with both dependencies
overridden, so no auth backend and no real AskFlow stack are touched. :7999-eligible.

WHAT THESE GATES ARE FOR. The failure mode of registry work is a green suite bought
by weakening an assertion, and the two gates the plan shipped were both that:

  · gate 1 (endpoint equals the registry) was the good one and is kept as written.
  · gate 3 asked about `speakable` while the dropdown is governed by
    `user_initiable`, so a command that is typeable-but-not-sayable could be missing
    from the dropdown with the gate fully green. Rewritten here as a set-equality on
    the field that actually governs — same shape as gate 1, different table column.
    Its falsification is a set difference, never a count: the plan's own ⚠️
    disqualifies counts, and gate 3's original falsification was one.

Run: PYTHONPATH=src .venv/bin/pytest src/tests/unit/test_v2_agents_endpoint.py -v
"""

import types
from unittest import mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from cosa.rest.routers import v2_ask
from cosa.rest.v2.registry import (
    AUTO_ROUTE_VALUE,
    REGISTRY,
    USER_INITIABLE_COMMANDS,
    CommandClass,
)
from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS


USER = { "uid": "u-1", "email": "someone@example.com" }


def _client( crud_enabled=False, current_user=USER ):
    """Mount the endpoint with a flow that carries nothing but `crud_enabled`.

    The endpoint reads exactly one thing off the flow, so the fake declares exactly
    one thing. A fake with more surface than the code uses hides which coupling is
    real.
    """
    app = FastAPI()
    app.include_router( v2_ask.router )
    app.dependency_overrides[ v2_ask.get_current_user ] = lambda: current_user
    app.dependency_overrides[ v2_ask.get_ask_flow ]     = lambda: types.SimpleNamespace( crud_enabled=crud_enabled )
    return TestClient( app )


def _agents( crud_enabled=False ):
    response = _client( crud_enabled ).get( "/api/v2/agents" )
    assert response.status_code == 200, response.text
    return response.json()


def _by_command( payload ):
    return { a[ "command" ]: a for a in payload[ "agents" ] }


def _mode_to_command():
    """The mode-key → routing-command map, for the two MODE_METADATA boundary tests.

    Built from AGENTIC_MODE_MAP (which already IS this map for the agentic half) plus
    the seven conversational keys, which have no such map because their command is
    just "agent router go to {key}" — except `datetime`, whose key matches, and
    `receptionist`, which is classed NONE. Written out rather than synthesised from
    an f-string so a renamed command has to be edited here, visibly, instead of
    silently resolving to a key that no longer exists.
    """
    from cosa.rest.todo_fifo_queue import AGENTIC_MODE_MAP
    mapping = dict( AGENTIC_MODE_MAP )
    mapping.update( {
        "math"        : "agent router go to math",
        "calendar"    : "agent router go to calendar",
        "weather"     : "agent router go to weather",
        "receptionist": "agent router go to receptionist",
        "todo"        : "agent router go to todo",
        "datetime"    : "agent router go to datetime",
        "calculator"  : "agent router go to calculator",
    } )
    return mapping


_MODE_TO_COMMAND = _mode_to_command()


# ══════════════════════════════════════════════════════════════════════════════
# GATE 1 — the endpoint equals the registry
# ══════════════════════════════════════════════════════════════════════════════

class TestGate1EndpointEqualsRegistry:
    """A set-equality across a REAL boundary — an HTTP response body against a
    Python table. Falsify it by adding a spec to the table: this goes red until the
    endpoint carries it."""

    def test_command_set_equals_registry( self ):
        served = { a[ "command" ] for a in _agents()[ "agents" ] }
        assert served == set( REGISTRY ), (
            f"served-but-not-registered: {served - set( REGISTRY )}; "
            f"registered-but-not-served: {set( REGISTRY ) - served}"
        )

    def test_class_matches_registry_command_for_command( self ):
        # "class for class" — the plan's words. A projection that served every
        # command but mislabelled its class would pass the set-equality above.
        served = { a[ "command" ]: a[ "cls" ] for a in _agents()[ "agents" ] }
        assert served == { c: s.cls.value for c, s in REGISTRY.items() }

    def test_no_command_is_served_twice( self ):
        # A set-equality cannot see a duplicate; the registry is a dict, so a
        # duplicate here could only come from the projection loop itself.
        served = [ a[ "command" ] for a in _agents()[ "agents" ] ]
        assert len( served ) == len( set( served ) )


# ══════════════════════════════════════════════════════════════════════════════
# GATE 3 (server half) — the dropdown's set is governed by `user_initiable`
# ══════════════════════════════════════════════════════════════════════════════

class TestGate3UserInitiableIsTheGoverningField:
    """The blocker fix. Gate 3 as the plan shipped it tested `speakable`; after
    ruling 1 the dropdown is governed by `user_initiable`, and the two fields
    genuinely differ — so the original gate could be green while the dropdown showed
    the wrong set. These assert the field that governs."""

    # ⚠️ WHAT THIS SET-EQUALITY DOES NOT PROVE. USER_INITIABLE_COMMANDS is DERIVED
    # from REGISTRY, so it proves the ENDPOINT matches the TABLE — a real boundary,
    # HTTP body against Python dict — and nothing about whether the table is RIGHT.
    # Clear one spec's user_initiable and both sides move together; measured, that
    # mutation leaves this assertion green. The table's own content is pinned by the
    # NAMED per-command assertions below (receptionist, both expediters, TFE resume,
    # `none`, `automatic`) — those are the ones that go red on a data change, and
    # deleting one silently removes the only check on that command.
    def test_served_user_initiable_set_equals_the_registry_projection( self ):
        served = { a[ "command" ] for a in _agents()[ "agents" ] if a[ "user_initiable" ] }
        assert served == set( USER_INITIABLE_COMMANDS ), (
            f"served-but-not-initiable: {served - set( USER_INITIABLE_COMMANDS )}; "
            f"initiable-but-not-served: {set( USER_INITIABLE_COMMANDS ) - served}"
        )

    def test_a_typeable_but_not_sayable_command_is_served_as_user_initiable( self ):
        """THE MANUFACTURED DISCRIMINATOR — Clayton's correction to the review,
        2026-08-22, and the reason this test exists rather than a comment.

        He measured what I had not: `user_initiable − speakable` is EMPTY today. The
        two commands separating the sets (`automatic`, `none`) are both held out of
        the dropdown, so a gate written on `user_initiable` and one written on
        `speakable` are green on exactly the same inputs. The defect the field was
        invented for is LATENT, not live.

        A gate whose discriminator is absent from the data asserts nothing about the
        thing it is named after, so the case has to be MANUFACTURED: a synthetic spec
        that is typeable and not sayable, pushed through the real projection. Without
        this, the whole `user_initiable` rewrite could be reverted to `speakable` and
        the suite would notice only by accident — through `automatic` and `none`
        going the other way, which is a different fact."""
        from cosa.rest.v2.registry import AgentSpec, CommandClass, REGISTRY

        typed_only = AgentSpec(
            "agent router go to typed only", cls=CommandClass.AGENTIC,
            display_name="Typed Only", description="Typeable, not sayable",
            speakable=False, user_initiable=True,
        )
        widened = dict( REGISTRY )
        widened[ typed_only.command ] = typed_only
        with mock.patch.dict( "cosa.rest.v2.registry.REGISTRY", widened, clear=True ):
            served = _by_command( _agents() )

        assert typed_only.command in served, (
            "a user_initiable, non-speakable command did not reach the dropdown — "
            "which is exactly the hole the field was ratified to close"
        )
        assert served[ typed_only.command ][ "user_initiable" ] is True
        assert served[ typed_only.command ][ "speakable" ]      is False

    def test_the_two_fields_are_not_the_same_set( self ):
        # The whole reason `user_initiable` was ratified as its own field. If these
        # two sets were equal, every assertion above could be satisfied by reading
        # `speakable` and nobody would notice — the coincidence the plan §5.1 warns
        # about. This pins that they have ALREADY diverged, so the coincidence is
        # not available to a future edit.
        agents    = _agents()[ "agents" ]
        speakable = { a[ "command" ] for a in agents if a[ "speakable" ] }
        initiable = { a[ "command" ] for a in agents if a[ "user_initiable" ] }
        assert speakable != initiable
        # And name the divergence in both directions, so a change that collapses it
        # says which way it collapsed.
        assert "none" in speakable - initiable
        assert "agent router go to automatic" in speakable - initiable

    def test_both_expediters_are_not_user_initiable( self ):
        # Ruled 2026-08-22: their only argument is a job id produced by a job that
        # already failed. You press a button on that job's card; you do not type it.
        served = _by_command( _agents() )
        assert served[ "agent router go to bug fix expediter" ][ "user_initiable" ] is False
        assert served[ "agent router go to test fix expediter" ][ "user_initiable" ] is False

    def test_tfe_resume_is_user_initiable( self ):
        # The one genuine gap the plan identified: `resume_from` is a plan path or a
        # description a person types, which is why it has a submit card today — and
        # why that card has no job left once the dropdown can express the command.
        assert _by_command( _agents() )[ "agent router go to test fix expediter resume" ][ "user_initiable" ] is True

    def test_receptionist_is_user_initiable_but_still_classed_none( self ):
        # Rick's ruling 3, and the reason the dropdown is NOT driven off `cls`:
        # `cls=NONE` describes how the ROUTER reaches it, `user_initiable` says a
        # person may pick it. Both are true at once.
        entry = _by_command( _agents() )[ "agent router go to receptionist" ]
        assert entry[ "user_initiable" ] is True
        assert entry[ "cls" ] == CommandClass.NONE.value

    def test_the_internal_no_command_outcome_is_not_pickable( self ):
        assert _by_command( _agents() )[ "none" ][ "user_initiable" ] is False


# ══════════════════════════════════════════════════════════════════════════════
# The projection's fields
# ══════════════════════════════════════════════════════════════════════════════

class TestProjectedFields:

    def test_every_user_initiable_command_carries_a_display_name( self ):
        # The option text. A dropdown entry falling back to its raw command string
        # would render "agent router go to swe team" where "SWE Team" belongs.
        missing = [ a[ "command" ] for a in _agents()[ "agents" ]
                    if a[ "user_initiable" ] and a[ "display_name" ] == a[ "command" ] ]
        assert missing == []

    def test_display_names_are_the_mode_metadata_strings( self ):
        """The other half of the 16 MODE_METADATA entries. Same boundary crossing as
        the descriptions below, and the same reason: the strings served must be the
        ones that were MOVED, not new ones written to make a test pass. Retire this
        with its sibling when phase 7 deletes MODE_METADATA.

        ONE NAMED EXCEPTION, and it is a drift this gate FOUND rather than one it
        excuses. MODE_METADATA calls `presentation` "Presentation"; JOB_ARG_CONTRACTS
        calls the same command "Presentation Generator". Two hand-maintained lists
        that had already disagreed — which is the whole reason this plan exists.

        The contract wins, for a reason and not by convenience: the argument
        expeditor already speaks the contract's name during the interview, so a user
        who picks it hears "Presentation Generator" today. The dropdown was the
        outlier, and MODE_METADATA is the list being retired. Effect: that option's
        text changes from "Presentation" to "Presentation Generator", which is an
        E2E-visible change and is deliberate.

        The exception is a single named command, not a predicate. A second entry
        appearing here means a NEW drift, and it should go red."""
        from cosa.rest.todo_fifo_queue import MODE_METADATA
        drifted_before_this_plan = { "presentation": "Presentation Generator" }
        served = _by_command( _agents() )
        for mode, meta in MODE_METADATA.items():
            if mode == "system":
                continue                                   # the Auto-Route sentinel, not a command
            command  = _MODE_TO_COMMAND[ mode ]
            expected = drifted_before_this_plan.get( mode, meta[ "display_name" ] )
            assert served[ command ][ "display_name" ] == expected, (
                f"{command}: display_name drifted from MODE_METADATA[{mode!r}]"
            )

    def test_the_recorded_presentation_drift_is_still_the_only_one( self ):
        # Pins the exemption above so it cannot quietly widen. If MODE_METADATA is
        # corrected to "Presentation Generator", this goes red and the exemption
        # should be DELETED, not kept as a no-op that would then hide the next drift.
        from cosa.rest.todo_fifo_queue import MODE_METADATA
        served  = _by_command( _agents() )
        drifted = { mode for mode, meta in MODE_METADATA.items()
                    if mode != "system"
                    and served[ _MODE_TO_COMMAND[ mode ] ][ "display_name" ] != meta[ "display_name" ] }
        assert drifted == { "presentation" }, (
            f"the set of MODE_METADATA display-name drifts changed: {drifted}"
        )

    def test_display_name_and_label_are_different_registers( self ):
        # Ruled 2026-08-22: one string is READ in a dropdown, one is HEARD in spoken
        # text. If they were interchangeable the second field would be dead weight and
        # a later edit would rightly collapse them — which is what turned "Math Agent"
        # into "math" in the first cut. Pin that they have already diverged.
        served = _by_command( _agents() )
        assert served[ "agent router go to datetime" ][ "display_name" ] == "Date & Time"
        assert served[ "agent router go to datetime" ][ "label" ]        == "date and time"
        differing = [ a[ "command" ] for a in _agents()[ "agents" ]
                      if a[ "display_name" ] != a[ "label" ] ]
        assert differing, "display_name and label are identical everywhere — one of them is dead weight"

    def test_every_user_initiable_command_carries_a_description( self ):
        # The 16 MODE_METADATA strings moved in for exactly this: they are the only
        # user-facing help text on the whole surface, and a dropdown entry with no
        # description is one that lost its string in the move.
        missing = [ a[ "command" ] for a in _agents()[ "agents" ]
                    if a[ "user_initiable" ] and not a[ "description" ] ]
        assert missing == []

    def test_descriptions_are_the_mode_metadata_strings( self ):
        # Crosses a real boundary while MODE_METADATA still exists: the strings the
        # endpoint serves must be the ones that were moved, not new ones written to
        # make a test pass. Retire this when phase 7 deletes MODE_METADATA.
        from cosa.rest.todo_fifo_queue import MODE_METADATA
        served = _by_command( _agents() )
        for mode, meta in MODE_METADATA.items():
            if mode == "system":
                continue                                   # the Auto-Route sentinel, not a command
            command = _MODE_TO_COMMAND[ mode ]
            assert served[ command ][ "description" ] == meta[ "description" ], (
                f"{command}: description drifted from MODE_METADATA[{mode!r}]"
            )

    def test_agentic_commands_carry_their_contract_fields( self ):
        served   = _by_command( _agents() )
        entry    = served[ "agent router go to deep research" ]
        contract = JOB_ARG_CONTRACTS[ "agent router go to deep research" ]
        assert entry[ "job_prefix" ]    == contract[ "job_prefix" ]
        assert entry[ "required_args" ] == list( contract[ "required_user_args" ] )
        assert entry[ "arg_questions" ] == dict( contract[ "fallback_questions" ] )
        assert entry[ "display_name" ]  == contract[ "display_name" ]

    def test_every_agentic_display_name_comes_from_its_contract( self ):
        # Not one spot-check: the agentic display names are pulled from the contract
        # at construction precisely so there is no second hand-written list to drift.
        # This is what would go red if somebody typed one in by hand.
        served = _by_command( _agents() )
        for command, contract in JOB_ARG_CONTRACTS.items():
            assert served[ command ][ "display_name" ] == contract[ "display_name" ], command

    def test_conversational_commands_carry_aliases_and_literal_required_args( self ):
        served = _by_command( _agents() )
        assert served[ "agent router go to weather" ][ "required_args" ] == [ "location" ]
        assert "weather" in served[ "agent router go to weather" ][ "aliases" ]
        assert served[ "agent router go to math" ][ "required_args" ] == []

    def test_non_agentic_commands_carry_no_job_prefix( self ):
        for agent in _agents()[ "agents" ]:
            if agent[ "cls" ] != CommandClass.AGENTIC.value:
                assert agent[ "job_prefix" ] is None, agent[ "command" ]

    def test_a_command_with_no_label_and_no_contract_falls_back_to_its_command( self ):
        # `agent router go to automatic` has neither. The fallback is deliberate:
        # nobody renders it, and an invented label would be the one string in this
        # response that came from nowhere.
        served = _by_command( _agents() )
        assert served[ "agent router go to automatic" ][ "display_name" ] == "agent router go to automatic"
        assert served[ "agent router go to automatic" ][ "label" ]        == "agent router go to automatic"
        assert served[ "none" ][ "display_name" ] == "none"
        assert served[ "none" ][ "label" ]        == "none"


# ══════════════════════════════════════════════════════════════════════════════
# The CRUD fork — the label must name the agent that will actually run
# ══════════════════════════════════════════════════════════════════════════════

class TestCrudFork:
    """The endpoint honours `crud_enabled` exactly as resolve() does — by CALLING
    resolve(), not by reimplementing the fork. These pin that a flag flip changes
    the two forked agents and nothing else."""

    def test_fork_off_serves_the_base_labels( self ):
        served = _by_command( _agents( crud_enabled=False ) )
        assert served[ "agent router go to todo" ][ "label" ]            == "todo list"
        assert served[ "agent router go to todo" ][ "display_name" ]     == "Todo List"
        assert served[ "agent router go to calendar" ][ "label" ]        == "calendaring"
        assert served[ "agent router go to calendar" ][ "display_name" ] == "Calendar"

    def test_fork_on_serves_the_forked_labels( self ):
        served = _by_command( _agents( crud_enabled=True ) )
        assert served[ "agent router go to todo" ][ "label" ]            == "todo (CRUD)"
        assert served[ "agent router go to calendar" ][ "label" ]        == "calendar (CRUD)"

    def test_fork_on_forks_the_read_label_too( self ):
        # BOTH strings move together or a user reads "Todo List" while hearing
        # "todo (CRUD)" about the same request. Forking `label` alone was the easy
        # miss here, because `label` is the one resolve() already handled.
        served = _by_command( _agents( crud_enabled=True ) )
        assert served[ "agent router go to todo" ][ "display_name" ]     == "Todo List (CRUD)"
        assert served[ "agent router go to calendar" ][ "display_name" ] == "Calendar (CRUD)"

    def test_the_flag_changes_those_two_and_nothing_else( self ):
        off = _by_command( _agents( crud_enabled=False ) )
        on  = _by_command( _agents( crud_enabled=True  ) )
        changed = { c for c in off if off[ c ] != on[ c ] }
        assert changed == { "agent router go to todo", "agent router go to calendar" }


# ══════════════════════════════════════════════════════════════════════════════
# The Auto-Route sentinel — blocker fix (b)
# ══════════════════════════════════════════════════════════════════════════════

class TestAutoRouteSentinel:
    """Auto-Route ships in the RESPONSE so the page hand-writes no option at all.
    That is what leaves the front-end guard (gate 2) with nothing to exempt — and an
    exemption without a written reason is how these guards get quietly widened."""

    def test_auto_route_is_served( self ):
        auto = _agents()[ "auto_route" ]
        # The equality alone is a TAUTOLOGY: both sides read the same constant, so it
        # stays green even if the sentinel is blanked to "". The tell was already in
        # this block — `label` and `description` are checked for truthiness and
        # `value` was not. A blank sentinel makes isAutoRoute() return true for EVERY
        # pick (agent-select.js), so the user's chosen command is silently discarded
        # and everything auto-routes. Silent and total is the expensive kind.
        assert auto[ "value" ]
        assert auto[ "value" ] == AUTO_ROUTE_VALUE
        assert auto[ "label" ]
        assert auto[ "description" ]

    def test_the_sentinel_can_never_collide_with_a_command( self ):
        # If it ever did, an option value would be ambiguous between "route this to
        # X" and "route this automatically" — and the set-equality in gate 3 would
        # have to subtract a real command to stay green.
        assert AUTO_ROUTE_VALUE not in REGISTRY

    def test_the_sentinel_is_not_the_control_command( self ):
        # `agent router go to automatic` is the VOICE way to clear a sticky mode.
        # Auto-Route is "do not name a command at all". Different acts; conflating
        # them would put a submittable command behind the one option that must not
        # submit.
        assert AUTO_ROUTE_VALUE != "agent router go to automatic"
        assert _by_command( _agents() )[ "agent router go to automatic" ][ "user_initiable" ] is False


# ══════════════════════════════════════════════════════════════════════════════
# Auth
# ══════════════════════════════════════════════════════════════════════════════

class TestAuth:
    """This endpoint requires authentication but reads NOTHING off the token — it
    serves the same table to every caller. So it does not carry the uid/email 401s
    its three sibling endpoints do: those exist because ask/submit/resume pass
    user_id downstream, and adding the check here would be a branch the code has no
    use for, kept alive by a test written to cover it.

    What IS worth pinning is that the door is not open. dependency_overrides
    replaces get_current_user in every other test in this file, so no request-level
    assertion can see the real gate — read the route's declared dependencies
    instead. Falsify it by deleting `Depends( get_current_user )` from the
    signature: this goes red, and nothing else in the file does."""

    def test_the_endpoint_requires_authentication( self ):
        app   = FastAPI()
        app.include_router( v2_ask.router )
        route = next( r for r in app.routes if getattr( r, "path", None ) == "/api/v2/agents" )
        assert v2_ask.get_current_user in [ d.call for d in route.dependant.dependencies ]

    def test_the_endpoint_reads_the_flow_for_the_crud_flag( self ):
        # The other half of the same read: if this dependency were dropped, the
        # labels would silently stop tracking the fork and every CRUD assertion
        # above would still be satisfiable by a hardcoded label.
        app   = FastAPI()
        app.include_router( v2_ask.router )
        route = next( r for r in app.routes if getattr( r, "path", None ) == "/api/v2/agents" )
        assert v2_ask.get_ask_flow in [ d.call for d in route.dependant.dependencies ]


# ══════════════════════════════════════════════════════════════════════════════
# install_ask_flow / get_ask_flow — the installed-flow seam
# ══════════════════════════════════════════════════════════════════════════════

class TestInstalledFlowSeam:
    """Not part of this phase, but the two lines it covers are the last uncovered
    ones in v2_ask.py (measured 98% at 9b49f04d, same gap), and the 100% mandate
    applies to the whole file. install_ask_flow is what lifespan calls so the door
    and the in-process callers share ONE flow object; without a test, deleting the
    assignment leaves every unit test green because they all override the dependency.

    Restores the module global itself — a test that installs a flow and walks away
    would leak it into every later test in the session, which is a worse defect than
    the gap it closes."""

    def test_an_installed_flow_is_what_get_ask_flow_serves( self, monkeypatch ):
        sentinel = types.SimpleNamespace( crud_enabled=False, tag="installed" )
        monkeypatch.setattr( v2_ask, "_INSTALLED_FLOW", None )
        v2_ask.install_ask_flow( sentinel, enabled=True )
        assert v2_ask.get_ask_flow() is sentinel

    def test_an_installed_but_disabled_flow_still_503s( self, monkeypatch ):
        # The feature gate applies to BOTH paths — installing a flow must not be a
        # way around `v2 flow enabled`.
        monkeypatch.setattr( v2_ask, "_INSTALLED_FLOW", None )
        v2_ask.install_ask_flow( types.SimpleNamespace( crud_enabled=False ), enabled=False )
        with pytest.raises( HTTPException ) as caught:
            v2_ask.get_ask_flow()
        assert caught.value.status_code == 503
