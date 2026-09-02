"""
Unit tests for the self_respin() verb core (WI-2 of row 9e0678f6).

Target: 100% lines + branches + functions on lupin_mcp/self_respin_core.py

The gates these tests enforce (Krishna + Cheech, standing):
  · a real human "no"/"neither" schedules NOTHING;
  · the confirmation ask is UNSKIPPABLE — no kwarg reaches the schedule without it;
  · the one-shot is rm'd INSIDE the injected command at the fire point;
  · wrap=False is proven at the CALL SITE — the argv carries verbatim "/clear",
    never a speakerphone-wrapped blob;
  · the memento is proven complete + fresh-this-cycle (nonce + ts window), not
    merely present — else the verb aborts rather than clearing into nothing.

Every side-effecting seam is injected, so no live tmux / MCP / subprocess runs.
"""

import datetime
import json
import os

import pytest

import lupin_mcp.self_respin_core as sr
from lupin_mcp.persona_normalization import persona_slug


UTC = datetime.timezone.utc


def _dt( minute, second=0 ):
    return datetime.datetime( 2026, 8, 14, 2, minute, second, tzinfo=UTC )


# ---------------------------------------------------------------------------
# gate_proceed — the confirmation-gate decision
# ---------------------------------------------------------------------------
def test_gate_default_used_proceeds():
    ok, _ = sr.gate_proceed( f"{sr.DEFAULT_USED_MARKER}yes" )
    assert ok is True


def test_gate_default_used_proceeds_even_if_value_is_no():
    """offline/timeout substitutes the default; that default is 'yes' → PROCEED,
    regardless of the substituted token's face value."""
    ok, _ = sr.gate_proceed( f"{sr.DEFAULT_USED_MARKER}no" )
    assert ok is True


def test_gate_real_yes_proceeds():
    assert sr.gate_proceed( "yes" )[ 0 ] is True


def test_gate_real_yes_with_comment_proceeds():
    assert sr.gate_proceed( "yes [comment: go for it]" )[ 0 ] is True


def test_gate_real_no_aborts():
    ok, reason = sr.gate_proceed( "no" )
    assert ok is False
    assert "declined" in reason


def test_gate_neither_aborts():
    assert sr.gate_proceed( "neither [comment: reframe]" )[ 0 ] is False


def test_gate_non_string_aborts_fail_safe():
    assert sr.gate_proceed( None )[ 0 ] is False


# ---------------------------------------------------------------------------
# build_nonce_line + verify_memento_content — the option-(b) freshness proof
# ---------------------------------------------------------------------------
# A body over the substance floor (row 4cf9f9fd) — these tests are about FRESHNESS,
# so they must not trip the nonce-only gate on their way to the assertion they mean.
_REAL_BODY = ( "board state: row 4cf9f9fd in progress, manager mr radio, "
               "venue :8000 idle, next act is the containment probe.\n" ) * 5


def _memento_with_nonce( uuid, ts, extra=_REAL_BODY ):
    return f"# memento\n{extra}{sr.build_nonce_line( uuid, ts )}\n"


def test_build_nonce_line_shape():
    line = sr.build_nonce_line( "abc-123", _dt( 20 ) )
    assert line == "SELF-RESPIN-NONCE: abc-123 @ 2026-08-14T02:20:00+00:00"


def test_verify_ok_when_nonce_present_and_fresh():
    content = _memento_with_nonce( "u1", _dt( 20 ) )
    ok, _ = sr.verify_memento_content( content, "u1", _dt( 21 ), cycle_window_seconds=300 )
    assert ok is True


def test_verify_fails_on_empty_memento():
    ok, reason = sr.verify_memento_content( "   ", "u1", _dt( 21 ) )
    assert ok is False
    assert "empty" in reason


def test_verify_fails_on_none_content():
    assert sr.verify_memento_content( None, "u1", _dt( 21 ) )[ 0 ] is False


def test_verify_fails_when_nonce_uuid_blank():
    content = _memento_with_nonce( "u1", _dt( 20 ) )
    assert sr.verify_memento_content( content, "", _dt( 21 ) )[ 0 ] is False


def test_verify_fails_when_nonce_absent():
    """A stale body carries an OLD uuid — this cycle's uuid is simply not there."""
    content = _memento_with_nonce( "old-uuid", _dt( 20 ) )
    ok, reason = sr.verify_memento_content( content, "this-cycle-uuid", _dt( 21 ) )
    assert ok is False
    assert "not found" in reason


def test_verify_fails_when_nonce_ts_naive():
    content = f"{sr.NONCE_LINE_PREFIX} u1 @ 2026-08-14T02:20:00\n"   # no offset
    assert sr.verify_memento_content( content, "u1", _dt( 21 ) )[ 0 ] is False


def test_verify_fails_when_nonce_ts_stale():
    """Right uuid, but stamped 8 days ago → outside the cycle window → abort."""
    old  = datetime.datetime( 2026, 8, 6, 2, 20, 0, tzinfo=UTC )
    content = _memento_with_nonce( "u1", old )
    ok, reason = sr.verify_memento_content( content, "u1", _dt( 21 ), cycle_window_seconds=300 )
    assert ok is False
    assert "stale" in reason


def test_verify_rejects_future_dated_nonce():
    """A stamp in the FUTURE (corrupt/forged) must not pass (Krishna nit 1)."""
    content = _memento_with_nonce( "u1", _dt( 30 ) )   # stamped at 02:30
    ok, reason = sr.verify_memento_content( content, "u1", _dt( 21 ), cycle_window_seconds=300 )  # now 02:21
    assert ok is False
    assert "future" in reason


# ---------------------------------------------------------------------------
# build_guarded_clear_argv — the fire-point one-shot + verbatim /clear
# ---------------------------------------------------------------------------
def test_guarded_argv_consumes_token_before_send_keys():
    argv = sr.build_guarded_clear_argv( "sess", "/data/.fire.token", 20 )
    script = argv[ 2 ]
    assert 'rm "$4"' in script
    assert script.index( 'rm "$4"' ) < script.index( "send-keys" )   # consume BEFORE typing


def test_guarded_argv_carries_verbatim_clear_and_token():
    argv = sr.build_guarded_clear_argv( "sess", "/data/.fire.token", 20 )
    assert argv[ 6 ] == "/clear"                 # $3 verbatim slash command
    assert argv[ 7 ] == "/data/.fire.token"      # $4 the one-shot
    # no speakerphone wrapper text anywhere in the argv
    assert not any( "system-reminder" in part for part in argv )


# ---------------------------------------------------------------------------
# build_wake_text + build_guarded_clear_argv WAKE path (row 275cb0b9, GAP 1)
# ---------------------------------------------------------------------------
def test_build_wake_text_names_memento_and_is_plain_english():
    txt = sr.build_wake_text( "/data/lupin/.claude-memento.md", "nonce-7", "/data/.wake-proof.marker" )
    assert "/data/lupin/.claude-memento.md" in txt
    assert "rehydrated" in txt.lower()
    assert "memento" in txt.lower()
    assert "resume" in txt.lower()
    # consumer-proof instruction: the seat must write the nonce-echoing proof line
    assert "/data/.wake-proof.marker" in txt                       # names the proof artifact
    assert f"{sr._WAKE_PROOF_NONCE_LINE} nonce-7" in txt           # the exact line to echo
    assert "\n" not in txt                                         # single line (send-keys -l + one Enter)


