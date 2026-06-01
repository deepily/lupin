"""
E2E UI tests for STT transcription insert-at-cursor behavior.

Behavior change (2026-06-01, Rick): the recording button on the notifications
client used to SELECT-ALL + OVERWRITE the target field with the transcription.
The new contract is insert-at-caret: transcribed text is inserted wherever the
caret sits, replacing ONLY a highlighted range (if any), and never clobbering
the rest of the field.

These tests drive the real production method
`window.notificationsUI._insertTranscriptionText( inputElement, text )` via
`page.evaluate()` against a live `qa-input` field — no microphone, no
transcription service, no MediaRecorder plumbing required. The insertion logic
is the unit under test; the audio-capture path is unchanged.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit) — the
logged_in_page fixture registers a user, mutating persistent state.

Requires:
    - Authenticated session (logged_in_page fixture)
    - notifications page loaded with window.notificationsUI present
"""

from .conftest import BASE_URL


class TestSttInsertAtCursor:
    """Lock in the insert-at-caret contract for STT transcription."""

    def _insert( self, page, initial, sel_start, sel_end, text ):
        """
        Set `qa-input` to `initial`, place the selection at
        [sel_start, sel_end), then call the real production insertion method
        with `text`. Returns {value, caret} after insertion.
        """
        return page.evaluate(
            """( args ) => {
                const el = document.getElementById( 'qa-input' );
                el.value = args.initial;
                el.focus();
                el.setSelectionRange( args.selStart, args.selEnd );
                // Mimic the real flow: the mic button steals focus before the
                // transcription callback fires. The input's selection persists.
                el.blur();
                window.notificationsUI._insertTranscriptionText( el, args.text );
                return { value: el.value, caret: el.selectionStart };
            }""",
            { "initial": initial, "selStart": sel_start, "selEnd": sel_end, "text": text },
        )

    def test_callback_wiring_chain_resolves( self, logged_in_page ):
        """
        Guard the exact reference chain the onTranscription callback uses:
        `self.ui._insertTranscriptionText(...)`, where `self` is the
        recordingManager and `self.ui` is the NotificationsUI instance.

        Regression guard for the 2026-06-01 bug where the method was placed on
        the NotificationsUI class but called as `self._insertTranscriptionText`
        (i.e. on the recordingManager), throwing "is not a function" at runtime.
        The direct-helper tests below would NOT catch that — this one does.
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        wiring = logged_in_page.evaluate(
            """() => {
                const ui = window.notificationsUI;
                const rm = ui && ui.recordingManager;
                return {
                    uiBackref     : !!( rm && rm.ui === ui ),
                    helperIsFn    : !!( rm && rm.ui && typeof rm.ui._insertTranscriptionText === 'function' )
                };
            }"""
        )
        assert wiring[ "uiBackref" ] is True, "recordingManager.ui must be the NotificationsUI instance"
        assert wiring[ "helperIsFn" ] is True, "self.ui._insertTranscriptionText must resolve to a function"

    def test_insert_into_empty_field( self, logged_in_page ):
        """Empty field → value is exactly the transcription, caret at end."""
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        result = self._insert( logged_in_page, "", 0, 0, "hello world" )
        assert result[ "value" ] == "hello world"
        assert result[ "caret" ] == len( "hello world" )

    def test_insert_at_caret_in_middle( self, logged_in_page ):
        """Caret mid-text, no selection → text spliced in, surrounding text intact."""
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        # "Hello world" with caret after "Hello " (index 6), insert "brave ".
        result = self._insert( logged_in_page, "Hello world", 6, 6, "brave " )
        assert result[ "value" ] == "Hello brave world"
        assert result[ "caret" ] == 6 + len( "brave " )

    def test_insert_at_end( self, logged_in_page ):
        """Caret at end → text appended, nothing lost."""
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        result = self._insert( logged_in_page, "Hello", 5, 5, " there" )
        assert result[ "value" ] == "Hello there"
        assert result[ "caret" ] == len( "Hello there" )

    def test_insert_at_start( self, logged_in_page ):
        """Caret at start → text prepended, original text preserved after it."""
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        result = self._insert( logged_in_page, "world", 0, 0, "hello " )
        assert result[ "value" ] == "hello world"
        assert result[ "caret" ] == len( "hello " )

    def test_highlighted_selection_is_replaced( self, logged_in_page ):
        """A highlighted range IS replaced (the one documented overwrite case)."""
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        # "Hello world" with "world" selected (indices 6..11), insert "everyone".
        result = self._insert( logged_in_page, "Hello world", 6, 11, "everyone" )
        assert result[ "value" ] == "Hello everyone"
        assert result[ "caret" ] == 6 + len( "everyone" )

    def test_full_selection_replaced_not_appended( self, logged_in_page ):
        """Whole-field selection → behaves like the old overwrite (back-compat)."""
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        result = self._insert( logged_in_page, "throw this away", 0, 15, "keep this" )
        assert result[ "value" ] == "keep this"
        assert result[ "caret" ] == len( "keep this" )

    def test_null_caret_fallback_appends( self, logged_in_page ):
        """
        Element exposing no caret (selectionStart === null) → text is appended,
        the field is NOT clobbered, and setSelectionRange is NOT called (it
        would throw on selection-less elements). Driven with a duck-typed mock
        so the fallback branch is exercised deterministically, independent of
        any browser quirk around number/email input selection semantics.
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        result = logged_in_page.evaluate(
            """( text ) => {
                let setRangeCalled = false;
                const mock = {
                    value         : 'keep me',
                    selectionStart: null,
                    selectionEnd  : null,
                    focus         : () => {},
                    setSelectionRange: () => { setRangeCalled = true; }
                };
                window.notificationsUI._insertTranscriptionText( mock, text );
                return { value: mock.value, setRangeCalled };
            }""",
            " appended",
        )
        # Appended to the end; original preserved; no caret positioning attempted.
        assert result[ "value" ] == "keep me appended"
        assert result[ "setRangeCalled" ] is False
