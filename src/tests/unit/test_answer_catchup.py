"""
Unit tests for the late-answer catch-up module (§4.4, answer_catchup.py).

Sibling of test_dm_inbox_reconcile.py. All :7999-eligible (no DB, no server, no
net — fetch is dependency-injected; on-disk state uses a tmp base_dir).

Covers:
  - reconcile_answers pure core: fresh surfacing oldest-first by responded_at,
    dedup by notification_id, cursor advance, NO seed suppression (ruling 3),
    blank-row recorded-not-surfaced
  - the CROSS-PROCESS ledger (C-V1 unit form): an id the listener appended to the
    shared on-disk side-log is VISIBLE to a subsequent hook reconcile and dedupes
    it — proven with the falsifying pair (without the append it WOULD surface)
  - HWM round-trip + fail-open defaults (no `seeded` key, unlike the DM sibling)
  - surface_owed_answers IO shell: not-ok fetch → "" + no HWM advance; success →
    HWM persisted + side-log compacted; persona None → ""
  - _format_answer_block envelope (rulings 6/7)
"""

import json
import pytest

import lupin_cli.claude_code.hooks.lib.answer_catchup as ac


ISO_EARLY = "2026-08-01T11:00:00+00:00"
ISO_MID   = "2026-08-01T12:00:00+00:00"
ISO_LATE  = "2026-08-01T13:00:00+00:00"


def _row( nid, responded_at=ISO_MID, question="Ship it?", answer="yes", from_earlier=False ):
    return {
        "id"                   : nid,
        "question"             : question,
        "response_value"       : { "value": answer, "source": "ui" },
        "responded_at"         : responded_at,
        "from_earlier_session" : from_earlier,
        "sender_persona"       : "tiberius",
    }


# ── pure reconcile core ───────────────────────────────────────────────────────
class TestReconcileCore:
    def test_no_seed_suppression_first_reconcile_surfaces_everything( self ):
        # Empty state (no HWM) MUST surface all owed answers — the deliberate
        # divergence from the DM sibling (ruling 3). This is the load-bearing test.
        ctx, new = ac.reconcile_answers( "sess1234", [ _row( "n1" ), _row( "n2" ) ],
                                         { "cursor_ts": None, "surfaced_ids": [] } )
        assert "Ship it?" in ctx
        assert set( new[ "surfaced_ids" ] ) == { "n1", "n2" }

    def test_dedup_by_id_against_surfaced( self ):
        ctx, _ = ac.reconcile_answers( "s", [ _row( "n1" ) ],
                                       { "cursor_ts": None, "surfaced_ids": [ "n1" ] } )
        assert ctx == ""                                   # already surfaced → nothing fresh

    def test_extra_surfaced_ids_excluded_and_recorded( self ):
        ctx, new = ac.reconcile_answers( "s", [ _row( "n1" ) ],
                                         { "cursor_ts": None, "surfaced_ids": [] },
                                         extra_surfaced_ids=[ "n1" ] )
        assert ctx == ""
        assert "n1" in new[ "surfaced_ids" ]               # recorded so it stays deduped

    def test_oldest_first_by_responded_at( self ):
        ctx, _ = ac.reconcile_answers( "s",
            [ _row( "late", responded_at=ISO_LATE, question="LATE?" ),
              _row( "early", responded_at=ISO_EARLY, question="EARLY?" ) ],
            { "cursor_ts": None, "surfaced_ids": [] } )
        assert ctx.index( "EARLY?" ) < ctx.index( "LATE?" )

    def test_cursor_advances_to_max_responded_at( self ):
        _, new = ac.reconcile_answers( "s",
            [ _row( "a", responded_at=ISO_EARLY ), _row( "b", responded_at=ISO_LATE ) ],
            { "cursor_ts": None, "surfaced_ids": [] } )
        assert new[ "cursor_ts" ] == ISO_LATE

    def test_blank_row_recorded_not_surfaced( self ):
        blank = { "id": "n1", "question": "", "response_value": None, "responded_at": ISO_MID }
        ctx, new = ac.reconcile_answers( "s", [ blank ], { "cursor_ts": None, "surfaced_ids": [] } )
        assert ctx == ""
        assert "n1" in new[ "surfaced_ids" ]               # recorded → no re-fetch loop