def test_build_wake_text_asks_instead_of_asserting_the_rehydrate():
    """
    Bug e88ebfae. The wake is composed from the SCHEDULING artifact, so it can prove a
    clear was scheduled and its token consumed — never that the pane actually reset.
    It must therefore leave the verdict to the seat, and must not tell it in the second
    person that it rehydrated at low context.
    """
    txt = sr.build_wake_text( "/m/memento.md", "nonce-7", "/p/proof.marker" ).lower()

    # The exact false claims the disputed run received are gone.
    assert "you just self-re-spun" not in txt
    assert "you typed /clear into your own pane" not in txt
    assert "rehydrated as the same seat at low context" not in txt

    # Both branches are named, and each says what to write.
    assert "if yours differs" in txt
    assert "if yours is the same" in txt


def test_the_wake_never_asks_the_seat_what_it_remembers():
    """
    🔴 THE INSTRUMENT THE WAKE HANDS THE SEAT MUST NOT BE ITS OWN MEMORY (2026-09-02).

    The e88ebfae fix stopped the wake ASSERTING the rehydrate and made it ask "do you
    remember the work of this session". That question CANNOT return the right answer,
    and the reason is structural rather than bad luck: it detects a MISSING memory and
    cannot detect a RESTORED one. A seat that cleared and then re-read its own record
    has no absence to find, so it answers "I remember" — confidently, and wrongly.

    Measured twice, on the SAME seat, one day apart (2026-09-01 and 2026-09-02). The
    second time the seat had READ that limit, QUOTED it in its own dispute file, and
    still ruled the wrong way. Transcripts settled it: the session chain
    611e3c47 -> 00249b1e -> 4bc5167d, an empty `local-command-stdout` at 21:13:15.828
    which is the /clear signature, and the wake nonce three times in the POST-clear
    transcript against zero in the pre-clear one. The clear had landed.

    ⇒ So the question is removed rather than reworded. Knowing a rule is not applying
    it, and an instrument that needs the reader to remember its own limit is not an
    instrument. What replaces it is a COMPARISON against an artifact the seat cannot
    author — see the test below.
    """
    txt = sr.build_wake_text( "/m/memento.md", "nonce-7", "/p/proof.marker" ).lower()
    for banned in ( "do you remember", "remember the work", "is your context near-empty",
                    "first you have seen of it" ):
        assert banned not in txt, f"the wake still asks the seat to introspect: {banned!r}"


def test_the_wake_hands_the_seat_an_oracle_it_cannot_author():
    """
    The replacement instrument: the wake quotes the session id the pane carried
    IMMEDIATELY BEFORE the clear, and tells the seat to compare it against its own
    `claude_code.session_id`. Both sides come from the bridge, which is written by the
    SessionStart hook — a different actor from the seat, so the seat cannot move either
    side of the comparison to suit its belief.

    The id is unknowable when the text is composed (the clear has not been sent yet), so
    the composer emits a sentinel and the detached chain substitutes the value it
    captured at fire time. This test pins the sentinel's presence; the EXECUTION test in
    test_self_respin_wake_gate_exec.py proves the substitution actually happens.
    """
    txt = sr.build_wake_text( "/m/memento.md", "nonce-7", "/p/proof.marker" )
    assert sr._PRE_CLEAR_SID_SENTINEL in txt, \
        "the wake must carry the pre-clear-session-id sentinel for the chain to substitute"
    assert "get_session_info" in txt
    assert "claude_code.session_id" in txt
    # and it must degrade rather than hand the seat an empty string that reads like an answer
    assert sr._PRE_CLEAR_SID_UNAVAILABLE in txt


def test_build_wake_text_routes_a_disputed_wake_to_a_file_not_a_proof():
    """A seat that did NOT rehydrate must be told to write a dispute, never a proof —
    a proof marker is a receipt, and the observer keys RETURNED on it."""
    txt = sr.build_wake_text( "/m/memento.md", "nonce-7", "/p/proof.marker" )
    assert sr._DISPUTE_PREFIX in txt
    assert "write NO proof" in txt
    assert "tell your manager" in txt.lower()


def test_guarded_argv_wake_path_appends_wake_bridge_and_poll_args():
    argv = sr.build_guarded_clear_argv(
        "sess", "/data/.fire.token", 20,
        wake_text="READ YOUR MEMENTO", bridge_path="/s/cc-42.json",
        ready_timeout_polls=7, poll_interval_seconds=0.5,
    )
    # $1-$4 unchanged (existing index contract preserved), $5-$8 appended
    assert argv[ 6 ] == "/clear"
    assert argv[ 7 ] == "/data/.fire.token"
    assert argv[ 8 ] == "READ YOUR MEMENTO"      # $5 wake, typed -l
    assert argv[ 9 ] == "/s/cc-42.json"          # $6 bridge (readiness oracle)
    assert argv[ 10 ] == "7"                     # $7 bounded poll count
    assert argv[ 11 ] == "0.5"                   # $8 poll interval


def test_guarded_argv_wake_path_gates_on_bridge_session_id_not_send_keys_exit():
    """Ruling 1: readiness is the bridge's own report of a NEW session, never a
    send-keys exit code; ruling 3: ONE chain; ruling 4: literal wake keystroke."""
    script = sr.build_guarded_clear_argv(
        "sess", "/f.token", 20, wake_text="WAKE", bridge_path="/s/cc-42.json" )[ 2 ]
    assert '"session_id"' in script                  # the bridge's session_id is the oracle
    assert '[ "$s" != "$s0" ]' in script             # value-change compare
    assert 'rm "$4" || exit 0' in script             # one-shot guard preserved
    assert 'send-keys -t "$2" -l -- "$w"' in script  # literal (-l) wake keystroke
    assert "exit 3" in script                        # loud, bounded give-up on timeout
    # the wake is typed AFTER the readiness gate, never before it. `$w` is `$5` with the
    # fire-time session id substituted in — the wake is no longer typed verbatim.
    assert script.index( 's0=$(' ) < script.index( '-l -- "$w"' )


def test_wake_gate_does_not_key_on_mtime():
    """
    Bug e88ebfae, the root cause. `touch_bridge_mtime()` runs from the PostToolUse hook
    on EVERY tool call of EVERY session (session_bridge.py REDLINE C1 — a bare
    os.utime with no content write). A gate that polls the mtime therefore cannot tell
    'the seat made a tool call' from 'the seat rehydrated', and on a busy seat — the
    very seat whose /clear is buffered — it opens on the seat's own next tool call.
    """
    script = sr.build_guarded_clear_argv(
        "sess", "/f.token", 20, wake_text="WAKE", bridge_path="/s/cc-42.json" )[ 2 ]
    assert "date -r" not in script, "mtime must not be the readiness oracle"
    assert "%s%N" not in script


def test_wake_gate_ignores_the_stable_session_id_line():
    """
    `"stable_session_id"` CONTAINS `"session_id"` as a substring, and it is the one
    field that does NOT change across a clear. Matching it would make the gate compare
    a constant to itself and never open. The pattern anchors past json.dump's indent.
    """
    script = sr.build_guarded_clear_argv(
        "sess", "/f.token", 20, wake_text="WAKE", bridge_path="/s/cc-42.json" )[ 2 ]
    assert '^ *"session_id"' in script


