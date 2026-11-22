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


def test_a_402_is_a_refusal_that_names_the_account_and_is_sent_once():
    calls = []
    try:
        jt.send_with_meta( b"{}", post_fn=door( [ ( 402, "x", {} ), ( 200, "ok", {} ) ], calls ), sleep_fn=lambda s: None, environ=ENV, transient=True )
    except jt.JevConfigError as e:
        out = e
    assert out.status == 402 and "Payment Required" in str( out ) and "account" in str( out )
    assert len( calls ) == 1 and [ a[ "status" ] for a in out.attempt_log ] == [ 402 ]


def test_after_a_402_the_live_transport_sends_nothing_more():
    calls = []
    transport = rt.LiveJevTransport( post_fn=door( [ ( 402, "x", {} ) ], calls ), sleep_fn=lambda s: None, environ=ENV )
    for _ in range( 3 ):
        try:
            transport.post( { "q": 1 } )
        except jt.JevConfigError as e:
            assert e.status == 402
    assert len( calls ) == 1


def test_a_lookup_that_drew_a_402_carries_a_note_naming_the_payment_and_a_clean_one_does_not( tmp_path ):
    root   = make_lupin_repo( tmp_path )
    calls  = []
    unpaid = rt.ReuseContext( root, tmp_path / "data", out_dir=tmp_path / "out",
                              transport=rt.LiveJevTransport( post_fn=door( [ ( 402, "x", {} ) ], calls ), sleep_fn=lambda s: None, environ=ENV ) )
    r = rt.check_exists_impl( NEED, unpaid, language="py" )
    assert r[ "cause" ] == "CALL_FAILED" and calls
    assert [ n[ "note" ] for n in r[ "notes" ] ] == [ rt.JEV_PAYMENT_REQUIRED ] and "402 Payment Required" in r[ "notes" ][ 0 ][ "detail" ]
    paid = rt.ReuseContext( root, tmp_path / "data2", out_dir=tmp_path / "out2",
                            transport=rt.LiveJevTransport( post_fn=door( [ ( 500, "x", {} ) ], [] ), sleep_fn=lambda s: None, environ=ENV ) )
    assert rt.JEV_PAYMENT_REQUIRED not in [ n[ "note" ] for n in rt.check_exists_impl( NEED, paid, language="py" )[ "notes" ] ]
