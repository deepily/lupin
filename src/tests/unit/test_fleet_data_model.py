"""
Unit tests for the heartbeat-arbiter fleet data-model transform (pure).

Covers the UNION roster (arbiter liveness fix, Step 1.4): membership across the
four signals (bridge / commons / idle_prompt / stop-event), id-form
canonicalization (N3), the kind=idle_prompt activity-axis filter (N2), and the
distinct ts fields the verdict seam consumes — plus the pure helper functions.
"""
import datetime

from cosa.agents.heartbeat_arbiter import fleet_data_model as m


UTC = datetime.timezone.utc
NOW = datetime.datetime( 2026, 6, 5, 12, 0, 0, tzinfo=UTC )


def _iso( seconds_ago ):
    return ( NOW - datetime.timedelta( seconds=seconds_ago ) ).isoformat()


def _ev( outcome, ts, **kw ):
    rec = { "session_id": "s", "persona": "Ann", "outcome": outcome, "ts": ts,
            "poke_count": 0, "cap": 3, "work_owed": False, "awaiting": None }
    rec.update( kw )
    return rec


def _idle_rec( ts, persona="Dot", sid="ip" ):
    return { "session_id": sid, "persona": persona, "kind": "idle_prompt", "ts": ts }


def _reaped_rec( ts, persona="Hal", sid="rp" ):
    return { "session_id": sid, "persona": persona, "kind": "reaped", "ts": ts }


# ── _parse_iso ────────────────────────────────────────────────────────────────

def test_parse_iso_none_and_non_str():
    assert m._parse_iso( None ) is None
    assert m._parse_iso( 123 ) is None
    assert m._parse_iso( "" ) is None


def test_parse_iso_z_suffix_and_naive_get_utc():
    z = m._parse_iso( "2026-06-05T12:00:00Z" )
    assert z is not None and z.tzinfo is not None
    naive = m._parse_iso( "2026-06-05T12:00:00" )       # no tz → coerced to UTC
    assert naive.tzinfo == UTC


def test_parse_iso_invalid_returns_none():
    assert m._parse_iso( "not-a-timestamp" ) is None


# ── _age_seconds / _is_recent / _newer ───────────────────────────────────────

def test_age_seconds_none_and_bad_type():
    assert m._age_seconds( None, NOW ) is None
    # ts that can't subtract → TypeError path → None
    assert m._age_seconds( "oops", NOW ) is None


def test_is_recent_window():
    fresh = NOW - datetime.timedelta( seconds=10 )
    old   = NOW - datetime.timedelta( seconds=10_000 )
    assert m._is_recent( fresh, NOW, 3600 ) is True
    assert m._is_recent( old, NOW, 3600 ) is False
    assert m._is_recent( None, NOW, 3600 ) is False


def test_newer_all_branches():
    a = NOW
    b = NOW - datetime.timedelta( seconds=5 )
    assert m._newer( None, b ) is b
    assert m._newer( a, None ) is a
    assert m._newer( a, b ) is a          # a >= b
    assert m._newer( b, a ) is a          # a < b → returns the later (a)
    assert m._newer( None, None ) is None


# ── _who_matches / _commons_ts_for_session ───────────────────────────────────

def test_who_matches():
    assert m._who_matches( "abc12345", "abc12345-full-uuid" ) is True   # full.startswith(short)
    assert m._who_matches( "abc12345-full-uuid", "abc12345" ) is True   # short prefixes full
    assert m._who_matches( "same", "same" ) is True
    assert m._who_matches( "abc", "xyz" ) is False
    assert m._who_matches( "", "x" ) is False
    assert m._who_matches( "x", "" ) is False


def test_commons_ts_skips_non_dict_and_mismatch_and_bad_ts():
    rows = [
        "not-a-dict",                                            # skipped (non-dict)
        { "session_id": "other", "last_post_ts": _iso( 5 ) },    # skipped (no match)
        { "session_id": "s1", "last_post_ts": "bad" },           # match but unparseable ts
        { "session_id": "s1", "last_post_ts": _iso( 5 ) },       # match + valid
    ]
    ts = m._commons_ts_for_session( rows, "s1" )
    assert ts is not None
    assert m._commons_ts_for_session( None, "s1" ) is None


# ── _canonicalize_ids ─────────────────────────────────────────────────────────

