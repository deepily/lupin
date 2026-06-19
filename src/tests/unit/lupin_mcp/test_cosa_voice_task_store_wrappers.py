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
            gate_class          = "ricks_court",
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
            "gate_class"          : "ricks_court",
            "priority"            : "P1",
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
            "accountable_manager" : None,
            "project"             : None,
            "item_class"          : None,
            "correlation_key"     : None,
            "limit"               : None,
            "offset"              : None,
            "terse"               : False,                     # §G: defaults off (full rows)
        }

    def test_filters_pass_through( self, stamped_identity, monkeypatch ):
        captured = { }
        monkeypatch.setattr( cv, "task_query_impl", lambda **kwargs: captured.update( kwargs ) or SENTINEL )
        cv.task_query.fn( owner_persona="sam", status="queued", gate_class="ricks_court",
                          accountable_manager="tiberius", project="lupin", item_class="gate",
                          correlation_key="todo:abc123", limit=7, offset=14 )
        assert captured[ "owner_persona" ]       == "sam"
        assert captured[ "status" ]              == "queued"
        assert captured[ "gate_class" ]          == "ricks_court"
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