def test_wake_gate_treats_an_unreadable_bridge_as_not_ready():
    """An empty read must never count as a change — the failure direction is
    mute-and-alarm, never wake-into-the-old-context."""
    script = sr.build_guarded_clear_argv(
        "sess", "/f.token", 20, wake_text="WAKE", bridge_path="/s/cc-42.json" )[ 2 ]
    assert '[ -n "$s" ]' in script


# ---------------------------------------------------------------------------
# perform_self_respin — over-budget grounds gate (row 275cb0b9, ruling 2)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize( "status", [ "within_budget", "unknown", "idle", None ] )
def test_perform_aborts_when_not_over_budget( tmp_path, status ):
    """No proven over_budget reading ⇒ no grounds to clear ⇒ abort. Covers the exact
    GAP-3 systemic case (status 'unknown' from a failed pressure fetch)."""
    mp    = _write_memento( tmp_path, "u1", _dt( 20 ) )
    ask   = _Spy()
    sched = _Spy()
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status=status, pre_clear_pct=None,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=ask, schedule_fn=sched,
        base_dir=str( tmp_path ), repo_root=str( tmp_path ),
    )
    assert r.status == "aborted"
    assert "no grounds to clear" in r.reason
    assert ask.calls   == 0                                        # never asked
    assert sched.calls == 0                                        # never scheduled
    assert list( tmp_path.glob( ".self-respin-*" ) ) == []        # no marker/token written


# ---------------------------------------------------------------------------
# perform_self_respin — the WAKE go-path (row 275cb0b9, GAP 1)
# ---------------------------------------------------------------------------
def test_perform_schedules_wake_argv_when_bridge_resolves( tmp_path ):
    mp        = _write_memento( tmp_path, "u1", _dt( 20 ) )
    scheduled = []
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=lambda: "yes",
        wake_nonce="wn-1", resolve_bridge_path_fn=lambda sid: "/s/cc-42.json",
        schedule_fn=lambda argv: scheduled.append( argv ), base_dir=str( tmp_path ), repo_root=str( tmp_path ),
    )
    assert r.status == "scheduled"
    argv = scheduled[ 0 ]
    # argv[8] is the FULL built wake text — it carries the proof instruction + nonce
    assert f"{sr._WAKE_PROOF_NONCE_LINE} wn-1" in argv[ 8 ]        # wake rode the SAME chain, nonce-bound
    assert argv[ 9 ] == "/s/cc-42.json"           # gated on this bridge's mtime
    # the marker records the wake_nonce the seat must echo; a stale proof was pre-removed
    marker = json.loads( ( tmp_path / ".self-respin-sid1.json" ).read_text() )
    assert marker[ "wake_nonce" ] == "wn-1"


def test_perform_falls_back_to_plain_clear_when_bridge_unresolvable( tmp_path ):
    """A wake was requested but the bridge path can't be resolved → schedule the
    plain clear anyway (never block the re-spin on an un-resolvable wake)."""
    mp        = _write_memento( tmp_path, "u1", _dt( 20 ) )
    scheduled = []
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=lambda: "yes",
        wake_nonce="wn-1", resolve_bridge_path_fn=lambda sid: None,
        schedule_fn=lambda argv: scheduled.append( argv ), base_dir=str( tmp_path ), repo_root=str( tmp_path ),
    )
    assert r.status == "scheduled"
    argv = scheduled[ 0 ]
    assert len( argv ) == 9                        # plain single-chain argv, no wake args
    assert argv[ 6 ] == "/clear"
    # $5 is the send stamp (row 855e4dd0) — present on the PLAIN chain too, because the
    # deadline it anchors has nothing to do with whether a wake was scheduled.
    assert argv[ 8 ].endswith( "/.self-respin-keys-sent-sid1.marker" )
    # ...and the WAKE args are what is still absent: no bridge path, no proof path.
    assert not any( "self-respin-wake-proof" in a for a in argv )
    # no wake ⇒ no wake_nonce requirement recorded in the marker
    marker = json.loads( ( tmp_path / ".self-respin-sid1.json" ).read_text() )
    assert marker[ "wake_nonce" ] is None


# ---------------------------------------------------------------------------
# perform_self_respin — the full ordered decision tree
# ---------------------------------------------------------------------------
class _Spy:
    def __init__( self, ret="yes" ):
        self.calls = 0
        self.ret   = ret
    def __call__( self, *a, **k ):
        self.calls += 1
        return self.ret


def _seat( tmux="cheech-mgr" ):
    return lambda sid: tmux


# The go-path memento must now satisfy the SLOT check too (row 8068c65e), so this
# helper writes the shape memento_io actually produces at `--slot root`: an immutable
# RECORD carrying the machine-readable header, plus the mutable POINTER beside it
# holding a copy of the record's bytes behind `current:`. The nonce is stamped into
# the POINTER, which is the file self_respin is handed and rehydrates from.
_SEAT_PERSONA = "cheech"
_SEAT_SID     = "sid1"


def _write_memento( tmp_path, uuid, ts, *, persona=_SEAT_PERSONA, sid=_SEAT_SID, written_at=None ):
    """Write a real root-slot record+pointer pair under tmp_path; return the pointer path."""
    stamp  = ( written_at if written_at is not None else ts ).isoformat()
    slug   = persona_slug( persona )
    record = tmp_path / f".claude-memento-{slug}-{sid[ :8 ].lower()}.md"
    header = f"<!-- memento-record: persona={slug} session_id={sid[ :8 ].lower()} written_at={stamp} slot=root -->\n"
    body   = header + "# memento\n" + _REAL_BODY * 4
    record.write_text( body )

    pointer = tmp_path / ".claude-memento.md"
    pointer.write_text(
        "<!-- MEMENTO POINTER — NOT THE RECORD. Safe to overwrite; it destroys nothing. -->\n"
        f"<!-- current: {record.name} -->\n"
        + body + "\n" + sr.build_nonce_line( uuid, ts ) + "\n"
    )
    return str( pointer )


def test_perform_aborts_when_no_tmux():
    ask = _Spy()
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path="/nope", memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=lambda sid: None, ask_fn=ask,
        schedule_fn=_Spy(), base_dir="/tmp",
    )
    assert r.status == "aborted"
    assert ask.calls == 0   # never asked — no seat to clear


def test_perform_aborts_on_bad_memento_without_asking( tmp_path ):
    """Memento verify runs BEFORE the ask; a stale memento aborts and never asks."""
    mp  = _write_memento( tmp_path, "old", _dt( 20 ) )
    ask = _Spy()
    sched = _Spy()
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="this-cycle",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=ask, schedule_fn=sched,
        base_dir=str( tmp_path ), repo_root=str( tmp_path ),
    )
    assert r.status == "aborted"
    assert ask.calls   == 0
    assert sched.calls == 0


def test_perform_declines_on_human_no_schedules_nothing( tmp_path ):
    mp    = _write_memento( tmp_path, "u1", _dt( 20 ) )
    sched = _Spy()
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=lambda: "no", schedule_fn=sched,
        base_dir=str( tmp_path ), repo_root=str( tmp_path ),
    )
    assert r.status == "declined"
    assert sched.calls == 0
    # and no marker/token were written on a decline
    assert list( tmp_path.glob( ".self-respin-*" ) ) == []


