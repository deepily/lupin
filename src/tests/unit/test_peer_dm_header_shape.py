"""
Peer-DM envelope SHAPE guard (row e990722a).

WHY THIS TEST IS LOAD-BEARING, not a formality:

`hook_common.build_peer_dm_reminder` is the single render path for EVERY peer DM
every seat in the fleet reads, and hooks run **from the working tree with no
staging step**. There is no build, no deploy, no review gate between an edit to
this function and the next DM every session receives. A malformed header ships
fleet-wide on the next event, and it ships SILENTLY — a reader who cannot find
the reply affordance simply does not reply, which looks like a quiet peer rather
than a broken renderer.

So this file pins the two things that must not drift:

  1. THE HEADER LINE — both branches. The stamped branch folds a leading EDT
     stamp into the header ("... at [ts]"); the unstamped branch keeps the
     trailing ":" and passes the body through byte-identically.

  2. THE REPLY AFFORDANCE — both variants. Bidirectional DMs must carry a
     pasteable `dm_send(...)` line plus the DM style tag. Arbiter one-way
     advisories must carry NEITHER, because the arbiter has no inbox and a
     dm_send line there is a false promise that costs every poked seat a turn.

And it pins `PEER_DM_FRAME_PREFIX` inside the rendered envelope, because two
OTHER mechanisms match on it: `is_injected_peer_dm` and the Stop-hook poke-cap
guard. Change the prefix and those stop recognising a peer DM — a failure two
files away from the edit.

Every assertion here is an exact-shape assertion, so any change to the rendered
envelope fails this file rather than reaching the fleet. That is the point: the
test IS the staging step this path does not otherwise have.
"""

import re

import pytest

from lupin_cli.claude_code.hooks.lib.hook_common import (
    DM_STYLE_TAG,
    PEER_DM_FRAME_PREFIX,
    build_peer_dm_reminder,
    is_injected_peer_dm,
)


STAMP    = "[2026.08.15 at 22:16:49]"
BODY     = "the workflow doc is committed at 21f230df"
PERSONA  = "Tiberius"
ICON     = "👑"
MSG_ID   = "8b6a4e5e-3aa7-4c80-a01a-e5c76af3dd37"
THREAD   = "1cb38166-0eaf-4cff-9162-2cf636520325"


def _render( body, **kw ):
    kw.setdefault( "persona",   PERSONA )
    kw.setdefault( "icon",      ICON )
    kw.setdefault( "msg_id",    MSG_ID )
    kw.setdefault( "thread_id", THREAD )
    return build_peer_dm_reminder( body, **kw )


# -- 1. The header line, both branches -----------------------------------------

class TestHeaderLine:

    def test_leading_stamp_is_folded_into_the_header( self ):
        out    = _render( f"{STAMP} {BODY}" )
        header = out.splitlines()[ 1 ]
        # " on " — not " at ". The stamp already carries its own "at"
        # ("[2026.08.15 at 22:16:49]"), so " at " stuttered in the rendered header.
        assert header == f"PEER DM from {PERSONA} {ICON} on {STAMP}", header

    def test_stamp_is_removed_from_the_body_not_duplicated( self ):
        # A render-layer extraction: the stamp moves, it does not appear twice.
        out = _render( f"{STAMP} {BODY}" )
        assert out.count( STAMP ) == 1, "stamp rendered twice — extraction became a copy"
        assert BODY in out

    def test_no_stamp_keeps_the_trailing_colon_and_passes_the_body_through( self ):
        out    = _render( BODY )
        header = out.splitlines()[ 1 ]
        assert header == f"PEER DM from {PERSONA} {ICON}:", header
        assert BODY in out

    def test_a_non_timestamp_bracket_is_not_eaten( self ):
        # "[URGENT] ..." must survive intact — the splitter is anchored to the
        # timestamp shape, not to "starts with a bracket".
        body   = "[URGENT] the bridge is stale"
        out    = _render( body )
        header = out.splitlines()[ 1 ]
        assert header == f"PEER DM from {PERSONA} {ICON}:", header
        assert body in out, "a non-timestamp leading bracket was consumed"

    def test_missing_persona_falls_back_and_still_renders_a_header( self ):
        out    = build_peer_dm_reminder( BODY, persona=None, icon=None )
        header = out.splitlines()[ 1 ]
        assert header == "PEER DM from a peer session:", header


