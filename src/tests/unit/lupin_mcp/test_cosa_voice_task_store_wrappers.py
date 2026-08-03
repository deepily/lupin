"""
Unit tests for the task-store MCP tool wrappers registered in cosa_voice_mcp —
task_create / task_transition / task_query + the _task_store_identity stamp.

FastMCP 2.x @mcp.tool yields FunctionTool objects that are not Python-callable;
per the established convention (test_cosa_voice_mcp_qualifier.py) we invoke the
underlying function via `.fn()`. The transport layer has its own suite
(test_task_store_tools.py) — here we pin ONLY the wrapper obligations:
identity stamping (spec §2.1: never a caller param, cannot impersonate) and
faithful parameter pass-through to the impls.

Venue: :7999-eligible (pure unit, all impls monkeypatched, no server, no state).
"""

import pytest

import lupin_mcp.cosa_voice_mcp as cv


SENTINEL = { "marker": "impl-result" }


@pytest.fixture
def stamped_identity( monkeypatch ):
    """Pin the bridge-derived identity inputs to deterministic values."""
    monkeypatch.setattr( cv, "_commons_persona_fields", lambda: { "persona_name": "krishna", "persona_icon": "🦚", "persona_color": "#0F0" } )
    monkeypatch.setattr( cv, "SESSION_ID", "38d15e3b" )
    monkeypatch.setattr( cv, "_get_server_url", lambda: "http://stub:7999" )
    monkeypatch.setattr( cv, "_mcp_outbound_api_key", lambda: "ck_live_stub" )


class TestTaskStoreIdentity:

    def test_identity_is_persona_space_session_id( self, stamped_identity ):
        # The spec §2.1 example shape: "krishna 38d15e3b"
        assert cv._task_store_identity() == "krishna 38d15e3b"

    def test_identity_falls_back_with_persona_fields( self, monkeypatch ):
        # _commons_persona_fields already absorbs bridge failure (AC3 default);
        # the stamp must compose whatever it returns, never raise.
        monkeypatch.setattr( cv, "_commons_persona_fields", lambda: { "persona_name": "<unknown>", "persona_icon": "💬", "persona_color": "#888888" } )
        monkeypatch.setattr( cv, "SESSION_ID", "01b3bf59" )
        assert cv._task_store_identity() == "<unknown> 01b3bf59"


