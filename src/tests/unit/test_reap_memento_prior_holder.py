"""
Unit tests for the PRIOR-HOLDER split and the loud top-level line (row 3b0c5f90).

THE DEFECT UNDER TEST. `unparseable_present` meant two opposite things within ten
minutes on 2026-08-17. On extra 1 (751f5944) it was a RACE — the seat's own memento,
mid-write, genuinely fine seconds later. On sam (4fa58ddc) it was a PRIOR HOLDER's
file sitting in the slot while sam's memento did not exist anywhere. Same verdict,
opposite recovery actions: open-and-read in one case, go-hunting-or-accept-the-loss
in the other. A manager who must open the file every time to learn which one it was
will eventually stop opening it, and the alarm stops working.

The evidence to tell them apart was already read and thrown away: `verify_seat_memento`
parses the header, pulls its `session_id`, and compares it to the seat — then folds
that comparison into a prose reason string and buckets the result with everything else
that is "present but unproven".

THE SECOND HALF. Even a correct per-seat verdict was being missed, because it sits in
a nested `memento_outcomes` dict while the reap reports success around it. `memento_alarm`
is the one line that goes at the TOP of the reap result, and returns None when there is
nothing to say — so its presence carries information.

WHAT THESE TESTS PIN, and what a weaker suite would miss: not "the batch failed" but
WHICH verdict each shape earns. The prior-holder case must NOT stay `unparseable_present`,
and — the direction that is easy to break while making the first one pass — the genuinely
unparseable case and the seat's-own-but-stale race case must NOT be swept into the new
verdict. All three shapes are asserted here, so a fix that over-reaches goes red.

Every seam (clock, file read, DM send, sleep) is injected — no live server.
"""

import datetime

import pytest

from lupin_mcp import reap_memento
from lupin_mcp import session_spawner as ss


# ── Fixtures / helpers ────────────────────────────────────────────────────────
_NOW  = datetime.datetime( 2026, 8, 17, 21, 33, 0, tzinfo=datetime.timezone.utc )
_REPO = "/repos/lupin"

# sam's real shape on the day: HIS seat, a PRIOR holder's file in the slot.
_SAM_SID    = "4fa58ddc0000"
_PRIOR_SID  = "1fe241ea0000"


def _now_fn():
    return _NOW


def _memento( persona, sid8, written_at="2026-08-17T21:32:00+00:00", body_bytes=1200 ):
    """A complete, fresh memento carrying a line-1 memento-record header."""
    header = ( f"<!-- memento-record: persona={persona} session_id={sid8} "
               f"written_at={written_at} slot=io -->\n" )
    return header + ( "x" * body_bytes )


class _Disk:
    """Injected file store: maps str(path) -> text; a missing key reads as None."""
    def __init__( self, files=None ):
        self.files = dict( files or {} )
    def read( self, path ):
        return self.files.get( str( path ) )


class _DM:
    def __init__( self ):
        self.calls = []
    def __call__( self, persona, session_id, body ):
        self.calls.append( { "persona": persona, "session_id": session_id } )
        return { "status": "sent" }


def _ident( name, sid, cwd=_REPO ):
    return { "persona": { "name": name }, "session_id": sid, "cwd": cwd }


def _slot( persona_slug, repo=_REPO ):
    return f"{repo}/io/mementos/{persona_slug}.md"


def _coord( identities, disk, dm=None ):
    return reap_memento.coordinate_mementos(
        identities, write_memento=True,
        now_fn=_now_fn, read_text_fn=disk.read, dm_fn=dm or _DM(),
        sleep_fn=lambda _s: None )


# ── The divergence: a prior holder's file is not "unparseable" ────────────────
def test_prior_holders_memento_in_the_slot_gets_its_own_verdict():
    """
    THE RED, and the whole receipt for defect 2 of row 3b0c5f90.

    sam's exact shape: the slot holds a complete, parseable, perfectly readable
    memento — belonging to session 1fe241ea, not to the seat being reaped. Against
    the old code this was `unparseable_present`, which told the manager to OPEN AND
    READ IT (RECOVERABLE) — advice that hands them a different seat's context and
    calls the reap recovered.
    """
    disk = _Disk( { _slot( "sam" ): _memento( "Sam", _PRIOR_SID[ :8 ] ) } )
    out  = _coord( { "cc-author-sam-1": _ident( "Sam", _SAM_SID ) }, disk )
    seat = out[ "cc-author-sam-1" ]

    assert seat[ "status" ] == "prior_holder_present"
    assert seat[ "status" ] != "unparseable_present"
    # The verdict must NAME the other seat — "somebody else's" without a session id
    # still forces the manual check this row exists to remove.
    assert _PRIOR_SID[ :8 ] in seat[ "reason" ]
    # And it must not send the manager to read it as if it were theirs.
    assert "OPEN AND READ IT" not in seat[ "reason" ]


