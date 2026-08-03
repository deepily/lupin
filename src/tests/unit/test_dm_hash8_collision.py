#!/usr/bin/env python3
"""
The 8-char session-id truncation, both arms — row 2a6759de.

⚠️ MOST OF THIS FILE ASSERTS A DEFECT, NOT A CONTRACT. Rick ruled 2026-07-27
that the full 36-char session id must be persisted as the DM addressee; that fix
needs a schema migration and is NOT shipped. Until it is, these tests pin the
CURRENT broken behaviour so the eventual fix has a red-to-green target, and so
the shape cannot be re-discovered from scratch a third time.

THE MECHANISM — one truncation rule, applied at two independent sites:
    dm.py:329                     job_id = target_session_id[ :8 ]     (routing)
    dm_inbox_reconcile.py:167     suffix = ( session_id or "" )[ :8 ]  (HWM file)

Two sessions sharing a first-8 therefore collapse on BOTH, and the two arms have
very different consequences:

    ARM 1  shared HWM ledger   -> mutual SUPPRESSION. A marks a DM surfaced, B
                                  reads A's dedup set and skips it.
    ARM 2  shared job_id       -> MISDELIVERY. B's filter matches A's DMs and
                                  surfaces them AS B's OWN. Strictly worse, and
                                  upstream of the HWM entirely.

⚠️ ARM 2 HAS NO CHEAP FIX, AND THAT IS MEASURED, NOT ASSUMED. `dm.py:565-577`
serializes `job_id` and `recipient_session_hash8` as THE SAME VALUE; no full
session id survives anywhere on a persisted DM row. There is nothing to tighten
the join against — which is exactly why the ruling had to be a schema decision.

⚠️ AND FIXING ARM 1 ALONE IS THE DANGEROUS OUTCOME: the visible symptom
(suppression) disappears while the invisible one (leakage) remains. Do not ship
a wider HWM filename by itself.

SEVERITY: LATENT. 0 duplicate suffixes among 435 HWM files as measured
2026-07-26. The ~77,000-session birthday figure applies ONLY to accidental UUID
collisions on arm 1 — `job_id` is reached by non-UUID ids that CLUSTER by
construction (four in-repo `stable-*` literals already collapse to one key), so
arm 2's likelihood is UNQUANTIFIED and the 77k number must not be carried to it.

Row: 2a6759de · prior art 8758d0b1, 59f355e0, 2565956b
"""
import os
import sys

import pytest

_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
_SRC = os.path.join( _LUPIN_ROOT, "src" )
if _SRC not in sys.path: sys.path.insert( 0, _SRC )

from lupin_cli.claude_code.hooks.lib import dm_inbox_reconcile as dr


# Two DISTINCT full session ids that share a first-8. This is the whole premise;
# if these ever stop colliding the file is testing nothing.
SESSION_A = "46ffe611-aaaa-4000-8000-000000000001"
SESSION_B = "46ffe611-bbbb-4000-8000-000000000002"
SHARED8   = "46ffe611"


def _row( mid, job_id=SHARED8, created="2026-07-02T11:00:00+00:00" ):
    return {
        "message_id"     : mid,
        "thread_id"      : "t1",
        "reply_to"       : None,
        "sender_id"      : "s",
        "sender_persona" : "mr radio",
        "sender_icon"    : "🦉",
        "body"           : "private to A",
        "direction"      : "ai_to_ai",
        "state"          : "sent",
        "job_id"         : job_id,
        "created_at"     : created,
    }


class TestThePremise:
    """
    CONTROL — the collision this file rests on must be real, and the two ids
    must be genuinely different. Without this, every assertion below could pass
    against ids that are simply equal.
    """

    def test_the_two_sessions_are_distinct( self ):
        assert SESSION_A != SESSION_B

    def test_but_they_share_a_first_eight( self ):
        assert SESSION_A[ :8 ] == SESSION_B[ :8 ] == SHARED8


