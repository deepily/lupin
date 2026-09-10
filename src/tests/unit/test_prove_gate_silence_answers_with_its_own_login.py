"""
Row e20e249a — the gate-silence probe answers the gate on the login it already holds.

The answer door now refuses an answer that carries no credential. `SilentConnectedUser._answer_gate`
is the probe's one call to that door, and it runs only against a live server, so no test had ever
executed it: the coverage report named that `requests.post` statement as the one changed
statement on the branch that nothing reached. These tests run it with `requests.post` replaced.

Venue: :7999-eligible — pure unit, no server, no socket, no state mutation.
"""

import importlib.util
import os


def _load_proof():
    lupin_root = os.environ[ "LUPIN_ROOT" ]
    path       = os.path.join( lupin_root, "src", "scripts",
                               "presentation-gate-silence-proof", "prove_gate_silence.py" )
    spec       = importlib.util.spec_from_file_location( "prove_gate_silence", path )
    module     = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


PG = _load_proof()


class _Posted:
    status_code = 200


def _probe():
    return PG.SilentConnectedUser( "http://probe.invalid", "silent session", "probe-login-jwt",
                                   answer_mode=True, continue_label="Approve" )


def test_the_probe_sends_the_token_it_logged_in_with( monkeypatch ):
    calls = [ ]
    monkeypatch.setattr( PG.requests, "post", lambda url, **kwargs: calls.append( ( url, kwargs ) ) or _Posted() )

    probe = _probe()
    probe._answer_gate( "n-1", [ "Continue?" ] )

    assert len( calls ) == 1
    url, kwargs = calls[ 0 ]
    assert url == "http://probe.invalid/api/notify/response"
    assert kwargs[ "headers" ] == { "Authorization": "Bearer probe-login-jwt" }
    assert kwargs[ "json" ] == { "notification_id": "n-1", "response_value": { "answers": { "Continue?": "Approve" } } }
    assert probe.answers_posted[ -1 ][ "status" ] == 200


def test_a_post_that_raises_is_recorded_rather_than_lost( monkeypatch ):
    def refuse( url, **kwargs ):
        raise ConnectionError( "door closed" )

    monkeypatch.setattr( PG.requests, "post", refuse )

    probe = _probe()
    probe._answer_gate( "n-2", [ "Continue?" ] )

    assert probe.answers_posted[ -1 ][ "notification_id" ] == "n-2"
    assert probe.answers_posted[ -1 ][ "status" ] == "ERR door closed"