def test_perform_scheduled_happy_path_writes_marker_and_token( tmp_path ):
    mp        = _write_memento( tmp_path, "u1", _dt( 20 ) )
    scheduled = []
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat( "cheech-mgr" ), ask_fn=lambda: "yes",
        schedule_fn=lambda argv: scheduled.append( argv ), base_dir=str( tmp_path ), repo_root=str( tmp_path ),
    )
    assert r.status == "scheduled"
    # observer marker persists (it is NOT the file the injector rm's)
    marker = tmp_path / ".self-respin-sid1.json"
    assert marker.exists()
    assert json.loads( marker.read_text() )[ "pre_clear_status" ] == "over_budget"
    # fire token written separately
    assert ( tmp_path / ".self-respin-fire-sid1.token" ).exists()
    # scheduled argv carries verbatim /clear + the fire token, and rm's it first
    argv = scheduled[ 0 ]
    assert argv[ 6 ] == "/clear"
    assert argv[ 7 ] == str( tmp_path / ".self-respin-fire-sid1.token" )


def test_perform_proceeds_on_offline_default_used( tmp_path ):
    mp        = _write_memento( tmp_path, "u1", _dt( 20 ) )
    scheduled = []
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=lambda: f"{sr.DEFAULT_USED_MARKER}yes",
        schedule_fn=lambda argv: scheduled.append( argv ), base_dir=str( tmp_path ), repo_root=str( tmp_path ),
    )
    assert r.status == "scheduled"
    assert len( scheduled ) == 1


def test_perform_aborts_when_marker_readback_fails( tmp_path ):
    """If the marker cannot be read back durable, we refuse to clear (no record)."""
    mp    = _write_memento( tmp_path, "u1", _dt( 20 ) )
    sched = _Spy()
    # write_json that silently drops the marker → read-back finds nothing
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=lambda: "yes", schedule_fn=sched,
        base_dir=str( tmp_path ), repo_root=str( tmp_path ), write_json_fn=lambda path, data: None,
    )
    assert r.status == "aborted"
    assert sched.calls == 0


def test_perform_aborts_when_fire_token_readback_fails_and_removes_marker( tmp_path ):
    """The marker writes durably but the fire token does not (Krishna nit 2): the
    verb must abort AND remove the marker so it can't raise a false DEAD alarm."""
    mp    = _write_memento( tmp_path, "u1", _dt( 20 ) )
    sched = _Spy()

    def selective_write( path, data ):
        # key on the BASENAME — the pytest tmp dir name itself contains "fire"
        if os.path.basename( path ).startswith( sr.FIRE_TOKEN_PREFIX ):
            return                       # silently drop the fire token
        with open( path, "w" ) as f:     # write the marker durably
            json.dump( data, f )

    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=lambda: "yes", schedule_fn=sched,
        base_dir=str( tmp_path ), repo_root=str( tmp_path ), write_json_fn=selective_write,
    )
    assert r.status == "aborted"
    assert sched.calls == 0
    assert not ( tmp_path / ".self-respin-sid1.json" ).exists()   # marker cleaned up


def test_best_effort_remove_swallows_missing_file( tmp_path ):
    sr._best_effort_remove( str( tmp_path / "nope" ) )            # must not raise


def test_perform_honors_grace_seconds_in_deadline( tmp_path ):
    mp = _write_memento( tmp_path, "u1", _dt( 20 ) )
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 20 ), delay_seconds=20, grace_seconds=100,
        resolve_tmux_fn=_seat(), ask_fn=lambda: "yes",
        schedule_fn=lambda argv: None, base_dir=str( tmp_path ), repo_root=str( tmp_path ),
    )
    # deadline = fired 02:20:00 + 20 + 100 = 02:22:00
    assert r.expected_return_by == _dt( 22 ).isoformat()


# ---------------------------------------------------------------------------
# _readback_ok + _default_read_text — the small IO helpers
# ---------------------------------------------------------------------------
def test_readback_ok_true_false_and_bad_json( tmp_path ):
    p = tmp_path / ".self-respin-sid1.json"
    p.write_text( json.dumps( { "session_id": "sid1" } ) )
    assert sr._readback_ok( sr._default_read_text, str( p ), "sid1" ) is True
    assert sr._readback_ok( sr._default_read_text, str( p ), "other" ) is False
    p.write_text( "{not json" )
    assert sr._readback_ok( sr._default_read_text, str( p ), "sid1" ) is False
    assert sr._readback_ok( sr._default_read_text, str( tmp_path / "missing.json" ), "sid1" ) is False


def test_default_read_text_missing_returns_none( tmp_path ):
    assert sr._default_read_text( str( tmp_path / "nope" ) ) is None


def test_default_read_text_reads_file( tmp_path ):
    p = tmp_path / "f.txt"
    p.write_text( "hello" )
    assert sr._default_read_text( str( p ) ) == "hello"


# ---------------------------------------------------------------------------
# self_respin_from_bridge — identity from the bridge, never from the caller
# ---------------------------------------------------------------------------
def test_from_bridge_aborts_when_no_session_id():
    called = []
    r = sr.self_respin_from_bridge(
        "/m", "u1",
        identity_fn = lambda: ( None, "cheech" ),
        pressure_fn = lambda p: ( "over_budget", 61.0 ),
        perform_fn  = lambda *a, **k: called.append( ( a, k ) ),
    )
    assert r.status == "aborted"
    assert called == []   # never reaches perform — no blind clear


def test_from_bridge_passes_resolved_identity_and_pressure_to_perform():
    seen = {}
    def fake_perform( session_id, **k ):
        seen[ "session_id" ] = session_id
        seen.update( k )
        return sr.SelfRespinResult( status="scheduled", reason="ok" )

    r = sr.self_respin_from_bridge(
        "/memento", "nonce-9", delay_seconds=30, cycle_window_seconds=120,
        identity_fn = lambda: ( "sid-self", "cheech" ),
        pressure_fn = lambda persona: ( "over_budget", 62.4 ),
        perform_fn  = fake_perform,
    )
    assert r.status == "scheduled"
    assert seen[ "session_id" ]       == "sid-self"      # from the bridge, not a caller arg
    assert seen[ "persona" ]          == "cheech"
    assert seen[ "pre_clear_status" ] == "over_budget"
    assert seen[ "pre_clear_pct" ]    == 62.4
    assert seen[ "memento_path" ]     == "/memento"
    assert seen[ "memento_nonce" ]    == "nonce-9"
    assert seen[ "delay_seconds" ]    == 30
    assert seen[ "cycle_window_seconds" ] == 120


def test_from_bridge_mints_and_passes_wake_nonce():
    seen = {}
    def fake_perform( session_id, **k ):
        seen.update( k )
        return sr.SelfRespinResult( status="scheduled", reason="ok" )
    sr.self_respin_from_bridge(
        "/data/.claude-memento.md", "n1",
        identity_fn = lambda: ( "sid-self", "cheech" ),
        pressure_fn = lambda persona: ( "over_budget", 61.0 ),
        perform_fn  = fake_perform,
    )
    # from_bridge mints the consumer-proof nonce (default uuid) and hands it to perform;
    # perform builds the wake TEXT internally (proof is consumer-side, not caller-supplied)
    assert isinstance( seen[ "wake_nonce" ], str ) and seen[ "wake_nonce" ]
    assert "wake_text" not in seen                               # no longer a from_bridge arg


