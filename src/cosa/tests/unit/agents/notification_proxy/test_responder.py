#!/usr/bin/env python3
"""
Unit tests for cosa.agents.notification_proxy.responder.NotificationResponder.

The three response strategies (ExpediterRuleStrategy, LlmScriptMatcherStrategy,
LLMFallbackStrategy), resolve_script_path, the cosa.utils.util helpers, the
script-file open(), and requests.post are ALL boundary-mocked → no LLM, no
network, no disk, zero API spend. Async handlers are driven via asyncio.run.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import requests

import cosa.agents.notification_proxy.responder as rr
from cosa.agents.notification_proxy.responder import NotificationResponder
from cosa.agents.notification_proxy.config import DEFAULT_ACCEPTED_SENDERS

EXPEDITER = DEFAULT_ACCEPTED_SENDERS[ 0 ]


def _make_responder(
    strategy           = "auto",
    debug              = False,
    verbose            = False,
    dry_run            = False,
    script_init_raises = False,
    script_load_raises = False,
    sender_ids         = None,
):
    """Construct a NotificationResponder with all collaborators mocked."""
    rule_mock   = MagicMock()
    script_mock = MagicMock()
    llm_mock    = MagicMock()
    llm_mock.respond = AsyncMock( return_value=None )

    cu_mock = MagicMock()
    cu_mock.get_project_root.return_value = "/root"

    open_mock = mock_open( read_data=json.dumps( { "sender_ids": sender_ids or [ EXPEDITER ] } ) )
    if script_load_raises:
        open_mock.side_effect = OSError( "no script" )

    if script_init_raises:
        script_cls = MagicMock( side_effect=RuntimeError( "script init boom" ) )
    else:
        script_cls = MagicMock( return_value=script_mock )

    with patch.object( rr, "resolve_script_path", return_value="/s.json" ), \
         patch.object( rr, "cu", cu_mock ), \
         patch( "builtins.open", open_mock ), \
         patch.object( rr, "ExpediterRuleStrategy", return_value=rule_mock ), \
         patch.object( rr, "LlmScriptMatcherStrategy", script_cls ), \
         patch.object( rr, "LLMFallbackStrategy", return_value=llm_mock ):
        r = NotificationResponder(
            profile_name = "deep_research",
            strategy     = strategy,
            dry_run      = dry_run,
            debug        = debug,
            verbose      = verbose,
        )
    return r, rule_mock, script_mock, llm_mock


def _notif( **over ):
    base = {
        "id_hash"            : "n-123",
        "response_requested" : True,
        "response_type"      : "open_ended",
        "message"            : "what topic?",
        "title"              : "Missing: query",
        "sender_id"          : EXPEDITER,
    }
    base.update( over )
    return base


class TestInit:

    def test_auto_creates_all_strategies( self ):
        r, rule, script, llm = _make_responder( strategy="auto", debug=True )
        assert r.rule_strategy   is rule
        assert r.script_strategy is script
        assert r.llm_strategy    is llm
        assert r.stats[ "notifications_received" ] == 0

    def test_rules_mode_skips_script_strategy( self ):
        r, _, _, _ = _make_responder( strategy="rules" )
        assert r.script_strategy is None

    def test_script_load_failure_falls_back_to_default_senders( self ):
        r, _, _, _ = _make_responder( script_load_raises=True, debug=True )
        # constructed without raising — accepted_senders defaulted internally
        assert r.rule_strategy is not None

    def test_script_strategy_init_failure_sets_none( self ):
        r, _, _, _ = _make_responder( strategy="llm_script", script_init_raises=True )
        assert r.script_strategy is None


class TestHandleEvent:

    def test_dispatches_notification_update( self ):
        r, rule, script, llm = _make_responder()
        script.can_handle.return_value = False
        rule.can_handle.return_value   = False
        llm.can_handle.return_value    = False
        asyncio.run( r.handle_event( "notification_queue_update", _notif() ) )
        assert r.stats[ "notifications_received" ] == 1

    def test_job_state_transition_verbose( self, capsys ):
        # Two defects in the four lines this replaces. It asserted NOTHING — it
        # called the handler and stopped, so it could not fail. And it fed
        # from_queue/to_queue, keys emit_job_state_transition() has never sent,
        # so it described a payload that does not exist. Row e3417974.
        r, _, _, _ = _make_responder( verbose=True )
        asyncio.run( r.handle_event( "job_state_transition",
                                     { "job_id": "j", "from_state": "queued", "to_state": "running" } ) )
        assert "Job state: j queued → running" in capsys.readouterr().out

    def test_job_state_transition_does_not_read_retired_keys( self, capsys ):
        """A payload carrying ONLY the retired keys must not render as if it worked."""
        r, _, _, _ = _make_responder( verbose=True )
        asyncio.run( r.handle_event( "job_state_transition",
                                     { "job_id": "j", "from_queue": "todo", "to_queue": "run" } ) )
        out = capsys.readouterr().out
        assert "todo → run" not in out
        assert "Job state: j ? → ?" in out

    def test_other_event_verbose( self ):
        r, _, _, _ = _make_responder( verbose=True )
        asyncio.run( r.handle_event( "sys_ping", {} ) )

    def test_other_event_non_verbose_noop( self ):
        r, _, _, _ = _make_responder( verbose=False )
        asyncio.run( r.handle_event( "sys_ping", {} ) )

    def test_job_state_transition_non_verbose( self ):
        """job_state_transition with verbose=False → inner if-False → exits quietly."""
        r, _, _, _ = _make_responder( verbose=False )
        asyncio.run( r.handle_event( "job_state_transition", { "job_id": "j" } ) )


class TestHandleNotificationUpdate:

    def _run( self, r, event ):
        asyncio.run( r._handle_notification_update( event ) )

    def test_skips_when_no_response_requested( self ):
        r, _, _, _ = _make_responder( verbose=True )
        self._run( r, _notif( response_requested=False ) )
        assert r.stats[ "skipped" ] == 1

    def test_error_when_no_notification_id( self ):
        r, rule, script, llm = _make_responder()
        self._run( r, _notif( id_hash=None, notification_id=None, id=None ) )
        assert r.stats[ "errors" ] == 1

    def test_nested_notification_payload_and_tier3_display( self ):
        r, rule, script, llm = _make_responder( debug=True, verbose=True )
        script.can_handle.return_value = False
        rule.can_handle.return_value   = True
        rule.respond.return_value      = "academic"
        with patch.object( rr.requests, "post", return_value=MagicMock( status_code=200, json=lambda: { "status": "ok", "message": "done" } ) ):
            self._run( r, { "notification": _notif( abstract="ctx" ) } )
        assert r.stats[ "responses_sent" ] == 1
        assert r.stats[ "rules_used" ] == 1

    def test_tier2_display_debug_only( self ):
        r, rule, script, llm = _make_responder( debug=True, verbose=False )
        script.can_handle.return_value = False
        rule.can_handle.return_value   = True
        rule.respond.return_value      = "academic"
        with patch.object( rr.requests, "post", return_value=MagicMock( status_code=200, json=lambda: {} ) ):
            self._run( r, _notif() )
        assert r.stats[ "rules_used" ] == 1

    def test_dry_run_yes_no_sends_no( self ):
        r, _, _, _ = _make_responder( dry_run=True, verbose=True )
        captured = {}
        def fake_post( url, **kw ):
            captured[ "value" ] = kw[ "json" ][ "response_value" ]
            return MagicMock( status_code=200, json=lambda: {} )
        with patch.object( rr.requests, "post", side_effect=fake_post ):
            self._run( r, _notif( response_type="yes_no" ) )
        assert captured[ "value" ] == "no"
        assert r.stats[ "skipped" ] == 1

    def test_dry_run_other_sends_cancel_non_verbose( self ):
        r, _, _, _ = _make_responder( dry_run=True, verbose=False )
        captured = {}
        def fake_post( url, **kw ):
            captured[ "value" ] = kw[ "json" ][ "response_value" ]
            return MagicMock( status_code=200, json=lambda: {} )
        with patch.object( rr.requests, "post", side_effect=fake_post ):
            self._run( r, _notif( response_type="open_ended" ) )
        assert captured[ "value" ] == "cancel"

    def test_script_matcher_wins( self ):
        r, rule, script, llm = _make_responder( debug=True )
        script.can_handle.return_value = True
        script.respond.return_value    = "from-script"
        with patch.object( rr.requests, "post", return_value=MagicMock( status_code=200, json=lambda: {} ) ):
            self._run( r, _notif() )
        assert r.stats[ "script_matcher_used" ] == 1

    def test_script_can_handle_but_returns_none_falls_through_to_rules( self ):
        r, rule, script, llm = _make_responder()
        script.can_handle.return_value = True
        script.respond.return_value    = None
        rule.can_handle.return_value   = True
        rule.respond.return_value      = "from-rules"
        with patch.object( rr.requests, "post", return_value=MagicMock( status_code=200, json=lambda: {} ) ):
            self._run( r, _notif() )
        assert r.stats[ "rules_used" ] == 1

    def test_llm_fallback_wins_with_dict_answer( self ):
        r, rule, script, llm = _make_responder( debug=True, verbose=True )
        script.can_handle.return_value = False
        rule.can_handle.return_value   = False
        llm.can_handle.return_value    = True
        llm.respond = AsyncMock( return_value={ "answers": { "a": "b" } } )   # dict → json.dumps display path
        with patch.object( rr.requests, "post", return_value=MagicMock( status_code=200, json=lambda: {} ) ):
            self._run( r, _notif() )
        assert r.stats[ "llm_used" ] == 1

    def test_no_strategy_answers_skips( self ):
        r, rule, script, llm = _make_responder()
        script.can_handle.return_value = False
        rule.can_handle.return_value   = False
        llm.can_handle.return_value    = False
        self._run( r, _notif() )
        assert r.stats[ "skipped" ] == 1

    def test_rule_can_handle_but_returns_none( self ):
        """rule.can_handle True but respond None → answer stays None (272->276 arc)."""
        r, rule, script, llm = _make_responder()
        script.can_handle.return_value = False
        rule.can_handle.return_value   = True
        rule.respond.return_value      = None
        llm.can_handle.return_value    = False
        self._run( r, _notif() )
        assert r.stats[ "skipped" ] == 1

    def test_llm_can_handle_but_returns_none( self ):
        """llm.can_handle True but respond None → answer stays None (278->281 arc)."""
        r, rule, script, llm = _make_responder()
        script.can_handle.return_value = False
        rule.can_handle.return_value   = False
        llm.can_handle.return_value    = True
        llm.respond = AsyncMock( return_value=None )
        self._run( r, _notif() )
        assert r.stats[ "skipped" ] == 1

    def test_submit_failure_counts_error( self ):
        r, rule, script, llm = _make_responder()
        script.can_handle.return_value = False
        rule.can_handle.return_value   = True
        rule.respond.return_value      = "academic"
        with patch.object( rr.requests, "post", return_value=MagicMock( status_code=500, text="err" ) ):
            self._run( r, _notif() )
        assert r.stats[ "errors" ] == 1


class TestSubmitResponse:

    def test_success_verbose( self ):
        r, _, _, _ = _make_responder( verbose=True )
        with patch.object( rr.requests, "post", return_value=MagicMock( status_code=200, json=lambda: { "status": "ok", "message": "m" } ) ):
            assert r._submit_response( "n1", "yes" ) is True

    def test_success_non_verbose( self ):
        r, _, _, _ = _make_responder( verbose=False )
        with patch.object( rr.requests, "post", return_value=MagicMock( status_code=200 ) ):
            assert r._submit_response( "n1", "yes" ) is True

    def test_non_200_returns_false( self ):
        r, _, _, _ = _make_responder()
        with patch.object( rr.requests, "post", return_value=MagicMock( status_code=403, text="nope" ) ):
            assert r._submit_response( "n1", "yes" ) is False

    def test_connection_error_returns_false( self ):
        r, _, _, _ = _make_responder()
        with patch.object( rr.requests, "post", side_effect=requests.ConnectionError() ):
            assert r._submit_response( "n1", "yes" ) is False

    def test_timeout_returns_false( self ):
        r, _, _, _ = _make_responder()
        with patch.object( rr.requests, "post", side_effect=requests.Timeout() ):
            assert r._submit_response( "n1", "yes" ) is False

    def test_generic_exception_returns_false( self ):
        r, _, _, _ = _make_responder()
        with patch.object( rr.requests, "post", side_effect=ValueError( "weird" ) ):
            assert r._submit_response( "n1", "yes" ) is False


class TestPrintStats:

    def test_print_stats_runs( self ):
        r, _, _, _ = _make_responder()
        r.print_stats()   # smoke — exercises the stats-formatting loop


class TestHumanOnlyExemption:
    """
    A notification flagged human_only must NEVER be auto-answered by the proxy —
    not in dry_run (which blanket-declines yes_no), not via any strategy. This is
    the honor-side of the self-re-spin fix (row 804afce6): a proxy 'no' to the
    self-re-spin ask would abort a manager's own re-spin, the exact
    "an absent user must not cost a manager" failure.

    Written to FAIL on current code (no human_only check anywhere) before the fix.
    """

    def _run( self, r, event ):
        asyncio.run( r._handle_notification_update( event ) )

    def test_human_only_not_answered_in_dry_run( self ):
        r, _, _, _ = _make_responder( dry_run=True, verbose=True )
        posted = { "called": False }
        def fake_post( url, **kw ):
            posted[ "called" ] = True
            return MagicMock( status_code=200, json=lambda: {} )
        with patch.object( rr.requests, "post", side_effect=fake_post ):
            self._run( r, _notif( response_type="yes_no", human_only=True ) )
        assert posted[ "called" ] is False, "proxy answered a human_only ask in dry_run — it must not"
        assert r.stats[ "skipped" ] == 1

    def test_human_only_skipped_silently_when_not_verbose( self, capsys ):
        """
        The skip must hold with verbose off — the guard is the behaviour, the
        log line is not. Every human_only test above ran verbose=True, so the
        quiet arm of that `if self.verbose` was never taken (coverage 296->298).
        """
        r, _, _, _ = _make_responder( dry_run=True, verbose=False )
        posted = { "called": False }
        def fake_post( url, **kw ):
            posted[ "called" ] = True
            return MagicMock( status_code=200, json=lambda: {} )
        with patch.object( rr.requests, "post", side_effect=fake_post ):
            self._run( r, _notif( response_type="yes_no", human_only=True ) )
        assert posted[ "called" ] is False, "proxy answered a human_only ask — it must not"
        assert r.stats[ "skipped" ] == 1
        assert "Skipped (human_only" not in capsys.readouterr().out

    def test_human_only_not_answered_by_strategy( self ):
        r, rule, script, llm = _make_responder( verbose=True )
        script.can_handle.return_value = False
        rule.can_handle.return_value   = True
        rule.respond.return_value      = "no"          # a strategy that WOULD veto
        posted = { "called": False }
        def fake_post( url, **kw ):
            posted[ "called" ] = True
            return MagicMock( status_code=200, json=lambda: {} )
        with patch.object( rr.requests, "post", side_effect=fake_post ):
            self._run( r, _notif( response_type="yes_no", human_only=True ) )
        assert posted[ "called" ] is False, "a strategy answered a human_only ask — it must be skipped first"
        assert r.stats[ "skipped" ] == 1


class TestPositionalSentinelResolution:
    """
    A scripted answer of __first_option__ becomes a REAL option label before it is
    submitted (row 9046ef58).

    THE FAILURE THIS REPLACES. The document choice card's labels are filenames
    discovered while a run is in flight, so the entry first carried a prose directive
    and trusted the matcher to turn it into a label. On a live presentation job the
    matcher returned the prose verbatim; the expeditor saw a label the card had never
    offered, correctly refused to guess which document was meant, and the run
    cancelled — the exact failure the entry existed to prevent.
    """

    DESCRIBE = "Let me describe it instead"
    CANCEL   = "Cancel"

    def _run( self, r, event ):
        asyncio.run( r._handle_notification_update( event ) )

    def _card_event( self, *labels ):
        return {
            "id"                 : "n1",
            "sender_id"          : EXPEDITER,
            "response_requested" : True,
            "response_type"      : "multiple_choice",
            "title"              : "Missing: source",
            "message"            : "Which document should I use for the presentation?",
            "response_options"   : { "questions": [ { "options": [
                { "label": l, "description": "" } for l in labels
            ] } ] },
        }

    def test_the_sentinel_is_replaced_by_the_first_real_candidate( self ):
        r, _, script, _ = _make_responder( debug=True )
        script.can_handle.return_value = True
        script.respond.return_value    = "__first_option__"
        with patch.object( r, "_submit_response", return_value=True ) as submit:
            self._run( r, self._card_event( "kiss.md", "quantum.md", self.DESCRIBE, self.CANCEL ) )
        submit.assert_called_once_with( "n1", "kiss.md" )
        assert r.stats[ "responses_sent" ] == 1

    def test_the_escapes_are_never_chosen( self ):
        # Selecting Cancel would read to the expeditor as the user declining — a run
        # that looks answered and did nothing.
        r, _, script, _ = _make_responder()
        script.can_handle.return_value = True
        script.respond.return_value    = "__first_option__"
        with patch.object( r, "_submit_response", return_value=True ) as submit:
            self._run( r, self._card_event( self.DESCRIBE, self.CANCEL ) )
        submit.assert_not_called()
        assert r.stats[ "skipped" ] == 1

    def test_an_unresolvable_sentinel_is_a_visible_skip_not_a_submitted_string( self ):
        # Submitting "__first_option__" would cancel the run for a reason nobody can
        # see from the outside. The counted skip is the whole point.
        r, _, script, _ = _make_responder()
        script.can_handle.return_value = True
        script.respond.return_value    = "__first_option__"
        with patch.object( r, "_submit_response", return_value=True ) as submit:
            self._run( r, self._card_event() )
        submit.assert_not_called()
        assert r.stats[ "skipped" ] == 1
        assert r.stats[ "responses_sent" ] == 0

    def test_a_typod_sentinel_is_a_loud_skip_not_a_dead_proxy( self ):
        # The resolver REFUSES to forward a typo as a literal (it raises). The proxy
        # must not die of it either: one bad entry in a script file would otherwise
        # take down a run that had nothing to do with it. Counted skip, reason on
        # stdout, run continues.
        r, _, script, _ = _make_responder()
        script.can_handle.return_value = True
        script.respond.return_value    = "__frist_option__"
        with patch.object( r, "_submit_response", return_value=True ) as submit:
            self._run( r, self._card_event( "kiss.md", "quantum.md" ) )
        submit.assert_not_called()
        assert r.stats[ "skipped" ] == 1
        assert r.stats[ "responses_sent" ] == 0

    def _multi_card_event( self, *labels ):
        return {
            "id"                 : "n1",
            "sender_id"          : EXPEDITER,
            "response_requested" : True,
            "response_type"      : "multiple_choice",
            "title"              : "TFE Proposal",
            "message"            : "Select fixes to apply (2 proposals):",
            "response_options"   : { "questions": [ {
                "question"     : "Select fixes to apply (2 proposals):",
                "header"       : "Fixes",
                "multi_select" : True,
                "options"      : [ { "label": l, "description": "" } for l in labels ],
            } ] },
        }

    def test_all_submits_every_label_in_the_shape_the_reader_expects( self ):
        # Row 054207ce. tfe.json has answered its proposal gate with "__all__" since it
        # was written and the token was never implemented, so the resolver raised and
        # the gate was never auto-answered. What is submitted is the format the HUMAN
        # path produces — a bare label string would be wrapped under the header
        # "response", the card's real header would read as absent, and TFE would report
        # that the user selected no fixes.
        r, _, script, _ = _make_responder()
        script.can_handle.return_value = True
        script.respond.return_value    = "__all__"
        with patch.object( r, "_submit_response", return_value=True ) as submit:
            self._run( r, self._multi_card_event( "c1: widen the timeout", "c2: fix the import" ) )
        submit.assert_called_once()
        notification_id, answer = submit.call_args[ 0 ]
        assert notification_id == "n1"
        assert json.loads( answer ) == {
            "answers": { "Fixes": [ "c1: widen the timeout", "c2: fix the import" ] } }
        assert r.stats[ "responses_sent" ] == 1

    def test_all_on_a_card_offering_only_escapes_is_a_visible_skip( self ):
        # An empty selection is read upstream as a no-response TIMEOUT, so submitting
        # one would misreport a gate that had nothing to offer.
        r, _, script, _ = _make_responder()
        script.can_handle.return_value = True
        script.respond.return_value    = "__all__"
        with patch.object( r, "_submit_response", return_value=True ) as submit:
            self._run( r, self._multi_card_event( self.DESCRIBE, self.CANCEL ) )
        submit.assert_not_called()
        assert r.stats[ "skipped" ] == 1

    def test_the_multi_select_answer_is_not_rejected_by_the_option_check( self ):
        # The two features have to coexist: the strategy-agnostic validator (row
        # a1420538) skips multi-select cards on purpose, and this is what proves the
        # JSON envelope survives it rather than being refused as "a label the card
        # never offered".
        r, _, script, _ = _make_responder()
        script.can_handle.return_value = True
        script.respond.return_value    = "__all__"
        with patch.object( r, "_submit_response", return_value=True ) as submit:
            self._run( r, self._multi_card_event( "c1: only fix" ) )
        submit.assert_called_once()
        assert r.stats[ "skipped" ] == 0

    def test_a_multi_select_answer_with_one_bogus_label_is_a_counted_skip( self ):
        # MARÍA'S FALSIFIER, and she named why it has to be this one: __all__ emits the
        # card's own labels and is correct by construction, so a test that only checks
        # __all__ still passes cannot fail and is not a guard. The guard is worth having
        # for every OTHER producer of a multi-select answer — a hand-written script
        # entry, the rule strategy, the cloud LLM — because an unoffered label reaches
        # the agent as a pick it never offered.
        # RED ON REVERT (the multi-select carve-out restored): submit is called with
        # the payload and assert_not_called fails.
        r, _, script, _ = _make_responder()
        script.can_handle.return_value = True
        script.respond.return_value    = json.dumps(
            { "answers": { "Fixes": [ "c1: widen the timeout", "NOT OFFERED" ] } } )
        with patch.object( r, "_submit_response", return_value=True ) as submit:
            self._run( r, self._multi_card_event( "c1: widen the timeout", "c2: fix the import" ) )
        submit.assert_not_called()
        assert r.stats[ "skipped" ] == 1
        assert r.stats[ "responses_sent" ] == 0

    def test_a_multi_select_answer_whose_picks_were_all_offered_still_submits( self ):
        # The other half of the falsifier: the guard must not simply reject everything
        # multi-select, which would trade a silent bad submit for a silent skip.
        r, _, script, _ = _make_responder()
        script.can_handle.return_value = True
        script.respond.return_value    = json.dumps(
            { "answers": { "Fixes": [ "c1: widen the timeout" ] } } )
        with patch.object( r, "_submit_response", return_value=True ) as submit:
            self._run( r, self._multi_card_event( "c1: widen the timeout", "c2: fix the import" ) )
        submit.assert_called_once()
        assert r.stats[ "responses_sent" ] == 1

    def test_an_answer_under_a_header_the_card_never_asked_is_a_counted_skip( self ):
        # The label is one the card really did offer, so the label check passes it.
        # Submitting it means the agent looks under its own header, finds nothing, and
        # reports that the user selected no fixes.
        # RED ON REVERT (the header check removed): submit is called with the payload.
        r, _, script, _ = _make_responder()
        script.can_handle.return_value = True
        script.respond.return_value    = json.dumps(
            { "answers": { "Wrong": [ "c1: widen the timeout" ] } } )
        with patch.object( r, "_submit_response", return_value=True ) as submit:
            self._run( r, self._multi_card_event( "c1: widen the timeout", "c2: fix the import" ) )
        submit.assert_not_called()
        assert r.stats[ "skipped" ] == 1

    def test_the_header_rejection_names_the_strategy_and_the_header( self, capsys ):
        r, _, script, _ = _make_responder()
        script.can_handle.return_value = True
        script.respond.return_value    = json.dumps( { "answers": { "Wrong": [ "c1: widen the timeout" ] } } )
        with patch.object( r, "_submit_response", return_value=True ):
            self._run( r, self._multi_card_event( "c1: widen the timeout" ) )
        printed = capsys.readouterr().out
        assert "never asked" in printed
        assert "script_matcher" in printed
        assert "Wrong" in printed

    def test_an_ordinary_answer_is_untouched( self ):
        # The resolver sits in the hot path for EVERY answer; this is the guard that
        # it changes nothing for the other several hundred script entries.
        #
        # The card now offers "general" as well. It used to offer only "kiss.md",
        # which passed because nothing downstream checked — an answer the card had
        # never offered went straight to the expeditor, which is the defect row
        # a1420538 closes. Pass-through is still what is being tested; the fixture
        # now describes a card the answer legitimately belongs to.
        r, _, script, _ = _make_responder()
        script.can_handle.return_value = True
        script.respond.return_value    = "general"
        with patch.object( r, "_submit_response", return_value=True ) as submit:
            self._run( r, self._card_event( "kiss.md", "general" ) )
        submit.assert_called_once_with( "n1", "general" )

    def test_an_answer_the_card_never_offered_is_a_visible_skip( self ):
        # Row a1420538. The sentinel block above only inspects sentinel-SHAPED
        # values, so an ordinary-looking answer from any strategy reached the card
        # unchecked. The expeditor rejects a label it never offered and the run
        # cancels, which from the outside is indistinguishable from a user declining.
        # RED ON REVERT (validation removed): submit is called with the prose and
        # "Expected 'assert_not_called' to not have been called" fails.
        r, _, script, _ = _make_responder()
        script.can_handle.return_value = True
        script.respond.return_value    = "made-up.md"
        with patch.object( r, "_submit_response", return_value=True ) as submit:
            self._run( r, self._card_event( "kiss.md", "quantum.md" ) )
        submit.assert_not_called()
        assert r.stats[ "skipped" ] == 1
        assert r.stats[ "responses_sent" ] == 0

    def test_the_retired_prose_at_confidence_equal_to_the_floor_is_not_submitted( self ):
        # THE ROW'S OWN CASE, at the boundary María named. On the live run the hint
        # carried the retired directive at confidence 0.9 against an auto-submit floor
        # of 0.9. The floor is INCLUSIVE — the client's reject test is
        # `confidence < floor`, pinned by "gate OPENS at exactly the floor (>= is
        # inclusive)" in src/tests/unit/notifications_js/batch_prediction_prefill.test.ts
        # — so equal ADMITS, and a test at 0.95 would prove nothing about it.
        #
        # The assertion is not that the gate admits equal (it does, and that is the
        # premise). It is that when the prose gets through at exactly-equal
        # confidence, the answer submitted is a real label or a visible skip, and
        # never the prose.
        prose = ( "Pick the first document option in the list - never "
                  "'Let me describe it' and never 'Cancel'." )
        hint  = {
            "auto_submit_enabled"                  : True,
            "auto_submit_min_confidence_threshold" : 0.9,
            "confidence"                           : 0.9,
            "predicted_value"                      : { "answers": { "_other": prose } },
        }
        # The premise, stated so the test cannot quietly become vacuous: equal is
        # at-or-above, so this hint IS eligible to reach the card.
        assert hint[ "confidence" ] >= hint[ "auto_submit_min_confidence_threshold" ]

        event = self._card_event( "kiss.md", "quantum.md", self.DESCRIBE, self.CANCEL )
        event[ "prediction_hint" ] = hint

        r, _, script, _ = _make_responder()
        script.can_handle.return_value = True
        script.respond.return_value    = prose
        with patch.object( r, "_submit_response", return_value=True ) as submit:
            self._run( r, event )
        submit.assert_not_called()
        assert r.stats[ "skipped" ] == 1
        assert r.stats[ "responses_sent" ] == 0

    def test_a_non_choice_card_is_not_option_checked( self ):
        # The check is scoped to multiple_choice. An open-ended ask has no options to
        # validate against, and validating one would reject every free-text answer.
        r, _, script, _ = _make_responder()
        script.can_handle.return_value = True
        script.respond.return_value    = "/tmp/mock-research-document.md"
        with patch.object( r, "_submit_response", return_value=True ) as submit:
            self._run( r, _notif( response_type="open_ended" ) )
        submit.assert_called_once_with( "n-123", "/tmp/mock-research-document.md" )

    def test_the_rejection_names_the_strategy_and_the_value( self, capsys ):
        # The printed line has to BE the fix: which path produced the answer, and what
        # it actually said. Without both, the reader sees a skip and has to reconstruct
        # the cause from a run that already ended.
        r, _, script, _ = _make_responder()
        script.can_handle.return_value = True
        script.respond.return_value    = "made-up.md"
        with patch.object( r, "_submit_response", return_value=True ):
            self._run( r, self._card_event( "kiss.md" ) )
        printed = capsys.readouterr().out
        # "never offered" is asserted because the SUCCESS line also carries the
        # strategy name and the answer — without it this test stays green with the
        # check removed, which is the one thing it must not do.
        assert "never offered"  in printed
        assert "script_matcher" in printed
        assert "made-up.md"     in printed
