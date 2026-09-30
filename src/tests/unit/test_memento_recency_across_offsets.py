"""
"Newest first" must mean newest in TIME, not newest as text — row f99bed95.

THE DEFECT. `_memento_candidates` ranked records by the raw ISO text of their
`written_at` header. ISO text orders chronologically only when every stamp shares
one UTC offset, and the live slot does not.

MEASURED against `io/mementos/` on 2026-08-29: 214 stamped records carrying two
offsets — 212 at -04:00 and 2 at +00:00 — producing **12 inverted pairs**. The
example below is one of them, taken from real filenames:

    tiffany-6ac667b0.md            2026-08-16T14:06:48-04:00  =  18:06:48Z
    rio-legacy-20260816-140016.md  2026-08-16T17:44:53+0000   =  17:44:53Z

The first is the LATER moment and sorts BELOW the second as text. Twelve pairs is
small today and grows with every writer that stamps in UTC.

WHY IT IS WORTH FIXING RATHER THAN NOTING. This is the same key that handed a
successor a 2.8-day-old memento. That defect was the TIER split — a header-less
record demoted below every stamped one — and this is a second, independent way
the same key can name the wrong file. Fixing one and leaving the other would
close the row on the symptom that happened to be observed.
"""
import os

import pytest

from lupin_cli.claude_code.hooks.register_session import (
    _memento_candidates,
    _recency_key,
    _resolve_memento_path,
    _stamp_instant,
)

SID_FRESH = "ffffffff-1111-2222-3333-444444444444"


def _io_slot( root ):
    slot = os.path.join( root, "io", "mementos" )
    os.makedirs( slot, exist_ok=True )
    return slot


def _write( root, name, written_at ):
    path = os.path.join( _io_slot( root ), name )
    stamp = f" written_at={written_at}" if written_at else ""
    with open( path, "w", encoding="utf-8" ) as fh:
        fh.write( f"<!-- memento-record: persona=rio session_id=deadbeef{stamp} slot=io -->\n"
                  "# Memento\nheld state\n" )
    return path


@pytest.fixture
def repo( tmp_path ):
    return str( tmp_path )


# ---------------------------------------------------------------------------
# The instant, not the text
# ---------------------------------------------------------------------------
def test_the_measured_inversion_is_ordered_by_time_not_text( repo ):
    """
    THE REPRODUCTION, using the two real stamps from the live slot. Before the
    fix the -04:00 record — which is the LATER moment — ranked second.
    """
    later   = _write( repo, "rio-6ac667b0.md", "2026-08-16T14:06:48-04:00" )   # 18:06:48Z
    earlier = _write( repo, "rio-140016.md",   "2026-08-16T17:44:53+0000" )    # 17:44:53Z

    ranked = [ p for p, _, _ in _memento_candidates( repo, slugs=[ "rio" ] ) ]
    assert ranked == [ later, earlier ]


def test_the_text_order_really_is_the_opposite( repo ):
    """
    POSITIVE CONTROL. The test above proves nothing unless the two stamps
    genuinely disagree — otherwise it would pass against the old code too.
    """
    assert "2026-08-16T14:06:48-04:00" < "2026-08-16T17:44:53+0000"          # text says earlier
    assert _stamp_instant( "2026-08-16T14:06:48-04:00" ) > _stamp_instant( "2026-08-16T17:44:53+0000" )


def test_resolution_follows_the_ordering( repo ):
    """What the RUN produces. A ranking fix that the resolver ignores is décor."""
    later = _write( repo, "rio-6ac667b0.md", "2026-08-16T14:06:48-04:00" )
    _write( repo, "rio-140016.md", "2026-08-16T17:44:53+0000" )
    assert _resolve_memento_path( SID_FRESH, "Rio", repo ) == later


