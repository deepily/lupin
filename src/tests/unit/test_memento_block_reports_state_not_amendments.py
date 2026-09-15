"""
The rehydrate block must report whether the memento CARRIES STATE, not whether it
happens to have an amendment tail.

Row: Tiberius 👑's report, 2026-09-05 — the boot path resolved his real 5,758-byte
memento, stamped a healthy receipt, and told him it carried no state.

MEASURED over `io/mementos/` the same day: 656 records, 517 with no amendment tail.
516 of those carry real prose (smallest 1,315 bytes); exactly one strips to nothing,
and it is a POINTER file rather than a record. The warning fired on 517 and was
correct about none of them.

The three states these tests pin:
    amendment tail present            -> show the tail          (unchanged)
    no tail, body carries prose       -> show the BODY          (the new state)
    no tail, no prose at all          -> the near-blank warning (preserved, narrowed)
"""

import sys
from pathlib import Path

_HOOKS = Path( __file__ ).resolve().parents[ 3 ] / "src" / "lupin_cli" / "claude_code" / "hooks"
if str( _HOOKS ) not in sys.path: sys.path.insert( 0, str( _HOOKS ) )

import register_session as rs


NEAR_BLANK = "CARRIES NO STATE"
BODY_STATE = "ALL OF ITS STATE IS IN THE BODY"

_HEADER  = "<!-- memento-record: persona=krishna session_id=056ca4c8 written_at=2026-09-05T22:00:00-04:00 slot=io -->\n"
_POINTER = (
    "<!-- MEMENTO POINTER — NOT THE RECORD. Safe to overwrite; it destroys nothing. -->\n"
    "<!-- current: io/mementos/krishna-056ca4c8.md -->\n"
)


def _prose( n_lines=40 ):
    return "\n".join( f"**Held**: line {i} of what I was doing before the reset." for i in range( n_lines ) )


# ── _substantive_body: the predicate the branch now keys on ──────────────────────

def test_a_pointer_file_strips_to_nothing():
    """The ONE record in the measured population that is genuinely stateless."""
    assert rs._substantive_body( _POINTER ) == ""


def test_a_record_with_only_a_header_strips_to_nothing():
    assert rs._substantive_body( _HEADER ) == ""


def test_none_and_empty_are_stateless_and_do_not_raise():
    assert rs._substantive_body( None ) == ""
    assert rs._substantive_body( "" )   == ""


def test_a_body_with_prose_is_substantive():
    body = rs._substantive_body( _HEADER + _prose() )
    assert "line 0" in body and "line 39" in body
    assert "memento-record:" not in body, "the header comment must not survive the strip"


def test_blank_lines_alone_are_not_state():
    assert rs._substantive_body( _HEADER + "\n\n   \n\t\n" ) == ""


# ── the branch: three states, and each must EXCLUDE the other two ────────────────

def _block( tmp_path, monkeypatch, content ):
    """
    Drive the REAL `_build_memento_block` — the function the boot path calls — with
    only two seams stood down: the path resolver (so the record is ours) and the
    receipt stamp (so a unit test writes nothing into fleet data).

    🔴 THE LAYER IS THE POINT. The incident entered at the boot path building this
    block, so that is where the test knocks. Calling `_substantive_body` alone would
    prove the predicate and say nothing about whether the branch reaches it.
    """
    record = tmp_path / "krishna-056ca4c8.md"
    record.write_text( content, encoding="utf-8" )
    monkeypatch.setattr( rs, "_resolve_memento_path",      lambda *a, **k: record )
    monkeypatch.setattr( rs, "_stamp_respin_boot_receipt", lambda *a, **k: None )
    return rs._build_memento_block( "056ca4c8", "krishna", repo_root=tmp_path, cwd=str( tmp_path ) )


def test_a_body_only_memento_is_not_called_near_blank( tmp_path, monkeypatch ):
    """Tiberius's case: real state, no tail. This is the regression."""
    block = _block( tmp_path, monkeypatch, _HEADER + _prose() )
    assert NEAR_BLANK not in block, "a full record must not be reported as carrying no state"
    assert BODY_STATE in block
    assert "line 39" in block, "the body itself must reach the seat, not just a pointer to it"


def test_a_genuinely_empty_record_still_gets_the_warning( tmp_path, monkeypatch ):
    """Rachel 🕊️'s 2026-08-15 finding — preserved, narrowed, not reverted."""
    block = _block( tmp_path, monkeypatch, _HEADER )
    assert NEAR_BLANK in block
    assert BODY_STATE not in block


def test_a_pointer_file_still_gets_the_warning( tmp_path, monkeypatch ):
    block = _block( tmp_path, monkeypatch, _POINTER )
    assert NEAR_BLANK in block