def test_from_bridge_uses_injected_wake_nonce_fn():
    """The nonce seam is injectable — a supplied wake_nonce_fn is used verbatim."""
    seen = {}
    def fake_perform( session_id, **k ):
        seen.update( k )
        return sr.SelfRespinResult( status="scheduled", reason="ok" )
    sr.self_respin_from_bridge(
        "/m", "n1",
        identity_fn   = lambda: ( "sid-self", "cheech" ),
        pressure_fn   = lambda persona: ( "over_budget", 61.0 ),
        wake_nonce_fn = lambda: "fixed-nonce-42",
        perform_fn    = fake_perform,
    )
    assert seen[ "wake_nonce" ] == "fixed-nonce-42"


def test_from_bridge_default_perform_fn_is_the_real_verb():
    """The default perform_fn is perform_self_respin — the seam is wired, not stubbed."""
    assert sr.self_respin_from_bridge.__defaults__ is None  # keyword-only signature
    # exercised end-to-end via the aborts-early path (no session id → no perform call)
    r = sr.self_respin_from_bridge(
        "/m", "u1",
        identity_fn = lambda: ( "", "" ),
        pressure_fn = lambda p: ( "over_budget", None ),
    )
    assert r.status == "aborted"


# ---------------------------------------------------------------------------
# resolve_identity_from_cc_meta — the pure bridge-precedence helper
# ---------------------------------------------------------------------------
def test_resolve_identity_prefers_stable_and_reads_persona_name():
    sid, persona = sr.resolve_identity_from_cc_meta(
        { "stable_session_id": "stable1", "session_id": "plain1", "voice_persona": { "name": "cheech" } },
        "FALLBACK",
    )
    assert sid == "stable1"
    assert persona == "cheech"


def test_resolve_identity_falls_back_through_plain_then_fallback_and_unknown():
    assert sr.resolve_identity_from_cc_meta( { "session_id": "plain1" }, "FB" ) == ( "plain1", "unknown" )
    assert sr.resolve_identity_from_cc_meta( {}, "FB" ) == ( "FB", "unknown" )
    # a present-but-empty voice_persona still yields "unknown"
    assert sr.resolve_identity_from_cc_meta( { "session_id": "s", "voice_persona": None }, "FB" )[ 1 ] == "unknown"


def test_resolve_own_identity_success():
    got = sr.resolve_own_identity(
        lambda: { "stable_session_id": "stable1", "voice_persona": { "name": "cheech" } }, "FB"
    )
    assert got == ( "stable1", "cheech" )


def test_resolve_own_identity_falls_back_when_metadata_raises():
    """The wrapper's old try/except lives HERE now and is tested directly:
    a raising bridge read must fall back to the SESSION_ID prefix, not crash."""
    def _boom():
        raise RuntimeError( "bridge unavailable" )
    assert sr.resolve_own_identity( _boom, "FALLBACK_SID" ) == ( "FALLBACK_SID", "unknown" )


# ---------------------------------------------------------------------------
# wrap=False is proven where it could bite: the speakerphone rider is NEVER
# applied by the scheduling path (Krishna's gate — the core builds the argv
# directly, never through inject_qualifier_via_tmux)
# ---------------------------------------------------------------------------
def test_schedule_path_never_applies_speakerphone_rider( tmp_path, monkeypatch ):
    import lupin_cli.claude_code.hooks.lib.hook_common as hook_common
    wraps = []
    monkeypatch.setattr( hook_common, "speakerphone_wrap",
                         lambda *a, **k: wraps.append( a ) or "WRAPPED!!" )

    mp        = _write_memento( tmp_path, "u1", _dt( 20 ) )
    scheduled = []
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=lambda: "yes",
        schedule_fn=lambda argv: scheduled.append( argv ), base_dir=str( tmp_path ), repo_root=str( tmp_path ),
    )
    assert r.status == "scheduled"
    assert wraps == []                              # the rider was NEVER applied
    assert scheduled[ 0 ][ 6 ] == "/clear"          # verbatim slash command, not a wrapped blob
    assert not any( "WRAPPED" in part for part in scheduled[ 0 ] )


# ---------------------------------------------------------------------------
# parse_own_pressure — the pure parse lifted out of _live_own_pressure's pragma
# (R1: the logic that held a wrong default for a day is now covered, both arms)
# ---------------------------------------------------------------------------
def test_parse_own_pressure_present_persona_returns_status_and_pct():
    section = { "personas": { "cheech": { "status": "over_budget", "consumption_pct_of_window": 61.0 } } }
    assert sr.parse_own_pressure( section, "cheech" ) == ( "over_budget", 61.0 )


def test_parse_own_pressure_absent_persona_is_UNMATCHED_not_unknown():
    """
    ⚠️ THIS TEST USED TO ASSERT `unknown`, AND THAT WAS THE DEFECT IT PINNED.
    A roster we successfully READ, which does not contain this seat, is a different
    fact from a roster we could not read at all — and returning the same answer for
    both is how a lookup that asked the wrong KEY got reported as a missing seat.
    """
    section = { "personas": { "someone_else": { "status": "within_budget" } } }
    assert sr.parse_own_pressure( section, "cheech" ) == ( sr.PRESSURE_UNMATCHED, None )


def test_parse_own_pressure_an_empty_roster_is_unknown_rather_than_unmatched():
    """
    The other side of the split, and it is DECIDABLE rather than a preference
    (Tiberius): THE ASKER IS ITSELF A LIVE SEAT, so a roster that omits everyone —
    the caller included — cannot be a true reading. A genuinely empty fleet cannot be
    observed by a member of it.

    ⚠️ Note that "unmatched" is LITERALLY TRUE here — the roster was read, and this
    seat is not in it — and is still wrong. That is why this case has a test of its
    own rather than being left to the reader: the tempting answer is the defensible-
    sounding one.
    """
    assert sr.parse_own_pressure( { "personas": { } }, "cheech" ) == ( sr.PRESSURE_UNKNOWN, None )


def test_parse_own_pressure_matches_a_display_capitalised_roster_key():
    """
    Rio's finding, measured live 2026-08-30: the roster keys by DISPLAY capitalisation
    and the fleet mixes conventions in ONE payload — six of eleven keys were not
    lowercase. `personas.get( "rio" )` returned None while `personas.get( "Rio" )`
    returned a live row at 32.1%.
    """
    section = { "personas": { "Rio": { "status": "within_budget", "consumption_pct_of_window": 32.1 } } }
    assert sr.parse_own_pressure( section, "rio" ) == ( "within_budget", 32.1 )


def test_parse_own_pressure_matches_a_lowercase_roster_key_from_a_display_cased_name():
    """The mirror direction — neither lowercasing nor title-casing is safe on its own."""
    section = { "personas": { "pocholo": { "status": "within_budget", "consumption_pct_of_window": 40.1 } } }
    assert sr.parse_own_pressure( section, "Pocholo" ) == ( "within_budget", 40.1 )