@pytest.mark.parametrize( "a,b", [
    ( "2026-08-16T23:30:00-04:00", "2026-08-17T01:00:00+00:00" ),   # crosses midnight UTC
    ( "2026-01-01T00:30:00+05:30", "2026-01-01T00:00:00+00:00" ),   # half-hour offset
    ( "2026-08-16T14:06:48-04:00", "2026-08-16T17:44:53+0000" ),    # the measured pair
] )
def test_text_order_and_time_order_DISAGREE_on_these_pairs( a, b ):
    """
    The property, asserted as a disagreement rather than a fixed direction.

    ⚠️ MY FIRST CUT OF THIS TEST ASSERTED A DIRECTION AND WAS WRONG — I claimed
    `00:30+05:30` was the later instant when it is 19:00Z the previous day, and
    the test caught me rather than the code. Asserting "these two orderings
    disagree" is both the real property and immune to my getting a sign backwards:
    it fails if the pair is not actually an inversion, whichever way it runs.

    The third pair is the one measured on the live slot, by filename.
    """
    text_says_a_is_later = a > b
    time_says_a_is_later = _stamp_instant( a ) > _stamp_instant( b )
    assert text_says_a_is_later != time_says_a_is_later


# ---------------------------------------------------------------------------
# The stamp parser
# ---------------------------------------------------------------------------
@pytest.mark.parametrize( "stamp", [ None, "", "not-a-date", "2026-13-45T99:99:99+00:00" ] )
def test_an_unusable_stamp_yields_no_instant( stamp ):
    assert _stamp_instant( stamp ) is None


def test_a_NAIVE_stamp_is_refused_rather_than_assumed_local():
    """
    Ordering a naive stamp against an aware one means guessing a zone, and
    guessing a zone is what produced the inversion. `reap_memento._parse_iso_aware`
    already makes this call; the two must not grow different answers.
    """
    assert _stamp_instant( "2026-08-16T14:06:48" ) is None


# ---------------------------------------------------------------------------
# The tier split must survive — it is the row's original fix
# ---------------------------------------------------------------------------
def test_a_dated_record_still_outranks_an_undated_one_with_a_newer_mtime( repo ):
    """
    REGRESSION GUARD for the pre-existing rule: the header stamp travels with the
    content, mtime does not. Undated-but-freshly-touched must still lose.
    """
    dated   = _write( repo, "rio-11111111.md", "2026-08-01T09:00:00-04:00" )
    undated = _write( repo, "rio-22222222.md", None )
    os.utime( undated, ( 9_000_000_000, 9_000_000_000 ) )

    ranked = [ p for p, _, _ in _memento_candidates( repo, slugs=[ "rio" ] ) ]
    assert ranked == [ dated, undated ]


def test_a_naive_stamp_falls_to_the_mtime_tier_and_is_never_dropped( repo ):
    """
    Refusing to ORDER a naive stamp must not mean discarding the record. It
    demotes to mtime, where it is still findable when it is all there is.
    """
    naive = _write( repo, "rio-33333333.md", "2026-08-16T14:06:48" )
    assert _recency_key( naive, "2026-08-16T14:06:48" )[ 0 ] == 0
    assert _resolve_memento_path( SID_FRESH, "Rio", repo ) == naive


def test_an_unreadable_mtime_ranks_last_but_still_lists( repo, monkeypatch ):
    """Both tiers now carry a float, so the floor is -inf rather than an empty
    string. The property is what matters: last, never dropped."""
    import lupin_cli.claude_code.hooks.register_session as rs
    path = _write( repo, "rio-44444444.md", None )
    monkeypatch.setattr( rs.os.path, "getmtime", lambda p: ( _ for _ in () ).throw( OSError( "vanished" ) ) )
    assert _recency_key( path, None ) == ( 0, float( "-inf" ) )


def test_both_tiers_are_mutually_comparable( repo ):
    """
    A tuple whose second element is a float in one tier and a string in another
    only survives because Python short-circuits on the first element. That is a
    latent TypeError one refactor away; pin that both are floats.
    """
    dated   = _write( repo, "rio-55555555.md", "2026-08-01T09:00:00-04:00" )
    undated = _write( repo, "rio-66666666.md", None )
    for key in ( _recency_key( dated, "2026-08-01T09:00:00-04:00" ), _recency_key( undated, None ) ):
        assert isinstance( key[ 1 ], float )