# ── the zone between the two predicates ──────────────────────────────────────────
# Two fixes for this defect met at the triage merge (row ef0fa72b): a 200-byte presence
# floor after the header (`_memento_body_after_header`) and a comment-stripped prose
# predicate (`_substantive_body`). The merged branch requires BOTH, and a record either
# one alone would deliver takes the near-blank warning (confirmed as the intended call).
# These two records are where the predicates disagree. Each test first proves its record
# really sits in that zone, or a green would say nothing about which rule decided it.

_THIN_PROSE = ( "**Held**: reviewing the triage merge; I owe two route tests and the "
                "typecheck gate before reporting back. Nothing else is in flight now." )
_THIN_PROSE = ( _THIN_PROSE + "." * 150 )[ :150 ]

_COMMENT_LINE    = "<!-- scaffold, not state: this line says nothing about the work -->\n"
_COMMENTS_ONLY   = _COMMENT_LINE * 4
_COMMENTS_ONLY  += "<!--" + "x" * ( 300 - len( _COMMENTS_ONLY ) - len( "<!---->\n" ) ) + "-->\n"


def test_a_thin_prose_body_under_the_floor_gets_the_warning( tmp_path, monkeypatch ):
    """150 bytes of real prose: the prose predicate says state, the floor says none."""
    content = _HEADER + _THIN_PROSE + "\n"
    assert len( _THIN_PROSE.encode( "utf-8" ) ) == 150
    assert rs._substantive_body( content ) != "",            "the record must carry prose"
    assert rs._memento_body_after_header( content ) is None, "the record must sit under the floor"

    block = _block( tmp_path, monkeypatch, content )
    assert NEAR_BLANK in block
    assert BODY_STATE not in block


def test_a_comments_only_body_over_the_floor_gets_the_warning( tmp_path, monkeypatch ):
    """300 bytes of HTML comments: the floor says state, the prose predicate says none."""
    content = _HEADER + _COMMENTS_ONLY
    assert len( _COMMENTS_ONLY.encode( "utf-8" ) ) == 300
    assert rs._substantive_body( content ) == "",                "the record must carry no prose"
    assert rs._memento_body_after_header( content ) is not None, "the record must clear the floor"

    block = _block( tmp_path, monkeypatch, content )
    assert NEAR_BLANK in block
    assert BODY_STATE not in block


def test_an_amendment_tail_still_wins_over_the_body( tmp_path, monkeypatch ):
    """The unchanged path: when a tail exists it is what the seat is shown."""
    content = _HEADER + _prose() + "\n<!-- memento-amendment: 2026-09-05 -->\nthe held merge\n"
    block   = _block( tmp_path, monkeypatch, content )
    assert "YOU HAVE A MEMENTO — YOU WROTE IT BEFORE THIS CONTEXT RESET" in block
    assert BODY_STATE not in block
    assert NEAR_BLANK not in block
    assert "the held merge" in block


# ── which END survives the truncation ────────────────────────────────────────────
# Tiberius 👑 asked whether the fix delivers the BODY or only re-words the block.
# It delivers it — measured on the real `clayton-d34333a9.md`: 20,765 bytes on disk,
# 8,745 delivered, against ~440 under the old branch. But the delivery kept the TAIL,
# which is right for amendments and wrong for a body: the first line, the who-am-I,
# was dropped. These pin the answer per branch.

def test_a_long_body_is_quoted_from_ITS_OPENING( tmp_path, monkeypatch ):
    """A body-only memento leads with who you are and what you hold — keep the head."""
    first = "# Memento — Krishna 🦚 · THIS LINE IS THE WHO-AM-I"
    last  = "**FINAL**: the very last line of a long body."
    body  = first + "\n" + "\n".join( f"filler line {i}" for i in range( 4000 ) ) + "\n" + last + "\n"
    block = _block( tmp_path, monkeypatch, _HEADER + body )

    assert first in block, "the opening of a body-only memento must survive truncation"
    assert "later bytes omitted" in block, "the cut must be visible and say which end went"
    assert last not in block, "the arm is meaningless unless the body was actually cut"


def test_a_long_AMENDMENT_tail_is_still_quoted_from_its_END( tmp_path, monkeypatch ):
    """The unchanged rule, kept as the control: amendments accrete, so the newest wins."""
    newest  = "**NEWEST**: the amendment written just before the reset."
    content = ( _HEADER + _prose() + "\n<!-- memento-amendment: 2026-09-05 -->\n"
                + "\n".join( f"old amendment line {i}" for i in range( 4000 ) ) + "\n" + newest + "\n" )
    block   = _block( tmp_path, monkeypatch, content )

    assert newest in block, "the newest amendment must survive truncation"
    assert "earlier bytes omitted" in block
    assert "old amendment line 0" not in block, "the arm is meaningless unless it was cut"