def test_parse_own_pressure_missing_status_is_unknown_but_keeps_pct():
    # a record present without a status must NOT manufacture over_budget
    section = { "personas": { "cheech": { "consumption_pct_of_window": 42.0 } } }
    assert sr.parse_own_pressure( section, "cheech" ) == ( "unknown", 42.0 )


def test_parse_own_pressure_blank_status_is_unknown():
    section = { "personas": { "cheech": { "status": "", "consumption_pct_of_window": 5.0 } } }
    assert sr.parse_own_pressure( section, "cheech" ) == ( "unknown", 5.0 )


def test_parse_own_pressure_personas_not_a_dict_is_unknown_none():
    assert sr.parse_own_pressure( { "personas": None }, "cheech" ) == ( "unknown", None )
    assert sr.parse_own_pressure( { "personas": [ "not", "a", "dict" ] }, "cheech" ) == ( "unknown", None )


def test_parse_own_pressure_a_matched_but_malformed_record_is_unknown_not_unmatched():
    """
    The third state, and it lands on the RIGHT side of the split: we found the seat in
    the roster, so it is not "unmatched" — but the record is unusable, so there is no
    reading either. Calling this "unmatched" would report a seat as absent from a
    roster that plainly lists it.
    """
    assert sr.parse_own_pressure( { "personas": { "Rio": "not a dict" } }, "rio" ) \
           == ( sr.PRESSURE_UNKNOWN, None )


# ---------------------------------------------------------------------------
# lookup_persona_record — the case-tolerant match, tested on its own because the
# KEY it reports is what lets a caller tell "absent" from "matched but empty"
# ---------------------------------------------------------------------------
def test_lookup_persona_record_reports_the_key_it_matched():
    personas = { "Rio": { "status": "within_budget" } }
    assert sr.lookup_persona_record( personas, "rio" ) == ( { "status": "within_budget" }, "Rio" )


def test_lookup_persona_record_prefers_an_EXACT_key_over_a_case_insensitive_one():
    """
    A roster carrying both spellings must resolve to the one actually asked for.
    Without the exact-first check the answer would depend on dict ORDER, which is a
    property of how the roster was built rather than of what the caller wanted.
    """
    personas = { "rio": { "status": "lowercase-row" }, "Rio": { "status": "display-row" } }
    assert sr.lookup_persona_record( personas, "Rio" )[ 1 ] == "Rio"
    assert sr.lookup_persona_record( personas, "rio" )[ 1 ] == "rio"


def test_lookup_persona_record_ignores_surrounding_whitespace():
    assert sr.lookup_persona_record( { "Mr Radio": { } }, "  mr radio  " )[ 1 ] == "Mr Radio"


def test_lookup_persona_record_reports_no_match_as_a_None_KEY_not_an_empty_record():
    """
    The distinction the whole fix rests on: a record may legitimately be EMPTY, so a
    falsy record cannot mean "absent". The matched KEY is what carries that fact.
    """
    assert sr.lookup_persona_record( { "Rio": { } }, "rio" )   == ( { }, "Rio" )
    assert sr.lookup_persona_record( { "Rio": { } }, "nobody" ) == ( None, None )


def test_lookup_persona_record_tolerates_a_non_dict_roster_and_a_non_string_name():
    assert sr.lookup_persona_record( None, "rio" )        == ( None, None )
    assert sr.lookup_persona_record( [ "not", "a", "dict" ], "rio" ) == ( None, None )
    assert sr.lookup_persona_record( { "Rio": { } }, None ) == ( None, None )


def test_lookup_persona_record_skips_a_non_string_key_rather_than_raising():
    """A malformed roster must not take down a seat's own pressure read."""
    assert sr.lookup_persona_record( { 7: { "status": "x" }, "Rio": { "status": "y" } }, "rio" )[ 1 ] == "Rio"


def test_parse_own_pressure_section_not_a_dict_is_unknown_none():
    # the fetch-failure path feeds {} (or a stray non-dict) — must be unknown, never over_budget
    assert sr.parse_own_pressure( {}, "cheech" ) == ( "unknown", None )
    assert sr.parse_own_pressure( None, "cheech" ) == ( "unknown", None )


# ---------------------------------------------------------------------------
# The confirmation wording — THIRD PERSON, naming the persona
# ---------------------------------------------------------------------------

def test_confirmation_text_names_the_persona_in_third_person():
    """
    The ask lands on a SHARED voice surface. Second person ("You are at your context
    ceiling") reads as if the HUMAN is at a ceiling and does not say which seat is
    asking — the one thing the human needs to know to answer.
    """
    question, abstract = sr.confirmation_text( "Mr. Radio" )

    assert question.startswith( "Mr. Radio is at their context ceiling" )
    assert "Re-spin Mr. Radio now?" in question
    assert "Mr. Radio" in abstract

    for second_person in ( "You are", "your context", "I will", "my memento", "my own pane" ):
        assert second_person not in question, f"second-person phrasing in the question: {second_person!r}"
        assert second_person not in abstract, f"second-person phrasing in the abstract: {second_person!r}"


def test_confirmation_text_uses_they_them():
    """A persona name does not tell us anyone's pronouns, and this is read aloud."""
    question, abstract = sr.confirmation_text( "María" )
    assert "their context ceiling" in question
    assert "their memento" in abstract and "their own pane" in abstract
    for gendered in ( " his ", " her ", " he ", " she " ):
        assert gendered not in f" {question} {abstract} "


def test_confirmation_text_degrades_rather_than_saying_unknown():
    """"unknown is at their context ceiling" reads worse than not naming anyone."""
    for unresolved in ( None, "", "   ", "unknown", "UNKNOWN" ):
        question, abstract = sr.confirmation_text( unresolved )
        assert question.startswith( f"{sr.UNNAMED_SEAT} is at their context ceiling" )
        assert "unknown" not in question.lower()
        assert "unknown" not in abstract.lower()


def test_confirmation_text_keeps_the_default_yes_notice_in_the_abstract():
    """The offline default is the human's safety net; it must stay visible."""
    _, abstract = sr.confirmation_text( "Clayton" )
    assert "Defaults to YES if you are away." in abstract


def test_the_default_ask_receives_the_persona( tmp_path, monkeypatch ):
    """
    The seam stays zero-arg so the sixteen injected doubles keep working; the persona
    must still reach the default ask, which is the whole point of the change.
    """
    seen = {}
    monkeypatch.setattr( sr, "_default_ask",
                         lambda persona: seen.setdefault( "persona", persona ) or "no" )

    mp = _write_memento( tmp_path, "u1", _dt( 20 ) )
    r  = sr.perform_self_respin(
        "sid1", persona="Tiberius", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), base_dir=str( tmp_path ), repo_root=str( tmp_path ),
    )

    assert seen[ "persona" ] == "Tiberius"      # ...and NOT a zero-arg call
    assert r.status == "declined"


# ---------------------------------------------------------------------------
# Every argument the ask is fired with — pinned, not changed
# ---------------------------------------------------------------------------

def test_confirmation_kwargs_pins_every_argument_the_ask_is_fired_with():
    """
    `_default_ask` is pragma-no-cover, so anything left inside it is the part of
    this feature nothing can test. These are pinned as they stand — NOT changed.
    """
    kwargs = sr.confirmation_kwargs( "Mr. Radio" )

    assert set( kwargs ) == { "question", "default", "timeout_seconds",
                              "priority", "abstract", "human_only" }
    assert kwargs[ "default" ]         == "yes"      # the OFFLINE SAFETY NET
    assert kwargs[ "human_only" ]      is True       # row 804afce6 — no proxy veto
    assert kwargs[ "timeout_seconds" ] == 120
    assert kwargs[ "priority" ]        == "high"


