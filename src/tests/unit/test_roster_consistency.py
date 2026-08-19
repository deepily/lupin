"""
Unit tests for the manager-roster drift check (row a1a84682).

The point of this suite is NOT that the checker returns [] on a healthy env —
that is the state it will sit in forever, and a guard only ever seen passing has
not been tested. Every test below that matters PLANTS a disagreement and asserts
it is caught, including the two shapes that must stay SILENT (a one-sided
environment is the arbiter/container deployment, not drift).
"""

import os

import pytest

from lupin_cli.claude_code.hooks.lib.roster_consistency import (
    find_roster_disagreements, format_roster_drift_block,
    ROSTER_PREFIX, PREFERRED_PREFIX,
    REASON_NAMES_DIFFER, REASON_NO_ROSTER, REASON_NO_CHAIN,
)


def _env( roster=None, chain=None, extra=None ):
    """Build a synthetic environ from { project: value } maps."""
    out = dict( extra or { } )
    for project, value in ( roster or { } ).items():
        out[ f"{ROSTER_PREFIX}{project}" ] = value
    for project, value in ( chain or { } ).items():
        out[ f"{PREFERRED_PREFIX}{project}" ] = value
    return out


# ── The healthy shape: the two families agree ────────────────────────────────

class TestAgreement:

    def test_derived_chain_matches_roster( self ):
        # Exactly what start-cc-with-tmux.sh now emits: chain == "<roster>,*".
        env = _env( roster={ "LUPIN": "Mr. Radio, Cheech" },
                    chain ={ "LUPIN": "Mr. Radio, Cheech,*" } )
        assert find_roster_disagreements( env ) == [ ]

    def test_whole_live_fleet_agrees( self ):
        roster = { "LUPIN": "Mr. Radio, Cheech", "PLAN": "María",
                   "LOOKML": "Sam", "LUPIN_MOBILE": "Tiffany",
                   "SKILLS_DISTILLATION": "Sam" }
        chain  = { p: f"{v},*" for p, v in roster.items() }
        assert find_roster_disagreements( _env( roster, chain ) ) == [ ]

    def test_spelling_and_case_are_not_drift( self ):
        # canonical_persona_key collapses "Mr. Radio" / "mr radio" / "MR.RADIO".
        env = _env( roster={ "LUPIN": "Mr. Radio, Cheech" },
                    chain ={ "LUPIN": "mr radio,CHEECH,*" } )
        assert find_roster_disagreements( env ) == [ ]

    def test_unrelated_env_vars_ignored( self ):
        env = _env( roster={ "LUPIN": "Sam" }, chain={ "LUPIN": "Sam,*" },
                    extra={ "PATH": "/usr/bin", "COSA_VOICE_ROLE": "manager" } )
        assert find_roster_disagreements( env ) == [ ]


# ── PLANTED DISAGREEMENTS — the cases the guard exists for ───────────────────

class TestPlantedDrift:

    def test_the_real_2026_08_18_drift_is_caught( self ):
        # The exact pair Rick found: roster still named a retired manager while
        # the chain had moved on. Nothing failed; nothing compared them either.
        env = _env( roster={ "LUPIN": "Mr. Radio, Tiberius" },
                    chain ={ "LUPIN": "Mr. Radio,Cheech,*" } )
        found = find_roster_disagreements( env )
        assert len( found ) == 1
        assert found[ 0 ][ "project" ] == "LUPIN"
        assert found[ 0 ][ "reason" ]  == REASON_NAMES_DIFFER
        assert found[ 0 ][ "roster" ]  == [ "Mr. Radio", "Tiberius" ]
        assert found[ 0 ][ "chain" ]   == [ "Mr. Radio", "Cheech" ]

    def test_extra_name_in_chain_only( self ):
        env = _env( roster={ "LUPIN": "Mr. Radio" }, chain={ "LUPIN": "Mr. Radio,Cheech,*" } )
        found = find_roster_disagreements( env )
        assert [ f[ "reason" ] for f in found ] == [ REASON_NAMES_DIFFER ]

    def test_order_difference_is_drift( self ):
        # Order is load-bearing on BOTH sides: roster head = declared fallback
        # manager, chain is walked first-free-wins.
        env = _env( roster={ "LUPIN": "Mr. Radio, Cheech" }, chain={ "LUPIN": "Cheech,Mr. Radio,*" } )
        assert [ f[ "reason" ] for f in find_roster_disagreements( env ) ] == [ REASON_NAMES_DIFFER ]

    def test_project_with_chain_but_no_roster_line( self ):
        env = _env( roster={ "LUPIN": "Mr. Radio" },
                    chain ={ "LUPIN": "Mr. Radio,*", "SKILLS_DISTILLATION": "Sam,*" } )
        found = find_roster_disagreements( env )
        assert found == [ { "project": "SKILLS_DISTILLATION", "roster": [ ],
                            "chain": [ "Sam" ], "reason": REASON_NO_ROSTER } ]

    def test_project_with_roster_line_but_no_chain( self ):
        env = _env( roster={ "LUPIN": "Mr. Radio", "LOOKML": "Sam" },
                    chain ={ "LUPIN": "Mr. Radio,*" } )
        found = find_roster_disagreements( env )
        assert found == [ { "project": "LOOKML", "roster": [ "Sam" ],
                            "chain": [ ], "reason": REASON_NO_CHAIN } ]

    def test_wildcard_only_chain_declares_nobody( self ):
        # "*" alone is a real declaration — "reserve nobody" — and it disagrees
        # with a roster that names someone. It must not be mistaken for UNSET.
        env = _env( roster={ "LUPIN": "Mr. Radio", "LOOKML": "Sam" },
                    chain ={ "LUPIN": "Mr. Radio,*", "LOOKML": "*" } )
        found = find_roster_disagreements( env )
        assert [ ( f[ "project" ], f[ "reason" ], f[ "chain" ] ) for f in found ] == \
               [ ( "LOOKML", REASON_NAMES_DIFFER, [ ] ) ]

    def test_multiple_projects_reported_sorted( self ):
        env = _env( roster={ "ZULU": "Sam", "ALPHA": "Sam", "LUPIN": "Mr. Radio" },
                    chain ={ "ZULU": "Tiffany,*", "ALPHA": "Tiffany,*", "LUPIN": "Mr. Radio,*" } )
        assert [ f[ "project" ] for f in find_roster_disagreements( env ) ] == [ "ALPHA", "ZULU" ]