def test_canonicalize_merges_short_into_full_and_keeps_unrelated():
    full = "abcd1234-aaaa-bbbb"
    canon = m._canonicalize_ids( [ "abcd1234", full, "zzzz", "", None ] )
    assert canon[ "abcd1234" ] == full      # short → its longer full prefix-match
    assert canon[ full ] == full            # full → itself
    assert canon[ "zzzz" ] == "zzzz"        # unrelated → itself
    assert "" not in canon and None not in canon   # falsy dropped


# ── build_fleet_view — UNION membership ──────────────────────────────────────

def test_build_view_union_all_sources_and_empty_skipped():
    full = "abcd1234-aaaa-bbbb-cccc-dddddddddddd"
    events = {
        "s1": [ _ev( "poked", _iso( 30 ), awaiting="peer:Bob", poke_count=1 ) ],
        "s2": [ _ev( "cap_reached", _iso( 9000 ), work_owed=True ),
                _ev( "cap_reached", _iso( 30 ), work_owed=True ) ],
        "s3": [ _ev( "idle", _iso( 9000 ) ) ],          # alive via commons only
        "s4": [ ],                                       # no signal → skipped
        "ip": [ _idle_rec( _iso( 30 ) ) ],               # idle_prompt-only
        "abcd1234": [ _ev( "poked", _iso( 30 ), persona="Eve" ) ],   # canonical w/ bridge
    }
    who_rows = [ { "session_id": "s3", "last_post_ts": _iso( 30 ) } ]
    bridges  = { full: "Eve", "bridgeonly": "Fred" }

    view = m.build_fleet_view( events, who_rows, NOW, 3600, bridge_sessions=bridges )

    assert set( view ) == { "s1", "s2", "s3", "ip", full, "bridgeonly" }
    assert "abcd1234" not in view                                   # canonicalized into full
    assert "s4" not in view                                         # empty + no signal


def test_build_view_idle_prompt_off_activity_axis():
    """A kind=idle_prompt record feeds idle_prompt_ts ONLY — never state/stop-event."""
    events = { "ip": [ _idle_rec( _iso( 20 ), persona="Dot" ) ] }
    view   = m.build_fleet_view( events, None, NOW, 3600 )
    v = view[ "ip" ]
    assert v[ "state" ] == "unknown" and v[ "last_outcome" ] is None
    assert v[ "last_event_ts" ] is None              # NOT a stop-event
    assert v[ "idle_prompt_ts" ] is not None         # feeds idle_prompt age only
    assert v[ "persona" ] == "Dot" and v[ "holding_on" ] == "none"
    assert v[ "stuck" ] is False and v[ "poke_count" ] is None and v[ "cap" ] is None


def test_build_view_mixed_activity_and_idle_prompt_kept_distinct():
    events = { "s1": [ _ev( "poked", _iso( 100 ), awaiting="peer:Z" ),
                       _idle_rec( _iso( 5 ), sid="s1" ) ] }
    v = m.build_fleet_view( events, None, NOW, 3600 )[ "s1" ]
    assert v[ "state" ] == "working" and v[ "last_event_ts" ] is not None   # from the poke
    assert v[ "idle_prompt_ts" ] is not None                                # from the idle_prompt
    # activity_ts is the freshest of (event, commons, idle_prompt) → the idle_prompt (5s)
    assert v[ "alive" ] is True


def test_build_view_persona_precedence_activity_then_idle():
    # no bridge persona → falls back to activity record persona
    v1 = m.build_fleet_view( { "s": [ _ev( "poked", _iso( 5 ), persona="Act" ) ] }, None, NOW, 3600 )[ "s" ]
    assert v1[ "persona" ] == "Act"
    # no bridge, no activity → idle_prompt persona
    v2 = m.build_fleet_view( { "s": [ _idle_rec( _iso( 5 ), persona="Idle", sid="s" ) ] }, None, NOW, 3600 )[ "s" ]
    assert v2[ "persona" ] == "Idle"


def test_build_view_bridge_persona_preferred_over_event():
    full   = "feed1234-aaaa-bbbb"
    events = { "feed1234": [ _ev( "poked", _iso( 5 ), persona="EventName" ) ] }
    v = m.build_fleet_view( events, None, NOW, 3600, bridge_sessions={ full: "BridgeName" } )[ full ]
    assert v[ "persona" ] == "BridgeName"


def test_build_view_bridge_only_member_is_unknown_state():
    v = m.build_fleet_view( { }, None, NOW, 3600, bridge_sessions={ "b": "Ghost" } )[ "b" ]
    assert v[ "persona" ] == "Ghost" and v[ "state" ] == "unknown"
    assert v[ "last_event_ts" ] is None and v[ "alive" ] is False