# ── cross-process ledger (C-V1 unit form) ─────────────────────────────────────
class TestCrossProcessLedger:
    def _fetch_one( self, row ):
        def fetch_fn( persona, session_hash8, since, limit ):
            return ( True, [ row ], False )
        return fetch_fn

    def test_cv1_listener_appended_id_visible_to_hook_reconcile( self, tmp_path ):
        # LISTENER process writes the id to the shared on-disk side-log; the HOOK
        # process (surface_owed_answers) then reconciles a fetch of the SAME id and
        # must dedupe it — proving the dedup crosses the process boundary via the
        # on-disk dir, NOT an in-process set().
        sid, nid = "sess1234", "notif-1"
        ac.append_surfaced_id( sid, nid, base_dir=tmp_path )
        ctx = ac.surface_owed_answers( sid, persona="tiberius",
                                       fetch_fn=self._fetch_one( _row( nid ) ), base_dir=tmp_path )
        assert ctx == ""                                   # deduped against the OTHER process's write

    def test_cv1_red_proof_without_listener_append_it_surfaces( self, tmp_path ):
        # The falsifier: same fetch, but NO listener append → the answer DOES surface.
        # Together with the test above this proves the side-log is what suppresses it.
        sid, nid = "sess1234", "notif-1"
        ctx = ac.surface_owed_answers( sid, persona="tiberius",
                                       fetch_fn=self._fetch_one( _row( nid ) ), base_dir=tmp_path )
        assert "Ship it?" in ctx

    def test_append_then_read_side_log_roundtrip( self, tmp_path ):
        ac.append_surfaced_id( "s1", "a", base_dir=tmp_path )
        ac.append_surfaced_id( "s1", "b", base_dir=tmp_path )
        assert ac.read_surfaced_log( "s1", base_dir=tmp_path ) == [ "a", "b" ]

    def test_append_noops_on_empty_args( self, tmp_path ):
        assert ac.append_surfaced_id( "", "x", base_dir=tmp_path ) is False
        assert ac.append_surfaced_id( "s", "", base_dir=tmp_path ) is False


# ── HWM IO ────────────────────────────────────────────────────────────────────
class TestHwmIO:
    def test_roundtrip( self, tmp_path ):
        ac.write_hwm( "s1", { "cursor_ts": ISO_MID, "surfaced_ids": [ "n1" ] }, base_dir=tmp_path )
        got = ac.read_hwm( "s1", base_dir=tmp_path )
        assert got == { "cursor_ts": ISO_MID, "surfaced_ids": [ "n1" ] }   # NO `seeded` key

    def test_missing_defaults_empty_no_seeded_key( self, tmp_path ):
        got = ac.read_hwm( "nope", base_dir=tmp_path )
        assert got == { "cursor_ts": None, "surfaced_ids": [] }
        assert "seeded" not in got

    def test_corrupt_defaults_empty( self, tmp_path ):
        p = ac._hwm_path( "bad", base_dir=tmp_path )
        p.parent.mkdir( parents=True, exist_ok=True )
        p.write_text( "{not json" )
        assert ac.read_hwm( "bad", base_dir=tmp_path ) == { "cursor_ts": None, "surfaced_ids": [] }


# ── IO shell ──────────────────────────────────────────────────────────────────
class TestSurfaceOwedAnswers:
    def test_persona_none_returns_empty( self, tmp_path ):
        # persona-less session (accepted gap) — resolve returns None, surface nothing.
        called = { "n": 0 }
        def fetch_fn( **k ):
            called[ "n" ] += 1; return ( True, [], False )
        out = ac.surface_owed_answers( "s1", persona=None,
                                       fetch_fn=fetch_fn, base_dir=tmp_path )
        # _resolve_persona reads a bridge that does not exist here → None → "".
        assert out == ""

    def test_not_ok_fetch_returns_empty_and_no_hwm_advance( self, tmp_path ):
        def fetch_fn( **k ): return ( False, [], False )
        out = ac.surface_owed_answers( "s1", persona="tiberius", fetch_fn=fetch_fn, base_dir=tmp_path )
        assert out == ""
        # HWM must NOT have been written (retry next turn).
        assert not ac._hwm_path( "s1", base_dir=tmp_path ).exists()

    def test_success_persists_hwm_and_compacts_side_log( self, tmp_path ):
        ac.append_surfaced_id( "s1", "old", base_dir=tmp_path )
        def fetch_fn( **k ): return ( True, [ _row( "n1" ) ], False )
        out = ac.surface_owed_answers( "s1", persona="tiberius", fetch_fn=fetch_fn, base_dir=tmp_path )
        assert "Ship it?" in out
        # HWM persisted with the new id...
        hwm = ac.read_hwm( "s1", base_dir=tmp_path )
        assert "n1" in hwm[ "surfaced_ids" ]
        # ...and the side-log compacted (folded under hook ownership).
        assert ac.read_surfaced_log( "s1", base_dir=tmp_path ) == []

    def test_empty_session_id_returns_empty( self, tmp_path ):
        assert ac.surface_owed_answers( "", persona="tiberius", base_dir=tmp_path ) == ""


