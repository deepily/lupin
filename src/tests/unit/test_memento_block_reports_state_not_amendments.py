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
