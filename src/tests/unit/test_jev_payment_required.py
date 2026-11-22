"""
Jev answering 402 Payment Required is an unpaid account, and the reuse tools say so.

From the evening of 21 Nov 2026 every Jev request answered 402. The transport read it as an ordinary
failed call. Each lookup reported CALL_FAILED with nothing naming the account, and every post kept
going to the network. Venue: :7999 (unit). No network: every door here is a stub.
"""
from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_tools as rt
from tests.unit.symindex_helpers import make_lupin_repo
from tests.unit.test_reuse_tools import NEED

ENV = { jt.KEY_VARIABLE: "k" }


def door( replies, calls ):
    """Ensures: returns a post function that records each call and answers the next reply."""
    def post( url, headers, body, timeout ):
        """Ensures: records the call and returns the next ( status, text, headers ) reply."""
        calls.append( body )
        return replies[ min( len( calls ), len( replies ) ) - 1 ]
    return post


def live( status, calls ):
    """Ensures: returns a live transport whose every HTTP reply is the given status."""
    return rt.LiveJevTransport( post_fn=door( [ ( status, "x", {} ) ], calls ), sleep_fn=lambda s: None, environ=ENV )


def notes_of( r ):
    """Ensures: returns the note names of one public result."""
    return [ n[ "note" ] for n in r[ "notes" ] ]


def test_a_402_is_a_refusal_that_names_the_account_and_is_sent_once():
    calls = []
    try:
        jt.send_with_meta( b"{}", post_fn=door( [ ( 402, "x", {} ), ( 200, "ok", {} ) ], calls ), sleep_fn=lambda s: None, environ=ENV, transient=True )
    except jt.JevConfigError as e:
        out = e
    assert out.status == 402 and "Payment Required" in str( out ) and "account" in str( out )
    assert len( calls ) == 1 and [ a[ "status" ] for a in out.attempt_log ] == [ 402 ]


def test_after_a_402_the_live_transport_sends_nothing_more_and_a_repeat_carries_no_attempt():
    calls, seen = [], []
    transport = live( 402, calls )
    for _ in range( 3 ):
        try:
            transport.post( { "q": 1 } )
        except jt.JevConfigError as e:
            seen.append( ( e.status, len( e.attempt_log ) ) )
    assert len( calls ) == 1 and seen == [ ( 402, 1 ), ( 402, 0 ), ( 402, 0 ) ]


def test_one_402_is_one_request_in_the_receipt_and_the_call_names_the_payment( tmp_path ):
    root, calls = make_lupin_repo( tmp_path ), []
    r = rt.check_exists_impl( NEED, rt.ReuseContext( root, tmp_path / "data", out_dir=tmp_path / "out", transport=live( 402, calls ) ), language="py" )
    assert r[ "cause" ] == "CALL_FAILED" and len( calls ) == 1
    assert r[ "stats" ][ "attempt_counts" ][ "requests" ] == 1 and r[ "stats" ][ "attempt_counts" ][ "attempts" ] == 1
    assert notes_of( r ) == [ rt.JEV_PAYMENT_REQUIRED ]


def test_the_note_belongs_to_the_call_so_a_reused_receipt_says_what_this_call_saw( tmp_path ):
    root = make_lupin_repo( tmp_path )
    ctx  = lambda status: rt.ReuseContext( root, tmp_path / "data", out_dir=tmp_path / "out", transport=live( status, [] ) )
    first  = rt.check_exists_impl( NEED, ctx( 402 ), language="py" )
    second = rt.check_exists_impl( NEED, ctx( 500 ), language="py" )
    third  = rt.check_exists_impl( NEED, ctx( 402 ), language="py" )
    assert first[ "receipt_id" ] == second[ "receipt_id" ] == third[ "receipt_id" ]        # the control: one stored receipt serves all three
    assert notes_of( first ) == [ rt.JEV_PAYMENT_REQUIRED ] and notes_of( second ) == [] and notes_of( third ) == [ rt.JEV_PAYMENT_REQUIRED ]
    assert "notes" not in rt.load_receipt( ctx( 500 ), first[ "receipt_id" ] )