# ── envelope formatting (rulings 6/7) ─────────────────────────────────────────
class TestFormatBlock:
    def test_carries_question_answer_responded_at( self ):
        block = ac._format_answer_block( _row( "n1", question="Deploy?", answer="yes" ) )
        assert "Deploy?" in block
        assert "yes" in block
        assert ISO_MID in block
        assert "no action required" in block               # non-interrupt framing

    def test_earlier_session_flagged( self ):
        block = ac._format_answer_block( _row( "n1", from_earlier=True ) )
        assert "earlier session of this persona" in block

    def test_same_session_not_flagged( self ):
        block = ac._format_answer_block( _row( "n1", from_earlier=False ) )
        assert "earlier session of this persona" not in block


# ── pure helpers ──────────────────────────────────────────────────────────────
class TestPureHelpers:
    """
    _max_iso and _dedup_tail are the two functions the cursor and the dedup ledger
    are built out of. Their edge branches were the only untested ones, and both
    edges are the ones that fire in production: a first-ever reconcile has a None
    cursor, and a long-lived session's ledger is always over the cap.
    """

    def test_max_iso_none_on_either_side_returns_the_other( self ):
        assert ac._max_iso( None, ISO_MID ) == ISO_MID
        assert ac._max_iso( ISO_MID, None ) == ISO_MID     # the b-is-None arm

    def test_max_iso_both_none_is_none( self ):
        assert ac._max_iso( None, None ) is None

    def test_max_iso_picks_the_later_string_lexicographically( self ):
        # Same UTC offset on every responded_at, so string order IS time order.
        assert ac._max_iso( ISO_EARLY, ISO_LATE ) == ISO_LATE
        assert ac._max_iso( ISO_LATE, ISO_EARLY ) == ISO_LATE

    def test_dedup_tail_drops_repeats_and_keeps_first_occurrence_order( self ):
        assert ac._dedup_tail( [ "a", "b", "a", "c", "b" ], 0 ) == [ "a", "b", "c" ]

    def test_dedup_tail_keeps_only_the_last_cap_entries( self ):
        # The FIFO tail is what bounds a long-lived session's ledger. Dedup runs
        # BEFORE the trim, so the cap counts distinct ids, not raw appends.
        assert ac._dedup_tail( [ "a", "b", "c", "d" ], 2 ) == [ "c", "d" ]

    def test_dedup_tail_cap_zero_means_no_cap( self ):
        assert ac._dedup_tail( [ "a", "b", "c" ], 0 ) == [ "a", "b", "c" ]


# ── envelope edges ────────────────────────────────────────────────────────────
class TestFormatBlockEdges:
    def test_plain_string_response_value_is_rendered_as_is( self ):
        """
        The dict shape {"value": ...} is what the UI sends, and every other test
        uses it. A bare string is the other live shape and must not be unwrapped
        into a stray repr.
        """
        block = ac._format_answer_block( {
            "id": "n1", "question": "Ship it?", "response_value": "yes",
            "responded_at": ISO_MID,
        } )
        assert "Answer: yes" in block

    def test_dict_response_value_without_a_value_key_falls_back_to_the_dict( self ):
        block = ac._format_answer_block( {
            "id": "n1", "question": "Ship it?", "response_value": { "other": 1 },
            "responded_at": ISO_MID,
        } )
        assert "{'other': 1}" in block

    def test_missing_fields_never_raise_and_get_a_readable_placeholder( self ):
        block = ac._format_answer_block( {} )
        assert "an earlier time" in block                  # responded_at placeholder
        assert "Question: " in block