# ── a big tail must not consume the whole budget ─────────────────────────────────
# Tiberius 👑, corpus, 2026-09-05: 56 of 129 tailed records carry a tail over 8,000
# bytes — 43% — and across 161 bodies the first load-bearing marker sits at a median
# 0.166 of the way in, 111 of 161 in the first quarter. Measured on the live
# `.claude-memento-maria-21979045.md`: 37,584-byte record, 27,365-byte tail, 8,617
# delivered, and `# 1. WHO I AM / SEAT` was NOT among it. A seat rehydrated with its
# owed work and no identity.

def test_a_huge_tail_does_not_evict_the_who_am_i( tmp_path, monkeypatch ):
    who     = "# 1. WHO I AM — Krishna 🦚, author on Mr. Radio's crew"
    newest  = "**NEWEST**: the amendment written just before the reset."
    content = (
        _HEADER + who + "\n" + _prose( 200 ) + "\n"
        + "<!-- memento-amendment: 2026-09-05 -->\n"
        + "\n".join( f"old amendment line {i}" for i in range( 4000 ) ) + "\n" + newest + "\n"
    )
    block = _block( tmp_path, monkeypatch, content )

    assert who    in block, "the identity line must survive a tail that fills the budget"
    assert newest in block, "and the newest amendment must still survive too"
    assert "old amendment line 0" not in block, "meaningless unless the tail was truly cut"


def test_the_lead_is_omitted_when_there_is_no_body_to_lead_with( tmp_path, monkeypatch ):
    """A record that is header + amendments only must not grow an empty lead section."""
    content = _HEADER + "<!-- memento-amendment: 2026-09-05 -->\nthe held merge\n"
    block   = _block( tmp_path, monkeypatch, content )

    assert "the held merge" in block
    assert "Who you are, from the top of the record" not in block


# ── the lead SIZE, pinned by an OBSERVABLE rather than by the number ─────────────
# Tiberius 👑, 2026-09-05: moving _MEMENTO_BODY_LEAD_BYTES from 2,000 to 3,000 reddened
# NOTHING across 575 tests — the constant was present, correct, and untestable-if-wrong.
# § UNGUARDED IS A THIRD STATE. The arm that proved it: baseline first (0 failures), then
# 3000 -> 2000, failing SETS byte-identical.
#
# 🔴 A TEST ASSERTING `_MEMENTO_BODY_LEAD_BYTES == 3000` WOULD PIN THE NUMBER AND WATCH
# NOTHING. This pins what the number is FOR: content at a known depth reaches the seat.
# His corpus is why the depth matters — a 2,000-byte lead reaches the opening in 80% of
# records, 3,000 in 90%, so the band between them is real content in real mementos.

_LEAD_MARKER = "**LOAD-BEARING**: the held merge and the crew, 2,500 bytes in."


def _body_with_marker_at( offset_bytes ):
    """A body whose load-bearing line begins at approximately `offset_bytes`."""
    filler = "\n".join( f"preamble line {i:04d}" for i in range( 4000 ) )
    return filler.encode( "utf-8" )[ :offset_bytes ].decode( "utf-8", errors="ignore" ) \
           + "\n" + _LEAD_MARKER + "\n" + filler


def test_content_2500_bytes_into_the_body_still_reaches_the_seat( tmp_path, monkeypatch ):
    """
    THE OBSERVABLE, not the constant. At a 3,000-byte lead this survives; at 2,000 it does
    not — which is exactly the band Tiberius measured as 80% -> 90% of real records.
    """
    content = ( _HEADER + _body_with_marker_at( 2500 )
                + "\n<!-- memento-amendment: 2026-09-05 -->\nthe held merge\n" )
    block   = _block( tmp_path, monkeypatch, content )

    assert _LEAD_MARKER in block, (
        "a load-bearing line 2,500 bytes into the body must reach the seat — if this fails, "
        "the lead reserve shrank below the depth real mementos put their state at"
    )
    assert "the held merge" in block, "and the amendment tail must still survive alongside it"


def test_the_lead_is_bounded_and_does_not_swallow_the_whole_body( tmp_path, monkeypatch ):
    """
    The OTHER side, so the pin is not satisfiable by simply quoting everything — without
    this, raising the reserve to the full budget would pass the test above and starve the tail.
    """
    deep    = "**TOO DEEP**: this line sits far past any sane lead."
    content = ( _HEADER + _body_with_marker_at( 2500 ) + "\n" + deep + "\n"
                + "<!-- memento-amendment: 2026-09-05 -->\nthe held merge\n" )
    block   = _block( tmp_path, monkeypatch, content )

    assert _LEAD_MARKER in block
    assert deep not in block, "the lead must remain bounded, or the tail loses its share"