def test_confirmation_kwargs_default_yes_is_the_offline_safety_net():
    """A seat at its ceiling with the human away must still re-spin; "no" strands it."""
    assert sr.confirmation_kwargs( "anyone" )[ "default" ] == "yes"


def test_confirmation_kwargs_human_only_blocks_the_auto_answer_proxy():
    """Row 804afce6: only a real human "no" (or the offline default) may decide."""
    assert sr.confirmation_kwargs( "anyone" )[ "human_only" ] is True


def test_confirmation_kwargs_takes_its_wording_from_confirmation_text():
    """One definition of the words, not two that drift."""
    question, abstract = sr.confirmation_text( "María" )
    kwargs             = sr.confirmation_kwargs( "María" )

    assert kwargs[ "question" ] == question
    assert kwargs[ "abstract" ] == abstract


def test_confirmation_kwargs_degrades_the_persona_like_the_text_does():
    kwargs = sr.confirmation_kwargs( "unknown" )
    assert kwargs[ "question" ].startswith( f"{sr.UNNAMED_SEAT} is at their context ceiling" )


# ---------------------------------------------------------------------------
# Row 4cf9f9fd — the truncating stamp, and the two halves that make it unwritable.
# Measured 2026-08-25 on session d34333a9: a 105-line memento became 93 bytes (the
# nonce line alone), verified clean, and the pane cleared into it.
# ---------------------------------------------------------------------------
def test_verify_rejects_a_nonce_only_memento_even_though_it_is_fresh():
    """The exact failure shape: right uuid, fresh ts, and nothing to wake into."""
    content = f"{sr.build_nonce_line( 'u1', _dt( 20 ) )}\n"
    ok, reason = sr.verify_memento_content( content, "u1", _dt( 21 ), cycle_window_seconds=300 )
    assert ok is False
    assert "nonce-only" in reason


def test_verify_rejects_a_body_under_the_substance_floor():
    content = _memento_with_nonce( "u1", _dt( 20 ), extra="b\n" )
    ok, reason = sr.verify_memento_content( content, "u1", _dt( 21 ) )
    assert ok is False
    assert str( sr.MIN_MEMENTO_SUBSTANCE_BYTES ) in reason


def test_substance_floor_sits_under_every_real_memento():
    """1226B was the smallest genuine memento on the box when this floor was set."""
    assert sr.MIN_MEMENTO_SUBSTANCE_BYTES < 1226


def test_stamp_appends_without_losing_the_body( tmp_path ):
    memento = tmp_path / "seat.md"
    memento.write_text( _REAL_BODY, encoding="utf-8" )

    line = sr.stamp_nonce_into( str( memento ), "u1", _dt( 20 ) )

    after = memento.read_text( encoding="utf-8" )
    assert _REAL_BODY.strip() in after                     # every byte of the body survived
    assert after.endswith( line + "\n" )
    assert sr.verify_memento_content( after, "u1", _dt( 21 ) )[ 0 ] is True


def test_stamp_is_the_fix_for_the_truncating_one_liner( tmp_path ):
    """The regression itself: the hand-rolled form empties the file, the verb does not."""
    hand = tmp_path / "hand.md"
    hand.write_text( _REAL_BODY, encoding="utf-8" )
    # Clayton's line, verbatim in shape: the outer open() truncates before the read runs.
    open( hand, "w" ).write( open( hand ).read().rstrip( "\n" ) + "\n\nSTAMP\n" )
    assert hand.read_text( encoding="utf-8" ) == "\n\nSTAMP\n"      # the body is gone

    safe = tmp_path / "safe.md"
    safe.write_text( _REAL_BODY, encoding="utf-8" )
    sr.stamp_nonce_into( str( safe ), "u1", _dt( 20 ) )
    assert _REAL_BODY.strip() in safe.read_text( encoding="utf-8" )


def test_stamp_leaves_no_temp_file_behind( tmp_path ):
    memento = tmp_path / "seat.md"
    memento.write_text( _REAL_BODY, encoding="utf-8" )
    sr.stamp_nonce_into( str( memento ), "u1", _dt( 20 ) )
    assert [ p.name for p in tmp_path.iterdir() ] == [ "seat.md" ]


def test_stamp_refuses_a_missing_memento( tmp_path ):
    with pytest.raises( FileNotFoundError ):
        sr.stamp_nonce_into( str( tmp_path / "nope.md" ), "u1", _dt( 20 ) )


def test_stamp_refuses_a_blank_memento( tmp_path ):
    memento = tmp_path / "blank.md"
    memento.write_text( "   \n", encoding="utf-8" )
    with pytest.raises( ValueError, match="blank" ):
        sr.stamp_nonce_into( str( memento ), "u1", _dt( 20 ) )


def test_stamp_refuses_to_stamp_the_same_nonce_twice( tmp_path ):
    memento = tmp_path / "seat.md"
    memento.write_text( _REAL_BODY, encoding="utf-8" )
    sr.stamp_nonce_into( str( memento ), "u1", _dt( 20 ) )
    with pytest.raises( ValueError, match="already carries" ):
        sr.stamp_nonce_into( str( memento ), "u1", _dt( 21 ) )


def test_stamp_removes_the_temp_file_when_the_write_fails( tmp_path, monkeypatch ):
    memento = tmp_path / "seat.md"
    memento.write_text( _REAL_BODY, encoding="utf-8" )

    def _boom( *a, **kw ):
        raise OSError( "disk full" )
    monkeypatch.setattr( sr.os, "replace", _boom )

    with pytest.raises( OSError ):
        sr.stamp_nonce_into( str( memento ), "u1", _dt( 20 ) )
    assert [ p.name for p in tmp_path.iterdir() ] == [ "seat.md" ]      # tmp cleaned
    assert memento.read_text( encoding="utf-8" ) == _REAL_BODY          # original untouched


def test_only_the_BODY_moves_the_verdict_not_the_nonce_freshness():
    """
    Clayton's nit, and it is the right one: a test that rejects a husk proves
    nothing unless the SAME nonce, at the SAME instant, passes once a body is
    present. Otherwise the rejection could be staleness wearing the floor's
    clothes and the floor would never be exercised.
    """
    stamped, now = _dt( 20 ), _dt( 21 )
    line         = sr.build_nonce_line( "u1", stamped )

    husk = f"{line}\n"
    real = f"# memento\n{_REAL_BODY}{line}\n"

    husk_ok, husk_why = sr.verify_memento_content( husk, "u1", now, cycle_window_seconds=300 )
    real_ok, _        = sr.verify_memento_content( real, "u1", now, cycle_window_seconds=300 )

    assert husk_ok is False and real_ok is True     # same nonce, same clock — only the body differs
    assert "nonce-only" in husk_why
    assert "stale" not in husk_why                  # it failed on SUBSTANCE, not freshness