# ── reconcile core edges ──────────────────────────────────────────────────────
class TestReconcileCoreEdges:
    def test_row_without_an_id_is_surfaced_but_not_recorded( self ):
        """
        A row with no notification_id cannot be deduped, so it is surfaced and NOT
        written to the ledger. Recording a falsy id would poison the dedup set for
        every later id-less row.
        """
        ctx, new = ac.reconcile_answers( "s", [ _row( None ) ],
                                         { "cursor_ts": None, "surfaced_ids": [] } )
        assert "Ship it?" in ctx
        assert new[ "surfaced_ids" ] == []

    def test_cursor_advances_past_a_row_that_was_already_surfaced( self ):
        """
        The cursor moves on EVERY fetched row, not only the surfaced ones —
        otherwise a re-fetch with since=cursor returns the same seen-and-skipped
        row forever.
        """
        _, new = ac.reconcile_answers( "s", [ _row( "n1", responded_at=ISO_LATE ) ],
                                       { "cursor_ts": ISO_EARLY, "surfaced_ids": [ "n1" ] } )
        assert new[ "cursor_ts" ] == ISO_LATE


# ── on-disk failure paths (fail-open, never raise) ────────────────────────────
class TestOnDiskFailurePaths:
    """
    Every writer here sits on the connect/turn hot path, so each one swallows
    OSError and reports the miss rather than raising. These pin that behavior at
    the one place it matters — a read-only or full runtime-state dir.
    """

    def test_read_hwm_rejects_valid_json_that_is_not_an_object( self, tmp_path ):
        # `[]` parses fine, so a try/except around json.load alone would let it
        # through and the caller would .get() on a list. The isinstance check is
        # the guard; this is what fires it.
        path = ac._hwm_path( "listy", base_dir=tmp_path )
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( "[]" )
        assert ac.read_hwm( "listy", base_dir=tmp_path ) == { "cursor_ts": None, "surfaced_ids": [] }

    def test_read_hwm_coerces_wrong_field_types_to_the_defaults( self, tmp_path ):
        path = ac._hwm_path( "typed", base_dir=tmp_path )
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( json.dumps( { "cursor_ts": 17, "surfaced_ids": "n1" } ) )
        assert ac.read_hwm( "typed", base_dir=tmp_path ) == { "cursor_ts": None, "surfaced_ids": [] }

    def test_write_hwm_returns_false_when_the_directory_cannot_be_made( self, tmp_path ):
        blocked = tmp_path / "afile"
        blocked.write_text( "not a directory" )
        assert ac.write_hwm( "s1", { "cursor_ts": None, "surfaced_ids": [] },
                             base_dir=blocked ) is False

    def test_append_surfaced_id_returns_false_when_the_directory_cannot_be_made( self, tmp_path ):
        blocked = tmp_path / "afile"
        blocked.write_text( "not a directory" )
        assert ac.append_surfaced_id( "s1", "n1", base_dir=blocked ) is False

    def test_read_surfaced_log_returns_empty_when_the_path_is_unreadable( self, tmp_path ):
        blocked = tmp_path / "afile"
        blocked.write_text( "not a directory" )
        assert ac.read_surfaced_log( "s1", base_dir=blocked ) == []

    def test_compact_surfaced_log_swallows_an_oserror( self, tmp_path ):
        """
        Provoked with a real on-disk condition — the log path occupied by a
        DIRECTORY, so `exists()` is True and `write_text` raises IsADirectoryError.
        Patching pathlib globally would reach every other test sharing the
        interpreter, which is a poor trade for a one-line failure path.
        """
        path = ac._surfaced_log_path( "s1", base_dir=tmp_path )
        path.mkdir( parents=True, exist_ok=True )

        ac._compact_surfaced_log( "s1", base_dir=tmp_path )     # must not raise
        # The fold already happened in the HWM, so a log that survives compaction
        # costs duplicate suppression, never correctness.
        assert path.is_dir()

    def test_compact_is_a_noop_when_there_is_no_log( self, tmp_path ):
        ac._compact_surfaced_log( "never-existed", base_dir=tmp_path )   # must not raise


