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


# ── María's bar, literally: every command a RUN emits, not a synthetic one ──────
#
# The test above proves _emit canonicalises a value I hand it. That is not quite what
# was asked for. The bar (María 🌸, echoed by Mr Radio 🦉) is: assert every
# payload.command IN A RUN is drawn from the known vocabulary — then revert the fix and
# watch it redden ON THAT ONE BARE RECORD. A guard that only ever sees values the test
# author chose is a guard that agrees with its author.
#
# The corpus lives under io/, which is gitignored, so this SKIPS when no run is present
# rather than failing. That is a real limitation and worth naming: the always-on guard is
# the synthetic one above; this is the one that reddens on production data when data
# exists. Both were run against the reverted fix, and both went red.

# The v2 arm names every run directory `eval-<timestamp>`; nothing else it writes carries a
# records.jsonl. Anchoring on that prefix is what makes "newest" mean "newest V2 RUN".
V2_RUN_DIR_GLOB = "eval-*"


def _newest_run_records():
    """The most recent v2 eval records.jsonl, or None. Never raises.

    🔴 THE PREFIX IS LOAD-BEARING (Mr Radio, 2026-08-26). This globbed `*` and so claimed
    ANY records.jsonl under io/v2-flow as a v2 run. A v1-arm run written alongside it —
    same filename, different schema, newer mtime — won `max( …, getmtime )`, and the test
    failed reporting "the corpus is not what this asserts against". The corpus was fine; the
    file was not a v2 run at all. A false accusation pointed at the wrong subject entirely.

    NARROWING HERE LOSES NOTHING, verified rather than assumed: at the time of the change all
    12 directories under io/v2-flow holding a records.jsonl were named `eval-*` and all 12
    carried payload.command. The prefix selects exactly the same set and excludes foreign
    artifacts. (Contrast the serial-bridge-guard glob, which must stay wide — there, narrowing
    dropped real signal. Here the wide form only admitted files this test cannot read.)
    """
    import glob
    candidates = glob.glob(
        os.path.join( os.environ[ "LUPIN_ROOT" ], "io", "v2-flow", V2_RUN_DIR_GLOB, "records.jsonl" )
    )
    return max( candidates, key=os.path.getmtime ) if candidates else None


def test_every_command_in_a_real_run_is_drawn_from_the_known_vocabulary():
    """Replay every DISTINCT command a real run recorded back through the emitter.

    Row 759a895b's bare `math` is in that set, so reverting the fix in `_emit` turns this
    red naming that exact value — which is what makes it a guard rather than a claim.
    """
    import json

    records_path = _newest_run_records()
    if records_path is None:
        pytest.skip( "no v2 eval run present (io/ is gitignored) — the synthetic _emit guard above still runs" )

    from cosa.rest.v2 import flow as flow_module

    class _Trace:
        trace_id = "t-759a895b"
        fields   = {}
        def mark( self, *a, **k ):  pass
        def update( self, **k ):    pass
        def write( self ):          pass
        def has_mark( self, *a ):   return False
        def timings_ms( self ):     return {}

    class _Flow:
        debug = verbose = False
        def _log_query( self, *a, **k ): pass

    recorded = set()
    with open( records_path ) as handle:
        for line in handle:
            payload = ( json.loads( line ).get( "payload" ) or {} )
            if payload.get( "command" ) is not None:
                recorded.add( payload[ "command" ] )
    assert recorded, f"{records_path} carried no commands at all — the corpus is not what this asserts against"

    escapes = []
    for command in sorted( recorded ):
        emitted = flow_module.AskFlow._emit(
            _Flow(), _Trace(), path="agent", status="waiting", route_reason="args_none",
            answer=None, answer_raw=None, command=command, ctx=( "u", "e@x.com", "s", None, False ),
        )[ "command" ]
        if emitted not in KNOWN_VOCABULARY:
            escapes.append( f"{command!r} emitted as {emitted!r}, which is not a known command" )

    assert escapes == [], (
        f"{os.path.basename( os.path.dirname( records_path ) )} contains commands that reach output "
        f"outside the known vocabulary — every count grouped by payload.command splits on these: {escapes}"
    )


class TestNewestRunRecordsPicksOnlyV2Runs:
    """
    The selector, pinned. `_newest_run_records` decides WHICH file the guard above reads, so a
    selector that picks the wrong file makes the guard report on something it never measured.

    The failure this pins actually happened (2026-08-26): a v1-arm run wrote its own
    records.jsonl beside the v2 runs — same filename, different schema, newer mtime — and the
    guard read it and failed naming the corpus. Both tests below FAIL if the `eval-*` prefix is
    dropped back to `*`, which is what makes the prefix a guard rather than a preference.
    """

    def _make( self, tmp_path, monkeypatch, name, mtime ):
        run_dir = tmp_path / "io" / "v2-flow" / name
        run_dir.mkdir( parents=True )
        records = run_dir / "records.jsonl"
        records.write_text( '{"utterance":"u","payload":{"command":"agent router go to todo"}}\n' )
        os.utime( records, ( mtime, mtime ) )
        monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
        return str( records )

    def test_a_newer_non_eval_directory_never_displaces_the_newest_eval_run( self, tmp_path, monkeypatch ):
        wanted = self._make( tmp_path, monkeypatch, "eval-2026-08-25-19-31-31", mtime=1_000 )
        self._make( tmp_path, monkeypatch, "v1-arm-n60-2026-08-26-10-01-33", mtime=9_000 )   # NEWER
        assert _newest_run_records() == wanted

    def test_the_newest_eval_run_still_wins_among_eval_runs( self, tmp_path, monkeypatch ):
        self._make( tmp_path, monkeypatch, "eval-2026-08-16-13-24-46", mtime=1_000 )
        wanted = self._make( tmp_path, monkeypatch, "eval-2026-08-25-19-31-31", mtime=5_000 )
        assert _newest_run_records() == wanted

    def test_no_eval_run_at_all_returns_none_rather_than_raising( self, tmp_path, monkeypatch ):
        self._make( tmp_path, monkeypatch, "v1-arm-n60-2026-08-26-10-01-33", mtime=9_000 )
        assert _newest_run_records() is None
