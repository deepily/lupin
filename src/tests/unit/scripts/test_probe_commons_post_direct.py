"""
`src/scripts/probe_commons_post_direct.py` — the truncation probe, covered without a real store.

A straggler from Rio's two-tier census at `cc336880` (49 statements, 8 branches). Claimed by
the SOUND direction: `git grep -l -- probe_commons_post_direct -- src/tests src/cosa/tests` was
EMPTY at `0f61dd85`, and empty is conclusive. Rio ⚡ held the earlier claim and withdrew it
explicitly at that sha, so the file has one owner.

🔴 WHAT THIS FILE IS CAREFUL ABOUT.

· THE REAL `CommonsStore` IS NEVER CONSTRUCTED. The probe already scopes itself to a
  `TemporaryDirectory`, so a live run would not pollute `io/commons/` — but it would take a
  `flock` and write 250 KB across nine posts to measure a cap this suite is not measuring.
  `CommonsStore` is patched at the MODULE attribute, so a missed patch is an error rather than
  a slow test that quietly does real I/O.
· THE FAKE IS THE INSTRUMENT, SO IT IS PROGRAMMABLE IN BOTH DIRECTIONS. A stand-in that always
  returns the body intact could only ever exercise the success branch, and the probe's whole
  purpose is to tell a surviving body from a truncated one. `_FakeStore` takes a cap, so the
  same suite drives the ✅ verdict, the ❌ verdict, a raising `post`, and an empty read-back.

WHY THE ASSERTIONS ARE ON STDOUT HERE, unlike the other straggler suites: this script has no
return value that varies — `run_probe` returns 0 on every path — and no persisted artifact. The
printed verdict IS the deliverable; a human reads "cap is FASTMCP-SPECIFIC" or its opposite and
acts on it. Asserting anything else would be asserting around the thing the script produces.
"""

import importlib.util
import os
import sys

import pytest


_ROOT       = os.environ.get( "LUPIN_ROOT", os.getcwd() )
SCRIPT_PATH = os.path.join( _ROOT, "src", "scripts", "probe_commons_post_direct.py" )