# ── Shapes that must stay SILENT (firing here would train readers to ignore) ──

class TestOneSidedEnvironmentsAreSilent:

    def test_roster_only_is_the_arbiter_shape( self ):
        # The :8001 arbiter's systemd unit loads fleet-roster.env and nothing else.
        assert find_roster_disagreements( _env( roster={ "LUPIN": "Mr. Radio, Cheech" } ) ) == [ ]

    def test_chain_only_is_a_bare_terminal( self ):
        assert find_roster_disagreements( _env( chain={ "LUPIN": "Mr. Radio,*" } ) ) == [ ]

    def test_neither_family_is_the_container_shape( self ):
        assert find_roster_disagreements( { "PATH": "/usr/bin" } ) == [ ]

    def test_blank_values_count_as_unset( self ):
        env = _env( roster={ "LUPIN": "   " }, chain={ "LUPIN": "Mr. Radio,*" } )
        assert find_roster_disagreements( env ) == [ ]

    def test_non_string_value_is_skipped( self ):
        env = _env( roster={ "LUPIN": "Mr. Radio" }, chain={ "LUPIN": "Mr. Radio,*" } )
        env[ f"{ROSTER_PREFIX}BOGUS" ] = 7
        assert find_roster_disagreements( env ) == [ ]


class TestDefaultEnviron:

    def test_none_reads_os_environ( self, monkeypatch ):
        for key in list( os.environ ):
            if key.startswith( ( ROSTER_PREFIX, PREFERRED_PREFIX ) ):
                monkeypatch.delenv( key, raising=False )
        monkeypatch.setenv( f"{ROSTER_PREFIX}LUPIN", "Mr. Radio, Tiberius" )
        monkeypatch.setenv( f"{PREFERRED_PREFIX}LUPIN", "Mr. Radio,Cheech,*" )
        found = find_roster_disagreements()
        assert [ f[ "project" ] for f in found ] == [ "LUPIN" ]


# ── The rendered block ───────────────────────────────────────────────────────

class TestRenderedBlock:

    def test_empty_findings_render_nothing( self ):
        assert format_roster_drift_block( [ ] ) == ""

    def test_block_names_both_declarations( self ):
        env   = _env( roster={ "LUPIN": "Mr. Radio, Tiberius" }, chain={ "LUPIN": "Mr. Radio,Cheech,*" } )
        block = format_roster_drift_block( find_roster_disagreements( env ) )
        assert "MANAGER ROSTER DRIFT" in block
        assert "LUPIN" in block
        assert "Mr. Radio, Tiberius" in block
        assert "Mr. Radio, Cheech"   in block
        assert "fleet-roster.env"    in block

    def test_empty_side_renders_none_marker( self ):
        env   = _env( roster={ "LUPIN": "Mr. Radio", "LOOKML": "Sam" }, chain={ "LUPIN": "Mr. Radio,*" } )
        block = format_roster_drift_block( find_roster_disagreements( env ) )
        assert "(none)" in block
        assert REASON_NO_CHAIN in block