def test_genuinely_unparseable_file_still_reads_unparseable_present():
    """
    THE OVER-REACH GUARD. A present file with NO parseable header — a hand-written
    memento, a markdown H1 and nothing else — is still the recoverable open-and-read
    case. If the new verdict swallowed this, the split would have replaced one
    over-broad bucket with another.
    """
    disk = _Disk( { _slot( "sam" ): "# Memento\n" + ( "x" * 1200 ) } )
    out  = _coord( { "cc-author-sam-1": _ident( "Sam", _SAM_SID ) }, disk )

    assert out[ "cc-author-sam-1" ][ "status" ] == "unparseable_present"


def test_the_seats_own_stale_memento_is_not_a_prior_holder():
    """
    THE RACE CASE, which must be left exactly where it was. extra 1's file was HIS,
    header session matching, just outside the freshness window at check time. That is
    the recoverable open-and-read case and it must not be relabelled as somebody
    else's file — the two verdicts would swap meanings and nothing would improve.
    """
    stale = _memento( "Sam", _SAM_SID[ :8 ], written_at="2026-08-17T12:00:00+00:00" )
    disk  = _Disk( { _slot( "sam" ): stale } )
    out   = _coord( { "cc-author-sam-1": _ident( "Sam", _SAM_SID ) }, disk )

    assert out[ "cc-author-sam-1" ][ "status" ] == "unparseable_present"


def test_nothing_at_the_slot_is_still_absent_not_a_prior_holder():
    """An empty slot has no owner to name — it stays the unrecoverable verdict."""
    out = _coord( { "cc-author-sam-1": _ident( "Sam", _SAM_SID ) }, _Disk() )

    assert out[ "cc-author-sam-1" ][ "status" ] == "timeout_no_memento"


# ── classify_slot_owner, directly ─────────────────────────────────────────────
def test_classify_slot_owner_names_the_other_seat():
    disk = _Disk( { _slot( "sam" ): _memento( "Sam", _PRIOR_SID[ :8 ] ) } )
    assert reap_memento.classify_slot_owner( _slot( "sam" ), _SAM_SID[ :8 ], disk.read ) == _PRIOR_SID[ :8 ]


def test_classify_slot_owner_is_silent_when_the_file_is_this_seats():
    disk = _Disk( { _slot( "sam" ): _memento( "Sam", _SAM_SID[ :8 ] ) } )
    assert reap_memento.classify_slot_owner( _slot( "sam" ), _SAM_SID[ :8 ], disk.read ) is None


def test_classify_slot_owner_follows_a_pointer_to_the_record():
    """
    john's shape. The slot is a POINTER; the header that matters is the RECORD's.
    Reading the pointer's own bytes would answer about the wrong file — the same
    mistake `verify_seat_memento` documents itself avoiding, so the two must agree.
    """
    record = f"{_REPO}/io/mementos/john-3619a192.md"
    disk   = _Disk( {
        _slot( "john" ): ( "<!-- MEMENTO POINTER — NOT THE RECORD. -->\n"
                          "<!-- current: io/mementos/john-3619a192.md -->\n" ),
        record         : _memento( "John", "3619a192" ),
    } )
    assert reap_memento.classify_slot_owner( _slot( "john" ), "0766748d", disk.read ) == "3619a192"


def test_classify_slot_owner_is_silent_when_the_pointers_record_is_gone():
    disk = _Disk( { _slot( "john" ): ( "<!-- MEMENTO POINTER — NOT THE RECORD. -->\n"
                          "<!-- current: io/mementos/john-3619a192.md -->\n" ) } )
    assert reap_memento.classify_slot_owner( _slot( "john" ), "0766748d", disk.read ) is None


def test_classify_slot_owner_is_silent_on_an_unreadable_slot():
    assert reap_memento.classify_slot_owner( _slot( "sam" ), _SAM_SID[ :8 ], _Disk().read ) is None


def test_classify_slot_owner_is_silent_without_a_parseable_header():
    disk = _Disk( { _slot( "sam" ): "# Memento\nno header here\n" } )
    assert reap_memento.classify_slot_owner( _slot( "sam" ), _SAM_SID[ :8 ], disk.read ) is None