class TestTaskCreateWrapper:

    def test_stamps_created_by_and_passes_through( self, stamped_identity, monkeypatch ):
        captured = { }
        def fake_impl( **kwargs ):
            captured.update( kwargs )
            return SENTINEL
        monkeypatch.setattr( cv, "task_create_impl", fake_impl )

        result = cv.task_create.fn(
            item_class          = "task",
            title               = "Build it",
            project             = "lupin",
            body                = "details",
            owner_persona       = "tiffany",
            accountable_manager = "tiberius",
            gate_class          = "operator",
            priority            = "P1",
            source_qid          = "qid-1",
            correlation_key     = "corr-1",
            authority           = "manager_relay",
        )

        assert result is SENTINEL
        assert captured == {
            "api_base_url"        : "http://stub:7999",
            "api_key"             : "ck_live_stub",
            "created_by"          : "krishna 38d15e3b",
            "item_class"          : "task",
            "title"               : "Build it",
            "project"             : "lupin",
            "body"                : "details",
            "owner_persona"       : "tiffany",
            "accountable_manager" : "tiberius",
            "gate_class"          : "operator",
            "priority"            : "P1",
            "urgency"             : "normal",
            "status"              : "queued",       # DEFAULT mint status (build 1b5483f4)
            "blocked_by"          : None,
            "next_chase_ts"       : None,
            "source_qid"          : "qid-1",
            "correlation_key"     : "corr-1",
            "authority"           : "manager_relay",
        }

    def test_defaults_match_spec( self, stamped_identity, monkeypatch ):
        captured = { }
        monkeypatch.setattr( cv, "task_create_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )
        cv.task_create.fn( item_class="bug", title="t", project="lupin" )
        assert captured[ "gate_class" ] == "none"
        assert captured[ "priority" ]   == "P2"
        assert captured[ "authority" ]  == "standing"
        assert captured[ "body" ]       is None
        # One-call blocked mint defaults (build 1b5483f4): status defaults queued,
        # the two blocked fields default None (forwarded to the transport verbatim).
        assert captured[ "status" ]        == "queued"
        assert captured[ "blocked_by" ]    is None
        assert captured[ "next_chase_ts" ] is None

    def test_blocked_mint_passes_through( self, stamped_identity, monkeypatch ):
        captured = { }
        monkeypatch.setattr( cv, "task_create_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )
        cv.task_create.fn(
            item_class    = "task",
            title         = "held on tiberius",
            project       = "lupin",
            status        = "blocked",
            blocked_by    = [ { "kind": "persona", "id": "tiberius" } ],
            next_chase_ts = "2026-06-12T09:00:00+00:00",
        )
        assert captured[ "status" ]        == "blocked"
        assert captured[ "blocked_by" ]    == [ { "kind": "persona", "id": "tiberius" } ]
        assert captured[ "next_chase_ts" ] == "2026-06-12T09:00:00+00:00"


class TestTaskTransitionWrapper:

    def test_stamps_actor_and_passes_through( self, stamped_identity, monkeypatch ):
        captured = { }
        monkeypatch.setattr( cv, "task_transition_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )

        result = cv.task_transition.fn(
            task_id       = "abc-uuid",
            to_status     = "blocked",
            receipt_refs  = { "commit": "f4e0370" },
            next_chase_ts = "2026-06-13T09:00:00-04:00",
            blocked_by    = [ { "kind": "user", "id": "rick" } ],
            reason        = "waiting on Rick's gate",
            authority     = "user_direct",
        )

        assert result is SENTINEL
        assert captured == {
            "api_base_url"  : "http://stub:7999",
            "api_key"       : "ck_live_stub",
            "actor"         : "krishna 38d15e3b",
            "task_id"       : "abc-uuid",
            "to_status"     : "blocked",
            "receipt_refs"  : { "commit": "f4e0370" },
            "next_chase_ts" : "2026-06-13T09:00:00-04:00",
            "blocked_by"    : [ { "kind": "user", "id": "rick" } ],
            "reason"        : "waiting on Rick's gate",
            "authority"     : "user_direct",
            "park_reason"   : None,          # park wiring (f68bc520) — always forwarded
        }

    def test_defaults_match_spec( self, stamped_identity, monkeypatch ):
        captured = { }
        monkeypatch.setattr( cv, "task_transition_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )
        cv.task_transition.fn( task_id="abc", to_status="in_progress" )
        assert captured[ "receipt_refs" ]  is None
        assert captured[ "next_chase_ts" ] is None
        assert captured[ "blocked_by" ]    is None
        assert captured[ "reason" ]        is None
        assert captured[ "authority" ]     == "standing"


class TestTaskCorrelateWrapper:

    def test_stamps_actor_and_passes_through( self, stamped_identity, monkeypatch ):
        captured = { }
        monkeypatch.setattr( cv, "task_correlate_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )

        result = cv.task_correlate.fn(
            task_id         = "abc-uuid",
            correlation_key = "cc-task:newsid:harness-7",
            authority       = "manager_relay",
        )

        assert result is SENTINEL
        assert captured == {
            "api_base_url"    : "http://stub:7999",
            "api_key"         : "ck_live_stub",
            "actor"           : "krishna 38d15e3b",
            "task_id"         : "abc-uuid",
            "correlation_key" : "cc-task:newsid:harness-7",
            "authority"       : "manager_relay",
        }

    def test_default_authority_is_standing( self, stamped_identity, monkeypatch ):
        captured = { }
        monkeypatch.setattr( cv, "task_correlate_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )
        cv.task_correlate.fn( task_id="abc", correlation_key="corr-1" )
        assert captured[ "authority" ] == "standing"


class TestTaskQueryWrapper:

    def test_no_args_board_glance( self, stamped_identity, monkeypatch ):
        captured = { }
        monkeypatch.setattr( cv, "task_query_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )

        result = cv.task_query.fn()

        assert result is SENTINEL
        assert captured == {
            "api_base_url"        : "http://stub:7999",
            "api_key"             : "ck_live_stub",
            "owner_persona"       : None,
            "status"              : None,
            "gate_class"          : None,
            "urgency"             : None,
            "accountable_manager" : None,
            "project"             : None,
            "item_class"          : None,
            "correlation_key"     : None,
            "limit"               : None,
            "offset"              : None,
            "terse"               : False,                     # §G: defaults off (full rows)
            "include_terminal"    : False,                     # guard: exclude done/dropped by default
            "unscoped_audit"      : False,                     # guard: no deliberate-audit escape by default
            "include_parked"      : False,                     # PARKED-STATUS: park-ACTIVE rows hidden by default
        }

    def test_filters_pass_through( self, stamped_identity, monkeypatch ):
        captured = { }
        monkeypatch.setattr( cv, "task_query_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )
        cv.task_query.fn( owner_persona="sam", status="queued", gate_class="operator",
                          accountable_manager="tiberius", project="lupin", item_class="gate",
                          correlation_key="todo:abc123", limit=7, offset=14 )
        assert captured[ "owner_persona" ]       == "sam"
        assert captured[ "status" ]              == "queued"
        assert captured[ "gate_class" ]          == "operator"
        assert captured[ "accountable_manager" ] == "tiberius"
        assert captured[ "project" ]             == "lupin"
        assert captured[ "item_class" ]          == "gate"
        assert captured[ "correlation_key" ]     == "todo:abc123"
        assert captured[ "limit" ]               == 7
        assert captured[ "offset" ]              == 14
        assert captured[ "terse" ]               is False     # default when unset

    def test_terse_passes_through( self, stamped_identity, monkeypatch ):
        # §G token win: the terse flag reaches the transport impl verbatim.
        captured = { }
        monkeypatch.setattr( cv, "task_query_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )
        cv.task_query.fn( owner_persona="sam", terse=True )
        assert captured[ "terse" ]         is True
        assert captured[ "owner_persona" ] == "sam"

    def test_guard_escape_params_pass_through( self, stamped_identity, monkeypatch ):
        # The unscoped-query guard escape: include_terminal + unscoped_audit reach
        # the transport impl verbatim (the deliberate-audit path).
        captured = { }
        monkeypatch.setattr( cv, "task_query_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )
        cv.task_query.fn( unscoped_audit=True, include_terminal=True )
        assert captured[ "unscoped_audit" ]   is True
        assert captured[ "include_terminal" ] is True


class TestTaskGetWrapper:
    """task_get (4288dd53) — the single-row fetch-by-id READ verb."""

    def test_task_id_and_server_context_pass_through( self, stamped_identity, monkeypatch ):
        captured = { }
        monkeypatch.setattr( cv, "task_get_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )

        result = cv.task_get.fn( task_id="4288dd53-6779-460a-88bd-a7365fb734b2" )

        assert result is SENTINEL
        assert captured == {
            "api_base_url" : "http://stub:7999",
            "api_key"      : "ck_live_stub",
            "task_id"      : "4288dd53-6779-460a-88bd-a7365fb734b2",
        }

    def test_is_a_read_verb_no_actor_stamp( self, stamped_identity, monkeypatch ):
        # READ tier, exactly like task_query: it must NOT bridge-stamp `actor`.
        # A read verb that carried an identity would imply a self-disclosure it
        # does not make — and `task_get_impl` has no `actor` param to receive one.
        captured = { }
        monkeypatch.setattr( cv, "task_get_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )
        cv.task_get.fn( task_id="abc" )
        assert "actor" not in captured


class TestTaskReassignWrapper:

    def test_stamps_actor_and_passes_through( self, stamped_identity, monkeypatch ):
        # The handoff verb bridge-stamps `actor` (never a param — anti-impersonation)
        # and threads every reassignment arg into the transport impl.
        captured = { }
        monkeypatch.setattr( cv, "task_reassign_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )

        result = cv.task_reassign.fn(
            task_id           = "abc-uuid",
            new_owner_persona = "marcus",
            reason            = "lane handoff — Tiberius now chasing",
            new_manager       = "tiberius",
            authority         = "user_direct",
        )

        assert result is SENTINEL
        assert captured == {
            "api_base_url"      : "http://stub:7999",
            "api_key"           : "ck_live_stub",
            "actor"             : "krishna 38d15e3b",
            "task_id"           : "abc-uuid",
            "new_owner_persona" : "marcus",
            "reason"            : "lane handoff — Tiberius now chasing",
            "new_manager"       : "tiberius",
            "authority"         : "user_direct",
        }

    def test_defaults_match_spec( self, stamped_identity, monkeypatch ):
        # new_manager defaults to None (leave the chasing manager unchanged, Q6);
        # authority defaults to the manager-relay handoff lane.
        captured = { }
        monkeypatch.setattr( cv, "task_reassign_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )
        cv.task_reassign.fn( task_id="abc", new_owner_persona="marcus", reason="why" )
        assert captured[ "new_manager" ] is None
        assert captured[ "authority" ]   == "manager_relay"

    def test_blank_reason_rejected_without_round_trip( self, stamped_identity, monkeypatch ):
        # A non-empty reason is verb-enforced: a blank one returns the empty_reason
        # error WITHOUT touching the transport (the impl would explode if called).
        def must_not_call( **kwargs ):
            raise AssertionError( "task_reassign_impl must not be called on a blank reason" )
        monkeypatch.setattr( cv, "task_reassign_impl", must_not_call )

        result = cv.task_reassign.fn( task_id="abc", new_owner_persona="marcus", reason="   " )
        assert result[ "status" ] == "error"
        assert result[ "reason" ] == "empty_reason"

    def test_none_reason_rejected_without_round_trip( self, stamped_identity, monkeypatch ):
        # The falsy-None branch of the guard (distinct from the whitespace branch).
        monkeypatch.setattr( cv, "task_reassign_impl",
                             lambda **kwargs: ( _ for _ in () ).throw( AssertionError( "must not call" ) ) )
        result = cv.task_reassign.fn( task_id="abc", new_owner_persona="marcus", reason=None )
        assert result[ "reason" ] == "empty_reason"


class TestTaskAmendWrapper:

    def test_stamps_actor_and_passes_through( self, stamped_identity, monkeypatch ):
        captured = { }
        monkeypatch.setattr( cv, "task_amend_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )

        result = cv.task_amend.fn(
            task_id   = "abc-uuid",
            note      = "SCOPE REFRAME: subscriber path.",
            reason    = "manager ruling",
            authority = "manager_relay",
        )

        assert result is SENTINEL
        assert captured == {
            "api_base_url" : "http://stub:7999",
            "api_key"      : "ck_live_stub",
            "actor"        : "krishna 38d15e3b",
            "task_id"      : "abc-uuid",
            "note"         : "SCOPE REFRAME: subscriber path.",
            "reason"       : "manager ruling",
            "authority"    : "manager_relay",
        }

    def test_defaults_standing_authority_and_none_reason( self, stamped_identity, monkeypatch ):
        captured = { }
        monkeypatch.setattr( cv, "task_amend_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )
        cv.task_amend.fn( task_id="abc", note="n" )
        assert captured[ "authority" ] == "standing"
        assert captured[ "reason" ]    is None


class TestTaskEditWrapper:

    def test_stamps_actor_and_passes_through( self, stamped_identity, monkeypatch ):
        captured = { }
        monkeypatch.setattr( cv, "task_edit_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )

        result = cv.task_edit.fn(
            task_id   = "abc-uuid",
            updates   = { "priority": "P3", "urgency": "low" },
            reason    = "demote over-inflated priority",
            authority = "user_direct",
        )

        assert result is SENTINEL
        assert captured == {
            "api_base_url" : "http://stub:7999",
            "api_key"      : "ck_live_stub",
            "actor"        : "krishna 38d15e3b",
            "task_id"      : "abc-uuid",
            "updates"      : { "priority": "P3", "urgency": "low" },
            "reason"       : "demote over-inflated priority",
            "authority"    : "user_direct",
        }

    def test_defaults_standing_authority_and_none_reason( self, stamped_identity, monkeypatch ):
        captured = { }
        monkeypatch.setattr( cv, "task_edit_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )
        cv.task_edit.fn( task_id="abc", updates={ "title": "t" } )
        assert captured[ "authority" ] == "standing"
        assert captured[ "reason" ]    is None

    def test_empty_updates_rejected_without_round_trip( self, stamped_identity, monkeypatch ):
        # A non-empty dict is verb-enforced: an empty dict returns the
        # empty_updates error and the transport is NEVER called.
        def must_not_call( **kwargs ):
            raise AssertionError( "task_edit_impl must not be called on empty updates" )
        monkeypatch.setattr( cv, "task_edit_impl", must_not_call )

        result = cv.task_edit.fn( task_id="abc", updates={ } )
        assert result[ "reason" ] == "empty_updates"

    def test_non_dict_updates_rejected_without_round_trip( self, stamped_identity, monkeypatch ):
        monkeypatch.setattr( cv, "task_edit_impl",
                             lambda **kwargs: ( _ for _ in () ).throw( AssertionError( "must not call" ) ) )
        result = cv.task_edit.fn( task_id="abc", updates=[ "priority", "P3" ] )
        assert result[ "reason" ] == "empty_updates"