# ---------------------------------------------------------------------------
# The SLOT gate inside perform_self_respin (row 8068c65e)
#
# The gap this closes: `dismiss_sessions` runs a real memento proof and raises
# memento_alarm on a miss; `self_respin` ran no equivalent, so Tiberius's misplaced
# memento went unreported on 2026-08-30 while Pocholo's was caught on the reap path.
# These tests prove the gate exists, fires BEFORE the ask, and runs the reap's own
# predicate — and the negative control proves it can fail on a real misplacement.
# ---------------------------------------------------------------------------
def _slot_kwargs( tmp_path, mp, **over ):
    kw = dict(
        persona=_SEAT_PERSONA, memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(),
        base_dir=str( tmp_path ), repo_root=str( tmp_path ),
    )
    kw.update( over )
    return kw


def test_slot_gate_aborts_and_never_asks_when_the_memento_is_off_slot( tmp_path ):
    """
    🔴 NEGATIVE CONTROL — Tiberius's real case, at the orchestrator.

    The memento is complete, fresh, correctly nonce-stamped, and would have passed the
    OLD check exactly as it did on 2026-08-30 — it is simply not at the seat's slot.
    The verb must abort, and must never reach the human with a confirmation ask for a
    clear that would land in nothing any reader follows.
    """
    stray = tmp_path / "elsewhere" / "tiberius-f032ae9f-memento.md"
    stray.parent.mkdir()
    stray.write_text( _memento_with_nonce( "u1", _dt( 20 ) ) )
    ask, sched = _Spy(), _Spy()

    r = sr.perform_self_respin( _SEAT_SID, ask_fn=ask, schedule_fn=sched,
                                **_slot_kwargs( tmp_path, str( stray ) ) )

    assert r.status == "aborted"
    assert "memento slot check failed" in r.reason
    assert "not at this seat's 'root' slot" in r.reason
    assert ask.calls   == 0     # never asked
    assert sched.calls == 0     # never scheduled


def test_the_same_memento_passes_once_it_is_written_to_the_slot( tmp_path ):
    """The paired positive: identical content, at the slot, schedules. Only place changed."""
    mp    = _write_memento( tmp_path, "u1", _dt( 20 ) )
    sched = _Spy()
    r = sr.perform_self_respin( _SEAT_SID, ask_fn=lambda: "yes", schedule_fn=sched,
                                **_slot_kwargs( tmp_path, mp ) )
    assert r.status == "scheduled"
    assert sched.calls == 1


def test_slot_gate_runs_before_the_nonce_verify( tmp_path ):
    """
    Order matters: a nonce proves the file you NAMED is fresh and says nothing about
    whether any reader will look at it. So an off-slot memento reports the SLOT failure,
    not a nonce failure — even when its nonce is also wrong.
    """
    stray = tmp_path / "stray.md"
    stray.write_text( _memento_with_nonce( "old", _dt( 20 ) ) )
    r = sr.perform_self_respin( _SEAT_SID, ask_fn=_Spy(), schedule_fn=_Spy(),
                                **_slot_kwargs( tmp_path, str( stray ), memento_nonce="this-cycle" ) )
    assert "memento slot check failed" in r.reason
    assert "memento verify failed"    not in r.reason


def test_slot_gate_aborts_when_the_repo_root_cannot_be_resolved( tmp_path ):
    """An unresolvable root REFUSES — a guessed root finds the WRONG memento, not none."""
    mp = _write_memento( tmp_path, "u1", _dt( 20 ) )
    r  = sr.perform_self_respin(
        _SEAT_SID, ask_fn=_Spy(), schedule_fn=_Spy(),
        **_slot_kwargs( tmp_path, mp, repo_root="" ),
    )
    assert r.status == "aborted"
    assert "cannot resolve this seat's repo root" in r.reason


def test_slot_gate_is_injectable_and_receives_the_seats_identity( tmp_path ):
    seen = {}
    def fake_verify( memento_path, **k ):
        seen.update( k, memento_path=memento_path )
        return True, "ok"
    mp = _write_memento( tmp_path, "u1", _dt( 20 ) )
    sr.perform_self_respin( _SEAT_SID, ask_fn=lambda: "yes", schedule_fn=_Spy(),
                            verify_slot_fn=fake_verify, **_slot_kwargs( tmp_path, mp ) )
    assert seen[ "memento_path" ] == mp
    assert seen[ "persona" ]      == _SEAT_PERSONA
    assert seen[ "session_id" ]   == _SEAT_SID
    assert seen[ "repo_root" ]    == str( tmp_path )
    assert seen[ "now" ]          == _dt( 21 )


def test_default_verify_slot_delegates_to_memento_slot_with_the_root_slot( tmp_path ):
    """The live seam: root slot, and the caller's repo_root passed straight through."""
    read, pointer = None, str( tmp_path / ".claude-memento.md" )
    _write_memento( tmp_path, "u1", _dt( 20 ) )
    ok, reason = sr._default_verify_slot(
        pointer, repo_root=str( tmp_path ), persona=_SEAT_PERSONA, session_id=_SEAT_SID,
        now=_dt( 21 ), read_text_fn=lambda p: open( p, encoding="utf-8" ).read()
                       if os.path.exists( p ) else None,
    )
    assert ok is True
    assert "'root' slot" in reason


def test_default_verify_slot_resolves_the_repo_root_when_none_is_given( monkeypatch ):
    """repo_root=None ⇒ resolve it live; an unresolvable one reaches the single refusal."""
    monkeypatch.setattr( sr, "resolve_repo_root", lambda: None )
    ok, reason = sr._default_verify_slot(
        "/anywhere/.claude-memento.md", repo_root=None, persona="cheech",
        session_id="sid1", now=_dt( 21 ), read_text_fn=lambda p: None,
    )
    assert ok is False
    assert "cannot resolve this seat's repo root" in reason


def test_negative_control_the_old_tautological_check_accepts_the_same_off_slot_memento( tmp_path ):
    """
    🔴 THE CONTROL, MADE PERMANENT — remove the fix and watch it redden, in-suite.

    A test that only proves the new gate REJECTS an off-slot memento cannot show the
    gate is what rejected it; the old check passed everything, so "it passes now" was
    never the discriminator. This runs the SAME input twice, changing only whether the
    slot check is the real one or the old tautological one — "does the file you named
    exist?", whose success criterion comes from the caller it is checking.

    REJECTED under the real check, SCHEDULED under the old one. That difference is the
    fix, and it is asserted here rather than described in a commit message.
    """
    stray = tmp_path / "elsewhere" / "tiberius-f032ae9f-memento.md"
    stray.parent.mkdir()
    stray.write_text( _memento_with_nonce( "u1", _dt( 20 ) ) )

    def old_tautological_check( memento_path, **k ):
        return os.path.exists( memento_path ), "the file you named is where you said it is"

    with_fix = sr.perform_self_respin(
        _SEAT_SID, ask_fn=lambda: "yes", schedule_fn=_Spy(),
        **_slot_kwargs( tmp_path, str( stray ) ) )
    without_fix = sr.perform_self_respin(
        _SEAT_SID, ask_fn=lambda: "yes", schedule_fn=_Spy(),
        verify_slot_fn=old_tautological_check,
        **_slot_kwargs( tmp_path, str( stray ) ) )

    assert with_fix.status    == "aborted"      # the gate catches it
    assert without_fix.status == "scheduled"    # ...and nothing else would have