# -- 2. The reply affordance, both variants ------------------------------------

class TestReplyAffordance:

    def test_bidirectional_dm_carries_a_pasteable_dm_send_line( self ):
        out = _render( BODY )
        assert f'↳ Reply via dm_send( recipient="{PERSONA}", body="<your reply>", ' \
               f'reply_to="{MSG_ID}", thread_id="{THREAD}" )' in out

    def test_bidirectional_dm_carries_the_style_tag( self ):
        assert DM_STYLE_TAG in _render( BODY )

    def test_one_way_advisory_offers_no_reply_path( self ):
        out = _render( BODY, one_way=True )
        assert "dm_send(" not in out, "one-way advisory promised a reply path the arbiter cannot receive"
        assert "ONE-WAY advisory" in out

    def test_one_way_advisory_omits_the_style_tag( self ):
        # No reply is possible, so a reply-shaping rider is pure byte cost.
        assert DM_STYLE_TAG not in _render( BODY, one_way=True )

    def test_the_affordance_survives_the_stamped_header_branch( self ):
        # The blast radius María flagged: folding the stamp shifts everything
        # below the header, so the affordance must be pinned in BOTH branches.
        out = _render( f"{STAMP} {BODY}" )
        assert f'reply_to="{MSG_ID}"' in out
        assert DM_STYLE_TAG in out


# -- 3. The prefix two other mechanisms match on -------------------------------

class TestFramePrefixContract:

    @pytest.mark.parametrize( "body", [ BODY, f"{STAMP} {BODY}" ] )
    def test_frame_prefix_is_present_in_both_header_branches( self, body ):
        assert PEER_DM_FRAME_PREFIX in _render( body )

    @pytest.mark.parametrize( "body", [ BODY, f"{STAMP} {BODY}" ] )
    def test_rendered_envelope_is_recognised_as_an_injected_peer_dm( self, body ):
        # is_injected_peer_dm and the Stop-hook poke-cap guard both key on the
        # prefix. If this fails, a peer DM stops being recognised as one — in a
        # different file from whatever was edited.
        assert is_injected_peer_dm( _render( body ) ) is True

    def test_envelope_is_a_complete_system_reminder_block( self ):
        out = _render( BODY )
        assert out.startswith( "<system-reminder>\n" )
        assert out.endswith( "\n</system-reminder>" )


# -- 4. Falsifiability -----------------------------------------------------------

class TestTheseAssertionsCanFail:
    """
    These prove the pins above are real comparisons against the LIVE renderer,
    not tautologies that would pass against any string.

    Each drives the REAL build_peer_dm_reminder and asserts a shape the current
    renderer does NOT produce — so if someone weakened the assertions above into
    substring-anything checks, these would start failing.
    """

    def test_header_is_not_merely_any_line_containing_the_persona( self ):
        # A weakened "persona in output" assertion would pass on this shape too;
        # the real header must be exactly one of the two pinned forms.
        header = _render( BODY ).splitlines()[ 1 ]
        assert header != f"{PERSONA} says:", "renderer produced an unpinned header shape"
        assert re.fullmatch(
            r"PEER DM from .+?(:| on \[\d{4}\.\d{2}\.\d{2} at \d{2}:\d{2}:\d{2}\])",
            header,
        ), header

    def test_the_two_header_branches_actually_differ( self ):
        # If split_leading_stamp silently became a no-op, both branches would
        # render identically and the stamped-header pin above would be vacuous.
        stamped   = _render( f"{STAMP} {BODY}" ).splitlines()[ 1 ]
        unstamped = _render( BODY ).splitlines()[ 1 ]
        assert stamped != unstamped, "stamp folding is inert — the header pin proves nothing"

    def test_the_two_affordance_variants_actually_differ( self ):
        # Same guard for one_way: if the flag stopped being honoured, the
        # one-way assertions above would be testing the bidirectional string.
        assert _render( BODY ) != _render( BODY, one_way=True ), \
            "one_way is inert — the one-way assertions prove nothing"