def test_build_view_bridge_present_but_persona_none():
    v = m.build_fleet_view( { }, None, NOW, 3600, bridge_sessions={ "b": None } )
    assert "b" in v and v[ "b" ][ "persona" ] is None     # present (bridge signal) but unnamed


def test_build_view_commons_only_member_is_phantom_without_bridge():
    # §5.2(b) PHANTOM GUARD: a commons-only session with NO live bridge is the
    # reaped-worker retention echo — still a roster member (auditable), but its
    # commons echo is nulled so it carries no liveness signal at all.
    who = [ { "session_id": "c1", "last_post_ts": _iso( 10 ) } ]
    v = m.build_fleet_view( { }, who, NOW, 3600 )
    assert "c1" in v                                     # membership survives (raw signal)
    assert v[ "c1" ][ "commons_ts" ] is None             # echo nulled by the guard
    assert v[ "c1" ][ "alive" ] is False                 # no liveness signal remains
    assert v[ "c1" ][ "last_activity_ts" ] is None


def test_build_view_commons_only_member_with_live_bridge_stays_alive():
    # The legitimate twin: same commons signal, but the bridge is LIVE — commons
    # counts as the secondary signal (Part-7 union doctrine unchanged).
    who = [ { "session_id": "c1", "last_post_ts": _iso( 10 ) } ]
    v = m.build_fleet_view( { }, who, NOW, 3600, bridge_sessions={ "c1": "Cal" } )
    assert v[ "c1" ][ "commons_ts" ] is not None and v[ "c1" ][ "alive" ] is True


# ── build_fleet_view — §5.2(b) phantom guard (commons vs live-bridge) ─────────

def test_phantom_guard_old_event_plus_recent_commons_no_bridge_not_alive():
    # The reaped-worker shape: stale stop-events + a recent commons echo, bridge
    # deleted by the reap. Pre-guard this read alive=True (pinned "quiet" on the
    # roster); the guard nulls the echo so liveness rests on the stale event only.
    events = { "rw": [ _ev( "poked", _iso( 9000 ), sid="rw" ) ] }
    who    = [ { "session_id": "rw", "last_post_ts": _iso( 10 ) } ]
    v = m.build_fleet_view( events, who, NOW, 3600 )[ "rw" ]
    assert v[ "commons_ts" ] is None
    assert v[ "alive" ] is False                         # 9000s event > 3600s threshold
    assert v[ "last_event_ts" ] is not None              # event signal untouched (honest)


def test_phantom_guard_recent_event_still_counts_when_bridge_absent():
    # Degrade-safety: the guard mutes ONLY the commons echo — a genuinely recent
    # stop-event keeps the session alive even if bridge discovery missed it.
    events = { "s": [ _ev( "poked", _iso( 30 ) ) ] }
    who    = [ { "session_id": "s", "last_post_ts": _iso( 10 ) } ]
    v = m.build_fleet_view( events, who, NOW, 3600 )[ "s" ]
    assert v[ "commons_ts" ] is None and v[ "alive" ] is True


def test_phantom_guard_prefix_tolerant_bridge_match_keeps_commons():
    # Canonicalization (N3) composes with the guard: a short-id commons row and a
    # full-uuid live bridge are the SAME session → bridge_present → commons kept.
    full = "cafe1234-aaaa-bbbb-cccc-dddddddddddd"
    who  = [ { "session_id": "cafe1234", "last_post_ts": _iso( 10 ) } ]
    v = m.build_fleet_view( { }, who, NOW, 3600, bridge_sessions={ full: "Eve" } )
    assert v[ full ][ "commons_ts" ] is not None and v[ full ][ "alive" ] is True


def test_phantom_guard_evicted_from_published_snapshot():
    # End-to-end through the verdict seam (§5.2 composition): the phantom reads
    # "offline" in compute_liveness ⇒ build_snapshot's default publish-prune
    # evicts it, while the live-bridge peer survives. include_offline=True
    # retains the phantom as an auditable offline row.
    from cosa.agents.heartbeat_arbiter import fleet_render as fr
    who     = [ { "session_id": "phantom", "last_post_ts": _iso( 10 ) },
                { "session_id": "live",    "last_post_ts": _iso( 10 ) } ]
    bridges = { "live": "Cal" }
    view    = m.build_fleet_view( { }, who, NOW, 3600, bridge_sessions=bridges )

    published = fr.build_snapshot( view, { "live": NOW.timestamp() - 4 }, NOW )
    assert { r[ "session_id" ] for r in published[ "sessions" ] } == { "live" }
    assert published[ "session_count" ] == 1

    audit = fr.build_snapshot( view, { "live": NOW.timestamp() - 4 }, NOW, include_offline=True )
    rows  = { r[ "session_id" ]: r for r in audit[ "sessions" ] }
    assert rows[ "phantom" ][ "liveness" ][ "verdict" ] == "offline"
    assert rows[ "live" ][ "liveness" ][ "verdict" ] == "LIVE"