# ── persona resolution (the retrieval key, ruling 6) ──────────────────────────
class TestResolvePersona:
    def test_returns_the_bridge_persona_name( self, monkeypatch ):
        import lupin_cli.claude_code.hooks.lib.session_bridge as sb
        monkeypatch.setattr( sb, "get_voice_persona", lambda h: { "name": "sam" } )
        assert ac._resolve_persona( "abcdefgh1234" ) == "sam"

    def test_returns_none_when_the_bridge_has_no_name( self, monkeypatch ):
        import lupin_cli.claude_code.hooks.lib.session_bridge as sb
        monkeypatch.setattr( sb, "get_voice_persona", lambda h: { "name": "" } )
        assert ac._resolve_persona( "abcdefgh" ) is None

    def test_returns_none_when_the_bridge_raises( self, monkeypatch ):
        """
        A persona-less session's answers are unretrievable by persona (the §4.4
        accepted gap). It must degrade to None, never propagate — this runs on the
        connect path.
        """
        import lupin_cli.claude_code.hooks.lib.session_bridge as sb
        def boom( h ):
            raise RuntimeError( "no bridge" )
        monkeypatch.setattr( sb, "get_voice_persona", boom )
        assert ac._resolve_persona( "abcdefgh" ) is None


# ── settings ──────────────────────────────────────────────────────────────────
class TestLoadSettings:
    def test_passes_through_the_loaded_settings( self, monkeypatch ):
        import lupin_cli.claude_code.hooks.lib.task_store_settings as ts
        monkeypatch.setattr( ts, "load_task_store_settings",
                             lambda: { "api_base_url": "http://x:1", "timeout_seconds": 9 } )
        assert ac._load_settings()[ "api_base_url" ] == "http://x:1"

    def test_falls_back_to_module_defaults_on_a_bad_settings_file( self, monkeypatch ):
        import lupin_cli.claude_code.hooks.lib.task_store_settings as ts
        def boom():
            raise ValueError( "malformed settings.json" )
        monkeypatch.setattr( ts, "load_task_store_settings", boom )
        got = ac._load_settings()
        assert got == { "api_base_url"    : ac.DEFAULT_API_BASE_URL,
                        "timeout_seconds" : ac.DEFAULT_TIMEOUT_SECONDS }


# ── the owed-answer fetch (X-API-Key lane, D-V1's unit half) ──────────────────
class TestFetchOwed:
    """
    The auth lane is this module's one silent-failure surface: reading the
    listener's ambient service account instead of the hook's X-API-Key returns a
    correct-looking EMPTY list. These tests pin the two properties that make that
    impossible to do by accident — the key comes from read_api_key, and the query
    carries `persona` with no user_id anywhere in it.
    """

    @staticmethod
    def _capture( monkeypatch, ok=True, body=None, status=200 ):
        from lupin_cli.claude_code.hooks.lib import task_store_client as tc
        seen = {}
        monkeypatch.setattr( tc, "read_api_key", lambda: "test-key" )
        monkeypatch.setattr( ac, "_load_settings",
                             lambda: { "api_base_url": "http://localhost:7999",
                                       "timeout_seconds": 1.5 } )
        def fake_request( method, url, api_key, timeout, body=None ):
            seen.update( method=method, url=url, api_key=api_key, timeout=timeout )
            return ok, status, fake_request.body
        fake_request.body = body
        monkeypatch.setattr( tc, "_request", fake_request )
        return seen

    def test_happy_path_returns_rows_and_a_not_full_page( self, monkeypatch ):
        seen = self._capture( monkeypatch, body={ "answers": [ _row( "n1" ) ] } )
        ok, rows, page_full = ac._fetch_owed( "sam", "abcdefgh" )
        assert ( ok, len( rows ), page_full ) == ( True, 1, False )
        assert seen[ "method" ] == "GET"
        assert seen[ "api_key" ] == "test-key"             # the hook lane, not the service account

    def test_the_query_is_persona_keyed_and_carries_no_user_id( self, monkeypatch ):
        seen = self._capture( monkeypatch, body={ "answers": [] } )
        ac._fetch_owed( "sam", "abcdefgh", since=ISO_MID )
        assert "persona=sam" in seen[ "url" ]
        assert "session_hash8=abcdefgh" in seen[ "url" ]
        assert "since=" in seen[ "url" ]
        assert "user_id" not in seen[ "url" ]               # the D-V1 property

    def test_session_hash8_and_since_are_omitted_when_absent( self, monkeypatch ):
        seen = self._capture( monkeypatch, body={ "answers": [] } )
        ac._fetch_owed( "sam", "" )
        assert "session_hash8" not in seen[ "url" ]
        assert "since" not in seen[ "url" ]

    def test_a_full_page_is_reported_so_the_caller_can_page( self, monkeypatch ):
        self._capture( monkeypatch, body={ "answers": [ _row( f"n{i}" ) for i in range( 3 ) ] } )
        ok, rows, page_full = ac._fetch_owed( "sam", "abcdefgh", limit=3 )
        assert ( ok, page_full ) == ( True, True )

    def test_transport_failure_is_not_ok_and_surfaces_nothing( self, monkeypatch ):
        self._capture( monkeypatch, ok=False, body=None, status=0 )
        assert ac._fetch_owed( "sam", "abcdefgh" ) == ( False, [], False )

    def test_a_non_dict_body_is_not_ok( self, monkeypatch ):
        # A 200 carrying a list/string must NOT read as "zero answers owed".
        self._capture( monkeypatch, body=[ "unexpected" ] )
        assert ac._fetch_owed( "sam", "abcdefgh" ) == ( False, [], False )

    def test_a_non_list_answers_field_is_not_ok( self, monkeypatch ):
        self._capture( monkeypatch, body={ "answers": "nope" } )
        assert ac._fetch_owed( "sam", "abcdefgh" ) == ( False, [], False )

    def test_a_body_without_an_answers_field_reads_as_zero_owed( self, monkeypatch ):
        # Distinct from the cases above: a well-formed body that simply owes
        # nothing IS ok, and the caller may advance its cursor.
        self._capture( monkeypatch, body={} )
        assert ac._fetch_owed( "sam", "abcdefgh" ) == ( True, [], False )


