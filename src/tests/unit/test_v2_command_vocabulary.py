"""
Row 759a895b (María 🌸's finding, Clayton 😎's fix) — one route, one name.

THE DEFECT. `math` is a registered ALIAS of `agent router go to math`, and `resolve()`
honours aliases, so a router emitting the short form ROUTED CORRECTLY. Only the record
was wrong: `_emit` copied the raw router string into `payload.command`, so one route
reached the output vocabulary under two spellings. Measured in
`io/v2-flow/eval-2026-08-25-19-31-31/records.jsonl`: 50 records spell it
`agent router go to math`, 2 spell it `math`, same `route_reason`, and the two bare
records are the SAME utterance in the cold and warm passes.

WHY IT NEEDED A TEST AND NOT JUST A FIX. Two records in two hundred changes nothing
material, which is exactly why it would have survived indefinitely. The guard María
asked for is: every command a run emits must be drawn from the known vocabulary.
"""
import os
import sys

import pytest

_src_path = os.path.join( os.environ[ "LUPIN_ROOT" ], "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.v2.registry import REGISTRY, canonical_command


# The vocabulary a run is allowed to emit: the canonical commands, and nothing else.
KNOWN_VOCABULARY = frozenset( REGISTRY )


def test_every_registry_alias_canonicalises_into_the_known_vocabulary():
    """THE GUARD. Every alias the registry accepts must map to a canonical command.

    This is the assertion that would have caught the defect: an alias reaching output
    un-canonicalised is a value NOT in the known vocabulary, which is precisely how
    `math` split every count grouped by `payload.command`.
    """
    escapes = []
    for canonical, spec in REGISTRY.items():
        for alias in spec.aliases:
            resolved = canonical_command( alias )
            if resolved not in KNOWN_VOCABULARY:
                escapes.append( f"alias {alias!r} (of {canonical!r}) -> {resolved!r}, not in the vocabulary" )
    assert escapes == [], f"aliases that would reach output under their own spelling: {escapes}"


def test_the_exact_record_that_started_this_row():
    """`math` is the value María found in the corpus. It must land on the long form."""
    assert canonical_command( "math" ) == "agent router go to math"


def test_a_canonical_command_is_returned_unchanged():
    """Canonicalising twice must not move — otherwise _emit would be order-dependent."""
    for command in REGISTRY:
        assert canonical_command( command ) == command
        assert canonical_command( canonical_command( command ) ) == command


@pytest.mark.parametrize( "value", [ None, "", "agent router go to nowhere", "not a command" ] )
def test_unknown_and_empty_values_pass_through_untouched( value ):
    """An unknown string is not ours to invent a spelling for, and None reaches _emit on
    paths that never had a command (flow.py's degrade callers). Both must survive."""
    assert canonical_command( value ) == value


def test_emit_records_the_canonical_name_for_an_alias():
    """THE FIX AT ITS CHOKEPOINT. _emit is the single terminal exit, so the canonical
    name must appear in the payload it returns — not merely be available from a helper."""
    from cosa.rest.v2 import flow as flow_module

    captured = {}

    class _Trace:
        trace_id = "t-759a895b"
        fields   = {}
        def mark( self, *a, **k ):      captured[ "marked" ] = True
        def update( self, **k ):        captured.update( k )
        def write( self ):              pass
        def has_mark( self, *a ):       return False
        def timings_ms( self ):         return {}

    class _Flow:
        debug = verbose = False
        def _log_query( self, *a, **k ): pass

    payload = flow_module.AskFlow._emit(
        _Flow(), _Trace(), path="agent", status="waiting", route_reason="args_none",
        answer=None, answer_raw=None, command="math", ctx=( "u", "e@x.com", "s", None, False ),
    )
    assert payload[ "command" ] == "agent router go to math", (
        f"_emit recorded {payload[ 'command' ]!r} — the alias reached output un-canonicalised, "
        "which is the defect row 759a895b fixed"
    )
