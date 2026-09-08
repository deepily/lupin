"""The v2 submit door refuses a bad `source_document` BEFORE it builds anything.

RICK'S RULING, 2026-09-08, Q4 of row 14c54c10: an unresolvable, out-of-scope or missing
source document is refused AT THE DOOR, before the job is created — not inside the agent
after it starts. The unit tests beside this one prove the RULE (does this path resolve,
is it in scope, does the symlink escape). These prove the DOOR ACTUALLY ASKS — which is a
different claim, and the one that fails silently if the call site is dropped in a refactor.

⚠️ EVERY TEST HERE ASSERTS THE FACTORY WAS NEVER CALLED. Asserting only on the returned
status would pass against a door that builds the job, queues it, and THEN reports a
refusal — which is exactly the behaviour Rick ruled against. "Nothing was built" is the
claim, so "nothing was built" is what gets asserted.

⚠️ Run scoped — `pytest src/tests/unit/...` — an unscoped run collects `src/tmp/`, which
exits at import time.
"""

import os
import sys

import pytest

sys.path.insert( 0, os.path.dirname( __file__ ) )
import test_v2_flow as v2                       # noqa: E402
from test_v2_flow import notifier               # noqa: F401,E402 — a fixture, used by name

from cosa.rest.v2.source_document import SOURCE_DOCUMENT_ARG


_CTX = v2._CTX

_COMMAND = "agent router go to deep research"


from cosa.rest.routers._scope_registry import ScopeConfig


def _Scope( name, root ):
    """A REAL ScopeConfig.

    This was a two-attribute stand-in until the validator began applying the doc-viewer's
    own secrets-blocklist and prefix-whitelist guards, which read `manifest` and
    `extra_blocklist_patterns` — attributes the fake did not have, so it raised
    AttributeError the moment the real code grew. Same defect Krishna found one layer out,
    reproduced in my own harness: a stand-in thinner than the real object fails exactly
    when the code under test starts using the parts you left out. Empty `allowed_prefixes`
    is the wildcard case, which is what the built-in `io` scope actually uses.
    """
    return ScopeConfig( name=name, root=root, allowed_prefixes=( ) )


class _CountingFactory:
    """A job factory that records whether it was ever reached.

    THE POINT OF THE WHOLE FILE. A refusal that arrives after the job was built is not the
    refusal Rick asked for, and only this counter can tell the two apart.
    """

    def __init__( self ):
        self.calls = 0

    def __call__( self, *args, **kwargs ):
        self.calls += 1
        raise AssertionError( "the factory was reached; the door was supposed to refuse first" )


@pytest.fixture
def io_tree( tmp_path ):
    """A real `io/` scope with one readable document and one escaping symlink."""
    io_root = tmp_path / "io"
    ( io_root / "deep-research" ).mkdir( parents=True )
    ( io_root / "deep-research" / "notes.md" ).write_text( "# seed context\n" )

    outside = tmp_path / "outside"
    outside.mkdir()
    ( outside / "secret.md" ).write_text( "# not yours\n" )
    os.symlink( str( outside ), str( io_root / "escape" ) )

    return { "io": _Scope( "io", str( io_root ) ) }


def _flow( tmp_path, notifier, monkeypatch, factory, scopes, required_args=() ):
    """An AskFlow whose agentic path is reachable and whose factory refuses to be reached."""
    monkeypatch.setattr( v2.flow_mod, "resolve", lambda command, crud_enabled: None )
    monkeypatch.setattr( v2.flow_mod, "resolve_agentic",
                         lambda command: v2.FakeSpec( required_args=required_args, snapshotable=False ) )
    return v2.AskFlow(
        v2.FakeCache( lookup_result=None ), v2.FakeRouter(), v2.FakeExpeditor(),
        v2.FakeExecutor( None ), v2.FakePending(), crud_enabled=False,
        receptionist_factory=v2.FakeReceptionist, notifier=notifier,
        agentic_factory=factory, scope_registry_fn=lambda: scopes,
        trace_dir=str( tmp_path / "traces" ),
    )


def _submit( flow, args ):
    return flow.submit( command=_COMMAND, args=args, question="research it",
                        speak=False, **_CTX )


@pytest.mark.parametrize( "bad_value, expected_fragment, what", [
    ( "io/deep-research/absent.md", "does not exist",      "a path that is not there" ),
    ( "io/escape/secret.md",        "outside its scope",   "a symlink walking out of the scope" ),
    ( "nowhere/a.md",               "not readable",        "a scope nobody registered" ),
    ( "io/deep-research",           "directory",           "a directory where a file was named" ),
    ( "notes.md",                   "<scope>",             "an unscoped path" ),
    ( { "path": "a.md" },           "dict",                "a wrong type entirely" ),
] )
def test_a_bad_source_document_is_REFUSED_and_NOTHING_is_built(
        bad_value, expected_fragment, what, tmp_path, notifier, monkeypatch, io_tree ):
    """Each refusal reaches the caller as an answer, and the factory is never called."""
    factory = _CountingFactory()
    flow    = _flow( tmp_path, notifier, monkeypatch, factory, io_tree )

    result = _submit( flow, { "query": "a topic", SOURCE_DOCUMENT_ARG: bad_value } )

    assert result[ "status" ] == "needs_input", what
    assert expected_fragment in ( result[ "answer" ] or "" ), f"{what}: {result[ 'answer' ]!r}"
    assert factory.calls == 0, f"{what}: a job was built before the refusal"