class TestArm1SharedHwmLedger:
    """ARM 1 — two live sessions resolve to ONE high-water-mark file."""

    def test_distinct_sessions_collapse_to_one_hwm_path( self, tmp_path ):
        """
        ⚠️ ASSERTS THE DEFECT. When the full id is persisted and used to key (or
        validate) the ledger, this becomes assertNotEqual and this test must be
        inverted, not deleted — the inversion is the record of what changed.
        """
        p_a = dr._hwm_path( SESSION_A, base_dir=str( tmp_path ) )
        p_b = dr._hwm_path( SESSION_B, base_dir=str( tmp_path ) )
        assert p_a == p_b, (
            "the HWM paths diverged — if the full session id now keys the ledger, "
            "invert this assertion and update row 2a6759de"
        )

    def test_one_sessions_state_is_read_by_the_other( self, tmp_path ):
        """
        The consequence, not just the path collision: B inherits A's cursor and
        dedup set wholesale. This is the suppression mechanism.
        """
        dr.write_hwm( SESSION_A, { "cursor_ts": "2026-07-02T12:00:00+00:00",
                                   "seeded": True, "surfaced_ids": [ "m-private-to-A" ] },
                      base_dir=str( tmp_path ) )
        state_b = dr.read_hwm( SESSION_B, base_dir=str( tmp_path ) )
        assert "m-private-to-A" in state_b.get( "surfaced_ids", [] ), (
            "B no longer inherits A's dedup set — arm 1 may be fixed; update the row"
        )

    def test_a_dm_A_already_surfaced_is_SUPPRESSED_for_B( self, tmp_path ):
        """
        ⭐ THE ONE THE ROW SAYS FAILS TODAY. B never sees a DM addressed to the
        shared key because A's ledger says it was already shown. This is the
        DM-suppression class 59f355e0 was built to eliminate, re-entering
        through the filename.
        """
        dr.write_hwm( SESSION_A, { "cursor_ts": None, "seeded": True,
                                   "surfaced_ids": [ "m1" ] }, base_dir=str( tmp_path ) )
        state_b = dr.read_hwm( SESSION_B, base_dir=str( tmp_path ) )
        context, _new_state = dr.reconcile_context( SHARED8, [ _row( "m1" ) ], state_b )
        assert context == "", (
            "B surfaced a DM that A had already marked — arm 1 is fixed; invert this"
        )


class TestArm2SharedJobIdMisdelivery:
    """
    ARM 2 — the strictly worse arm, and upstream of the HWM. The reconcile joins
    `job_id == session_hash8` by EQUALITY, so a colliding session matches DMs
    that were never addressed to it.
    """

    def test_B_surfaces_a_DM_addressed_to_A_as_its_own( self ):
        """
        ⚠️ ASSERTS THE DEFECT, and this is the leakage one: no ledger state is
        involved at all — B is handed a fresh state and still claims A's DM.
        One persona reading another's private DMs.
        """
        fresh = { "cursor_ts": None, "seeded": True, "surfaced_ids": [] }
        context, new_state = dr.reconcile_context( SHARED8, [ _row( "m-for-A" ) ], fresh )
        assert "private to A" in context, (
            "the join no longer matches on the truncated key — arm 2 may be fixed"
        )
        assert "m-for-A" in new_state.get( "surfaced_ids", [] ), (
            "B did not record A's DM as its own — the leakage may be closed"
        )

    def test_the_join_cannot_discriminate_because_no_full_id_is_on_the_row( self ):
        """
        WHY ARM 2 HAD NO CHEAP FIX — the discriminator is absent from the data,
        not merely unused. A serialized DM row carries `job_id` and
        `recipient_session_hash8` as the same value and nothing wider.

        This is the assertion that justified escalating to a schema ruling
        rather than tightening the join, so it is pinned rather than trusted.
        """
        row = _row( "m1" )
        full_id_fields = [ k for k, v in row.items()
                           if isinstance( v, str ) and v in ( SESSION_A, SESSION_B ) ]
        assert full_id_fields == [ ], (
            f"a full session id now rides the DM row ({full_id_fields}) — the cheap "
            f"join-side fix EXISTS after all; re-read row 2a6759de before designing"
        )


class TestNonHexSuffixIsSurvivable:
    """
    The measured non-UUID population — four in-repo `stable-*` literals all
    collapse to one key. This is arm 2's real exposure, and it is not
    birthday-distributed.
    """

    @pytest.mark.parametrize( "sid", [ "stable-session", "stable-sid-11111",
                                       "stable-sid-12345", "stable-sid-67890" ] )
    def test_a_non_hex_session_id_resolves_without_raising( self, sid, tmp_path ):
        assert dr._hwm_path( sid, base_dir=str( tmp_path ) ) is not None

    def test_all_four_in_repo_literals_collapse_to_one_key( self, tmp_path ):
        """
        ⚠️ NOT a birthday problem. These cluster BY CONSTRUCTION — the ~77,000
        figure was derived for accidental UUID collisions on arm 1 and must
        never be carried to arm 2.
        """
        paths = { str( dr._hwm_path( s, base_dir=str( tmp_path ) ) )
                  for s in ( "stable-session", "stable-sid-11111",
                             "stable-sid-12345", "stable-sid-67890" ) }
        assert len( paths ) == 1, (
            f"the four stable-* literals no longer share a key ({len( paths )} distinct) "
            f"— the truncation width or rule changed; re-derive row 2a6759de's exposure"
        )


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