def test_classify_slot_owner_is_silent_when_the_seat_id_is_unknown():
    """
    Refuse to accuse when there is nothing to compare against. An unknown seat id
    would otherwise make EVERY slot look foreign.
    """
    disk = _Disk( { _slot( "sam" ): _memento( "Sam", _PRIOR_SID[ :8 ] ) } )
    assert reap_memento.classify_slot_owner( _slot( "sam" ), "", disk.read ) is None
    assert reap_memento.classify_slot_owner( _slot( "sam" ), None, disk.read ) is None


def test_classify_slot_owner_folds_case_before_comparing():
    """
    An uppercase-hex seat id must not read as a different seat. `verify_seat_memento`
    already case-folds for exactly this reason; a raw compare here would manufacture
    a prior-holder accusation out of letter case.
    """
    disk = _Disk( { _slot( "sam" ): _memento( "Sam", "4fa58ddc" ) } )
    assert reap_memento.classify_slot_owner( _slot( "sam" ), "4FA58DDC", disk.read ) is None


def test_classify_slot_owner_is_silent_when_the_header_carries_no_session_id():
    disk = _Disk( { _slot( "sam" ): "<!-- memento-record: persona=Sam slot=io -->\n" + ( "x" * 1200 ) } )
    assert reap_memento.classify_slot_owner( _slot( "sam" ), _SAM_SID[ :8 ], disk.read ) is None


# ── memento_alarm ─────────────────────────────────────────────────────────────
def test_alarm_is_silent_when_every_seat_is_covered():
    """
    The quiet case must stay quiet. An alarm that fires on a clean reap is an alarm
    managers learn to skip, which is the same failure this row is about.
    """
    outcomes = {
        "cc-a": { "status": "verified", "persona": "Sam"  },
        "cc-b": { "status": "written",  "persona": "John" },
        "cc-c": { "status": "not_requested" },
    }
    assert reap_memento.memento_alarm( outcomes ) is None


@pytest.mark.parametrize( "losing_status", [
    "timeout_no_memento", "prior_holder_present", "unparseable_present",
    "skipped", "skipped_no_cwd",
] )
def test_alarm_fires_for_every_losing_verdict( losing_status ):
    """
    Each of these means the seat is about to die with no PROVEN memento. Any one of
    them omitted here is a seat that dies quietly.
    """
    line = reap_memento.memento_alarm( { "cc-a": { "status": losing_status, "persona": "Sam" } } )

    assert line is not None
    assert "cc-a" in line and "Sam" in line and losing_status in line


def test_alarm_names_every_losing_seat_and_counts_them():
    outcomes = {
        "cc-b": { "status": "prior_holder_present", "persona": "Sam"  },
        "cc-a": { "status": "verified",             "persona": "Rio"  },
        "cc-c": { "status": "timeout_no_memento",   "persona": "John" },
    }
    line = reap_memento.memento_alarm( outcomes )

    assert "2 seat(s)" in line
    assert "cc-b" in line and "cc-c" in line
    assert "cc-a" not in line                       # the covered seat is not accused
    assert line.index( "cc-b" ) < line.index( "cc-c" )   # sorted, so two reads agree


def test_alarm_tolerates_the_coordination_error_key_and_junk():
    """
    `_error` is a coordination failure, not a seat, and the caller writes it into the
    same dict. Treating it as a seat would print a nonsense name in the loud line.
    """
    outcomes = {
        "_error": "memento coordination raised RuntimeError",
        "cc-a"  : None,
        "cc-b"  : { "status": "timeout_no_memento", "persona": "Sam" },
    }
    line = reap_memento.memento_alarm( outcomes )

    assert "1 seat(s)" in line
    assert "_error" not in line


def test_alarm_falls_back_when_the_persona_is_missing():
    line = reap_memento.memento_alarm( { "cc-a": { "status": "skipped" } } )
    assert "unknown persona" in line


# ── The line reaches the TOP of the reap result ───────────────────────────────
def _reap_with_outcomes( outcomes, tmp_path ):
    """Drive dismiss_sessions with the memento coordinator stubbed to `outcomes`."""
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    return ss.dismiss_sessions(
        "mgr-session", session_names=[ "cc-author-sam-1" ],
        runner=lambda *a, **k: type( "R", (), { "returncode": 0, "stdout": "", "stderr": "" } )(),
        session_dir=session_dir,
        write_memento=True,
        memento_coord_fn=lambda identities: outcomes,
        emit_reap_fn=lambda ident, reason="": None,
        emit_reaped_fn=lambda ident: None,
    )