def test_a_NEAR_MISS_key_is_REFUSED_rather_than_silently_accepted(
        tmp_path, notifier, monkeypatch, io_tree ):
    """THE FREE-FORM-BAG HOLE.

    `args` is a plain dict, so `source_documnet` is accepted by the door, the job runs,
    and the research comes back having read nothing — with no error anywhere. Shipping a
    document argument on a free-form bag without this check would ship a new way to hit
    the silent-degradation shape this fleet keeps finding.
    """
    factory = _CountingFactory()
    flow    = _flow( tmp_path, notifier, monkeypatch, factory, io_tree )

    result = _submit( flow, { "query": "a topic", "source_documnet": "io/deep-research/notes.md" } )

    assert result[ "status" ] == "needs_input"
    assert "source_documnet" in result[ "answer" ]
    assert SOURCE_DOCUMENT_ARG in result[ "answer" ], "the refusal should name the spelling meant"
    assert factory.calls == 0


def test_an_UNWIRED_scope_registry_REFUSES_rather_than_waving_the_path_through(
        tmp_path, notifier, monkeypatch ):
    """FAIL CLOSED. A scope check that silently does not run is worse than no feature —
    it admits any path on exactly the deployments where it was misconfigured."""
    monkeypatch.setattr( v2.flow_mod, "resolve", lambda command, crud_enabled: None )
    monkeypatch.setattr( v2.flow_mod, "resolve_agentic",
                         lambda command: v2.FakeSpec( required_args=(), snapshotable=False ) )
    factory = _CountingFactory()
    flow    = v2.AskFlow(
        v2.FakeCache( lookup_result=None ), v2.FakeRouter(), v2.FakeExpeditor(),
        v2.FakeExecutor( None ), v2.FakePending(), crud_enabled=False,
        receptionist_factory=v2.FakeReceptionist, notifier=notifier,
        agentic_factory=factory, scope_registry_fn=None,
        trace_dir=str( tmp_path / "traces" ),
    )

    result = _submit( flow, { "query": "a topic", SOURCE_DOCUMENT_ARG: "io/deep-research/notes.md" } )

    assert result[ "status" ] == "needs_input"
    assert "no document scopes are configured" in ( result[ "answer" ] or "" )
    assert factory.calls == 0


def test_an_ABSENT_source_document_does_NOT_refuse_and_reaches_the_factory(
        tmp_path, notifier, monkeypatch, io_tree ):
    """🔴 POSITIVE CONTROL ONE — the argument is OPTIONAL.

    Without this, every test above would pass against a door that refuses every submit,
    and the feature would read as working while having broken deep research entirely.
    """
    seen    = { }

    def factory( *args, **kwargs ):
        seen[ "reached" ] = True
        raise RuntimeError( "stop here — reaching the factory is the whole assertion" )

    flow = _flow( tmp_path, notifier, monkeypatch, factory, io_tree )
    _submit( flow, { "query": "a topic" } )

    assert seen.get( "reached" ) is True, "an absent optional argument was refused"


def test_a_VALID_source_document_reaches_the_factory_as_a_RESOLVED_ABSOLUTE_PATH(
        tmp_path, notifier, monkeypatch, io_tree ):
    """🔴 POSITIVE CONTROL TWO — and it asserts the ARGUMENT, not just the outcome.

    The agent needs a real path it can open. Checking only that the submit succeeded
    would pass against a door that validates the path and then hands the agent the
    original `<scope>/<rel>` string, which the agent cannot open — the check and the
    thing checked drifting apart, one layer down.
    """
    captured = { }

    def factory( *args, **kwargs ):
        # `args_dict` is the factory's own kwarg name (flow.py's call site). Reading
        # `args` here returned None and the test said so — the fake has to speak the
        # real signature or it proves nothing about the real call.
        captured[ "args" ] = kwargs[ "args_dict" ]
        raise RuntimeError( "stop here — the captured args are the assertion" )

    flow = _flow( tmp_path, notifier, monkeypatch, factory, io_tree )
    _submit( flow, { "query": "a topic", SOURCE_DOCUMENT_ARG: "io/deep-research/notes.md" } )

    delivered = ( captured.get( "args" ) or { } ).get( SOURCE_DOCUMENT_ARG )
    assert isinstance( delivered, list ), f"expected a list of resolved paths, got {delivered!r}"
    assert len( delivered ) == 1
    assert os.path.isabs( delivered[ 0 ] ), "the agent was handed a scope-relative string it cannot open"
    assert os.path.isfile( delivered[ 0 ] )
    assert delivered[ 0 ].endswith( "notes.md" )