# ── IO shell: default wiring + the outer fail-open ────────────────────────────
class TestSurfaceOwedAnswersEdges:
    def test_default_fetch_fn_is_the_real_fetch( self, tmp_path, monkeypatch ):
        """
        Called with no fetch_fn, the shell must wire itself to _fetch_owed. Every
        other test injects one, so nothing else exercises the production wiring.
        """
        seen = {}
        def fake_fetch( persona, session_hash8, since, limit ):
            seen.update( persona=persona, session_hash8=session_hash8, limit=limit )
            return True, [ _row( "n1" ) ], False
        monkeypatch.setattr( ac, "_fetch_owed", fake_fetch )

        out = ac.surface_owed_answers( "s1abcdef", persona="sam", base_dir=tmp_path )
        assert "Ship it?" in out
        assert seen == { "persona": "sam", "session_hash8": "s1abcdef",
                         "limit": ac.DEFAULT_LIMIT }

    def test_an_unexpected_error_fails_open_to_empty_context( self, tmp_path, monkeypatch ):
        """
        This runs on the connect/turn hot path, so an unforeseen failure must cost
        the replay, never the turn.
        """
        def boom( *a, **k ):
            raise RuntimeError( "runtime-state dir vanished" )
        monkeypatch.setattr( ac, "read_hwm", boom )

        assert ac.surface_owed_answers( "s1", persona="sam",
                                        fetch_fn=lambda **k: ( True, [], False ),
                                        base_dir=tmp_path ) == ""

    def test_the_side_log_is_folded_into_the_dedup_on_the_shell_path( self, tmp_path ):
        # The §4.3 one-ledger property, proven through the public entrypoint:
        # an id the live listener arm wrote is not re-surfaced by catch-up.
        ac.append_surfaced_id( "s1", "n1", base_dir=tmp_path )
        out = ac.surface_owed_answers( "s1", persona="sam",
                                       fetch_fn=lambda **k: ( True, [ _row( "n1" ) ], False ),
                                       base_dir=tmp_path )
        assert out == ""


def isolated_unit_test():
    """Run this module's tests in isolation for the smoke-runner harness."""
    import time
    start = time.time()
    code = pytest.main( [ __file__, "-q", "-p", "no:cacheprovider" ] )
    return ( code == 0 ), time.time() - start, f"pytest exit {code}"


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} answer_catchup tests in {secs:.3f}s — {msg}" )