def test_reap_result_carries_the_alarm_at_the_top_level( tmp_path ):
    """
    THE SECOND DEFECT of the row: the verdict was honest and nested, so it was missed.
    It must be a top-level key on the result the manager actually reads.
    """
    res = _reap_with_outcomes(
        { "cc-author-sam-1": { "status": "prior_holder_present", "persona": "Sam" } }, tmp_path )

    assert res[ "memento_alarm" ] is not None
    assert "cc-author-sam-1" in res[ "memento_alarm" ]


def test_reap_result_alarm_is_none_on_a_clean_reap( tmp_path ):
    res = _reap_with_outcomes(
        { "cc-author-sam-1": { "status": "verified", "persona": "Sam" } }, tmp_path )

    assert res[ "memento_alarm" ] is None


# ── describe_slot / format_slot_report: the one command a manager runs ────────
def _describe( disk, sid, persona="Sam" ):
    return reap_memento.describe_slot( _REPO, persona, sid[ :8 ], _NOW, read_text_fn=disk.read )


def test_describe_slot_says_ready_only_when_the_slot_resolves_to_this_seat():
    disk   = _Disk( { _slot( "sam" ): _memento( "Sam", _SAM_SID[ :8 ] ) } )
    report = _describe( disk, _SAM_SID )

    assert report[ "verdict" ] == "ready"
    assert report[ "foreign_session_id" ] is None
    assert report[ "slot" ] == _slot( "sam" )


def test_describe_slot_catches_johns_shape_a_true_receipt_at_the_wrong_place():
    """
    john's live case, which this row caught BEFORE the reap: his memento was real,
    current and his — and in the repo root, while the slot resolved to a four-hour-old
    holder. Every element of his receipt was true. The slot is the only thing that
    answers the question, so this must report the OTHER session, not "ready".
    """
    disk   = _Disk( { _slot( "sam" ): _memento( "Sam", _PRIOR_SID[ :8 ] ) } )
    report = _describe( disk, _SAM_SID )

    assert report[ "verdict" ] == "prior_holder"
    assert report[ "foreign_session_id" ] == _PRIOR_SID[ :8 ]


def test_describe_slot_reports_an_empty_slot_as_absent():
    assert _describe( _Disk(), _SAM_SID )[ "verdict" ] == "absent"


def test_describe_slot_separates_the_race_from_the_wrong_owner():
    """
    A file that is not another session's but cannot be proven — the mid-write race.
    Re-running seconds later is the right advice; hunting for a misplaced file is not.
    """
    disk   = _Disk( { _slot( "sam" ): "# Memento\n" + ( "x" * 1200 ) } )
    report = _describe( disk, _SAM_SID )

    assert report[ "verdict" ] == "present_unproven"
    assert report[ "foreign_session_id" ] is None


def test_describe_slot_uses_the_same_predicate_as_the_reap():
    """
    If this command and the reap could disagree, the command would be worse than
    nothing — a manager would gate on a green it does not share. A stale memento is
    refused by the reap, so it must be refused here too.
    """
    stale = _memento( "Sam", _SAM_SID[ :8 ], written_at="2026-08-17T12:00:00+00:00" )
    disk  = _Disk( { _slot( "sam" ): stale } )

    assert _describe( disk, _SAM_SID )[ "verdict" ] != "ready"


@pytest.mark.parametrize( "verdict,expected_head", [
    ( "ready",            "READY"                 ),
    ( "prior_holder",     "NOT AT THE SLOT"       ),
    ( "absent",           "NOTHING AT THE SLOT"   ),
    ( "present_unproven", "PRESENT BUT UNPROVEN"  ),
] )
def test_format_slot_report_leads_with_the_verdict_and_always_names_the_slot( verdict, expected_head ):
    report = { "slot": _slot( "sam" ), "verdict": verdict, "detail": "why",
               "foreign_session_id": _PRIOR_SID[ :8 ] }
    text   = reap_memento.format_slot_report( report, "Sam", _SAM_SID[ :8 ] )

    assert text.startswith( expected_head )
    assert _slot( "sam" ) in text          # the slot is the answer; it appears every time


def test_format_slot_report_names_the_other_session_on_the_prior_holder_line():
    report = { "slot": _slot( "sam" ), "verdict": "prior_holder", "detail": "why",
               "foreign_session_id": _PRIOR_SID[ :8 ] }
    text   = reap_memento.format_slot_report( report, "Sam", _SAM_SID[ :8 ] )

    assert _PRIOR_SID[ :8 ] in text
    assert "repo root" in text             # names the usual wrong place to look