def test_build_view_stuck_threshold():
    events = { "s": [ _ev( "cap_reached", _iso( 100 ), work_owed=True ),
                      _ev( "cap_reached", _iso( 50 ), work_owed=True ) ] }
    assert m.build_fleet_view( events, None, NOW, 3600 )[ "s" ][ "stuck" ] is True
    one = { "s": [ _ev( "cap_reached", _iso( 50 ), work_owed=True ) ] }
    assert m.build_fleet_view( one, None, NOW, 3600 )[ "s" ][ "stuck" ] is False


def test_build_view_non_list_and_non_dict_records_are_safe():
    events = { "bad": "not-a-list", "mixed": [ "not-a-dict", _ev( "poked", _iso( 5 ) ) ] }
    v = m.build_fleet_view( events, None, NOW, 3600 )
    assert "bad" not in v                       # non-list events → no records → no signal → skipped
    assert v[ "mixed" ][ "state" ] == "working" # the one valid dict record drives it


def test_build_view_none_inputs_never_raise():
    assert m.build_fleet_view( None, None, NOW, 3600 ) == { }
    assert m.build_fleet_view( None, None, NOW, 3600, bridge_sessions=None ) == { }


def test_build_view_who_row_without_session_id_ignored():
    who = [ { "persona_name": "x" }, { "session_id": "", "last_post_ts": _iso( 5 ) } ]
    # neither contributes a member; with no other source the roster is empty
    assert m.build_fleet_view( { }, who, NOW, 3600 ) == { }


# ── reap tombstone (kind=reaped) — membership + off-axis + flag ───────────────

def test_build_view_reaped_only_member_off_axis_with_flag():
    """A kind=reaped tombstone makes the session a member, sets reaped=True, and
    stays OFF the activity axis (never state / never feeds last_event_ts)."""
    events = { "rp": [ _reaped_rec( _iso( 20 ), persona="Hal" ) ] }
    v = m.build_fleet_view( events, None, NOW, 3600 )[ "rp" ]
    assert v[ "reaped" ] is True
    assert v[ "state" ] == "unknown" and v[ "last_outcome" ] is None
    assert v[ "last_event_ts" ] is None and v[ "idle_prompt_ts" ] is None
    assert v[ "persona" ] == "Hal"                      # persona fallback to the tombstone


def test_build_view_reaped_flag_false_on_ordinary_session():
    """Additive flag defaults False for any non-reaped row."""
    v = m.build_fleet_view( { "s": [ _ev( "poked", _iso( 5 ) ) ] }, None, NOW, 3600 )[ "s" ]
    assert v[ "reaped" ] is False


def test_build_view_reaped_does_not_corrupt_activity_axis():
    """An activity record + a reaped tombstone: state comes from the activity
    record, reaped flag still set, tombstone never becomes state."""
    events = { "s": [ _ev( "poked", _iso( 40 ), persona="Act" ), _reaped_rec( _iso( 5 ), sid="s" ) ] }
    v = m.build_fleet_view( events, None, NOW, 3600 )[ "s" ]
    assert v[ "reaped" ] is True
    assert v[ "state" ] == "working" and v[ "last_outcome" ] == "poked"
    assert v[ "persona" ] == "Act"                      # activity persona preferred over tombstone


def test_build_view_reaped_persona_fallback_after_idle_prompt():
    """Persona precedence: bridge → activity → idle_prompt → reaped (last resort)."""
    events = { "s": [ _idle_rec( _iso( 8 ), persona="Idle", sid="s" ),
                      _reaped_rec( _iso( 4 ), persona="Reap", sid="s" ) ] }
    v = m.build_fleet_view( events, None, NOW, 3600 )[ "s" ]
    assert v[ "persona" ] == "Idle"                     # idle_prompt wins over the tombstone
    # reaped-only (no idle_prompt) → tombstone persona is used
    only = { "s": [ _reaped_rec( _iso( 4 ), persona="Reap", sid="s" ) ] }
    assert m.build_fleet_view( only, None, NOW, 3600 )[ "s" ][ "persona" ] == "Reap"


def test_quick_smoke_test_passes():
    assert m.quick_smoke_test() is True