for _p in ( os.path.join( _ROOT, "src", "scripts" ), os.path.join( _ROOT, "src" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

_spec = importlib.util.spec_from_file_location( "probe_commons_post_direct", SCRIPT_PATH )
mod   = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( mod )


class _FakeStore:
    """
    Stand-in for CommonsStore that can truncate, raise, or lose a post on command.

    Requires:
        - `cap` is None (no truncation) or a positive int (bodies longer than it are cut)

    Ensures:
        - `post` records the call and stores the body, truncated to `cap` when one is set
        - `read` returns the most recent entry, or [] when `swallow` is set
        - `raise_at` makes `post` raise once the sent length reaches it, which is how a
          transport-level failure is distinguished from a silent truncation
    """
    def __init__( self, root, cap=None, raise_at=None, swallow=False ):
        self.root     = root
        self.cap      = cap
        self.raise_at = raise_at
        self.swallow  = swallow
        self.entries  = [ ]
        self.posts    = [ ]

    def post( self, topic, body, sender_session_id, persona_name, persona_icon,
              persona_color, metadata ):
        self.posts.append( { "topic": topic, "len": len( body ), "metadata": metadata,
                             "sender_session_id": sender_session_id,
                             "persona_name": persona_name } )
        if self.raise_at is not None and len( body ) >= self.raise_at:
            raise RuntimeError( "transport refused the write" )
        stored = body if self.cap is None else body[ : self.cap ]
        self.entries.append( { "body": stored } )

    def read( self, topic, limit ):
        if self.swallow: return [ ]
        return list( reversed( self.entries ) )[ :limit ]


@pytest.fixture
def store( monkeypatch ):
    """
    Patch CommonsStore with a factory the test can configure, and hand back the built store.

    Ensures:
        - returns a callable; call it with _FakeStore kwargs BEFORE running the probe
        - the returned holder's "store" key is the instance the probe actually used
    """
    holder = { "store": None, "kwargs": { } }

    def factory( root ):
        holder[ "store" ] = _FakeStore( root, **holder[ "kwargs" ] )
        return holder[ "store" ]

    monkeypatch.setattr( mod, "CommonsStore", factory )

    def configure( **kwargs ):
        holder[ "kwargs" ] = kwargs
        return holder

    return configure


# ── make_body ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "n", mod.PROBE_LENGTHS )
def test_make_body_is_exactly_the_requested_length( n ):
    """
    Every probe length produces a body of exactly that many characters. This is the probe's
    entire premise — a generator that were off by the prefix length would report a truncation
    at every size and the conclusion would be backwards.
    """
    assert len( mod.make_body( n ) ) == n


def test_make_body_is_deterministic():
    """The same length twice gives the same body, so two probe runs are comparable."""
    assert mod.make_body( 500 ) == mod.make_body( 500 )


def test_make_body_labels_itself_with_its_length():
    """
    The body carries its own intended length, so a truncated body read back from a real store
    still says what it was meant to be. That label is what makes a partial read diagnosable.
    """
    assert mod.make_body( 4_000 ).startswith( "PROBE-LEN-4000-" )


def test_make_body_cannot_go_below_its_own_prefix():
    """
    An honest limit, recorded rather than fixed: a length shorter than the prefix yields the
    prefix alone, so the body is LONGER than requested. No PROBE_LENGTHS entry is anywhere near
    this, and the script does not change here — but a future length below ~15 would silently
    break the equality every other test in this file rests on.
    """
    assert len( mod.make_body( 3 ) ) > 3


def test_probe_lengths_are_ascending_and_all_above_the_prefix():
    """
    The probe reports the FIRST failing length, which only names a threshold if the lengths
    ascend. Asserted on the constant because a reordered list would still run clean and report
    a meaningless "first" failure.
    """
    assert mod.PROBE_LENGTHS == sorted( mod.PROBE_LENGTHS )
    assert min( mod.PROBE_LENGTHS ) > len( "PROBE-LEN-XXXXXX-" )


# ── run_probe, the surviving path ────────────────────────────────────────────

def test_all_lengths_survive_reports_the_cap_as_fastmcp_specific( store, capsys ):
    """
    The verdict the probe exists to reach: an uncapped store means the truncation lives above
    it, in the transport. This is the sentence a reader acts on.
    """
    store()

    assert mod.run_probe() == 0

    out = capsys.readouterr().out
    assert "All lengths survived" in out
    assert "FASTMCP-SPECIFIC" in out
    assert "code review missed it" not in out


def test_every_probe_length_is_posted_once( store, capsys ):
    """
    All nine lengths are attempted, in order, with the length carried in the metadata. A probe
    that stopped at the first success would measure only the smallest body.
    """
    holder = store()

    mod.run_probe()

    posted = [ p[ "len" ] for p in holder[ "store" ].posts ]
    assert posted == mod.PROBE_LENGTHS
    assert [ p[ "metadata" ][ "probe_len" ] for p in holder[ "store" ].posts ] == mod.PROBE_LENGTHS


def test_posts_are_tagged_as_probes( store ):
    """
    Each post is marked `kind: probe` and sent as the Probe persona, so an entry that escaped
    the temporary directory into a real store would be identifiable rather than anonymous.
    """
    holder = store()

    mod.run_probe()

    first = holder[ "store" ].posts[ 0 ]
    assert first[ "metadata" ][ "kind" ]     == "probe"
    assert first[ "sender_session_id" ]      == "probe"
    assert first[ "topic" ]                  == "probe-direct"


def test_store_is_built_under_a_temporary_directory_that_is_cleaned_up( store ):
    """
    The docstring promises no pollution of `io/commons/`. The root handed to the store is a
    real directory during the run and gone afterwards — asserted both ways, because "it uses
    a TemporaryDirectory" is a claim about cleanup, not just about naming.
    """
    holder = store()
    seen   = { }

    original = mod.CommonsStore

    def spy( root ):
        seen[ "root" ]    = str( root )
        seen[ "existed" ] = os.path.isdir( root )
        return original( root )

    mod.CommonsStore = spy
    try:
        mod.run_probe()
    finally:
        mod.CommonsStore = original

    assert seen[ "existed" ] is True
    assert not os.path.isdir( seen[ "root" ] )


# ── run_probe, the failing paths ─────────────────────────────────────────────

def test_a_truncating_store_reports_the_opposite_verdict( store, capsys ):
    """
    The branch that would have overturned the prior code review. A cap below the largest probe
    length flips the conclusion, and the report names the first length that failed.
    """
    store( cap=1_000 )

    assert mod.run_probe() == 0

    out = capsys.readouterr().out
    assert "code review missed it" in out
    assert "FAIL at sent_len=4000" in out
    assert "All lengths survived" not in out


def test_the_first_failure_is_the_one_reported( store, capsys ):
    """
    With several lengths failing, the SMALLEST is named — that is the threshold a reader wants.
    Asserted because `next(...)` over the results would just as happily report any of them if
    the list were built out of order.
    """
    store( cap=200 )

    mod.run_probe()

    assert "FAIL at sent_len=500" in capsys.readouterr().out


def test_a_raising_post_is_recorded_as_a_failure_with_its_message( store, capsys ):
    """
    An exception is caught per length rather than aborting the sweep, and the error text lands
    in the table. A probe that died on the first refusal would never reach the larger sizes,
    which is where the interesting boundary usually is.
    """
    store( raise_at=8_000 )

    assert mod.run_probe() == 0

    out = capsys.readouterr().out
    assert "transport refused the write" in out
    assert "FAIL at sent_len=8000" in out


def test_the_sweep_continues_past_a_raising_length( store ):
    """Every length after the first raise is still attempted — the failure is not fatal."""
    holder = store( raise_at=1_000 )

    mod.run_probe()

    assert [ p[ "len" ] for p in holder[ "store" ].posts ] == mod.PROBE_LENGTHS


def test_a_post_that_reads_back_empty_is_a_failure_not_a_pass( store, capsys ):
    """
    A `post` that succeeds while `read` returns nothing is the silent-loss case, and the script
    turns it into an explicit error rather than a zero-length success. Without that guard the
    row would read `returned=0` and still have to be interpreted by hand.
    """
    store( swallow=True )

    assert mod.run_probe() == 0

    out = capsys.readouterr().out
    assert "post succeeded but read returned empty" in out
    assert "FAIL at sent_len=100" in out


def test_a_failing_row_reports_zero_returned_length( store, capsys ):
    """The error rows carry `returned = 0`, so the table never implies a partial body arrived."""
    store( raise_at=100 )

    mod.run_probe()

    lines = [ l for l in capsys.readouterr().out.splitlines() if l.strip().startswith( "100 |" ) ]
    assert lines
    assert "0" in lines[ 0 ].split( "|" )[ 1 ]


def test_the_table_marks_each_row_and_leaves_error_blank_on_success( store, capsys ):
    """
    A surviving row shows ✅ with an empty error column — the `err or ""` fallback. A row
    printing "None" would read as a value rather than an absence.
    """
    store()

    mod.run_probe()

    out = capsys.readouterr().out
    assert "✅" in out
    assert "None" not in out
