#!/usr/bin/env python3
"""
Rename-consistency guard for the OUTCOME_POKE value rename ("poked", 2026-06-09).

Pins the §5 acceptance of the Stop-hook speakerphone poke-fix brief
(src/rnd/v0.1.8/2026.06.04-heartbeat-hook/2026.06.09-stop-hook-speakerphone-
poke-fix-and-poked-rename.md):

  1. The contract VALUE is exactly "poked" (the ONE name, everywhere).
  2. Production consumers reference the constant — the arbiter outcome→state
     map keys on OUTCOME_POKE and maps it to "working"; the old "poke" key is
     gone (a stale key would silently stop mapping poked workers to working).
  3. ZERO production literal-"poke" survivors: a repo grep over the production
     surfaces (hooks lib + arbiter + the watcher script) finds no quoted
     "poke" literal. Excludes the compound identifiers (poke_cap, poke_count,
     _poke, poker, …) by construction — the regex requires quotes around the
     bare word.

No legacy alias, no migration (Rick's no-migration + no-alias rules): old
on-disk events carrying the pre-rename value age out of consumer read windows.

Venue: :7999-eligible / local — pure reads, sub-second.
"""
import os
import re
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.heartbeat_decision import OUTCOME_POKE
from lupin_cli.claude_code.hooks.lib import heartbeat_events
from cosa.agents.heartbeat_arbiter.fleet_data_model import _STATE_BY_OUTCOME


# Production surfaces that consume heartbeat outcome values (repo-relative).
_PRODUCTION_SURFACES = (
    "src/lupin_cli/claude_code/hooks",
    "src/cosa/agents/heartbeat_arbiter",
    "src/scripts/watch-hook-events.py",
)

# A quoted bare-"poke" literal. The quotes exclude poke_cap / poke_count /
# _poke / poker / "poked" etc. by construction.
_LITERAL_POKE = re.compile( r"""["']poke["']""" )


def _repo_root():
    return os.environ.get( "LUPIN_ROOT", os.getcwd() )


def _iter_production_files():
    for surface in _PRODUCTION_SURFACES:
        path = os.path.join( _repo_root(), surface )
        if os.path.isfile( path ):
            yield path
        else:
            for dirpath, _dirnames, filenames in os.walk( path ):
                for name in filenames:
                    if name.endswith( ".py" ):
                        yield os.path.join( dirpath, name )


class TestPokedValueContract:

    def test_outcome_poke_value_is_poked( self ):
        """The ONE name: the constant's value is exactly 'poked'."""
        assert OUTCOME_POKE == "poked"

    def test_emitted_outcomes_carry_poked( self ):
        """heartbeat_events' emit whitelist rides the constant (not a literal)."""
        assert "poked" in heartbeat_events.EMITTED_OUTCOMES
        assert "poke" not in heartbeat_events.EMITTED_OUTCOMES


class TestArbiterMapConsistency:

    def test_poked_maps_to_working( self ):
        """The CRITICAL §5 consumer: a poked worker must read as 'working'."""
        assert _STATE_BY_OUTCOME[ OUTCOME_POKE ] == "working"
        assert _STATE_BY_OUTCOME[ "poked" ]      == "working"

    def test_stale_poke_key_is_gone( self ):
        """A surviving 'poke' key would silently mismap post-rename events."""
        assert "poke" not in _STATE_BY_OUTCOME


class TestZeroProductionLiteralSurvivors:

    def test_grep_zero_quoted_poke_in_production_surfaces( self ):
        """§5 acceptance: no quoted bare-'poke' literal on any production
        surface (consumers reference OUTCOME_POKE, so future renames ride
        free)."""
        survivors = [ ]
        for path in _iter_production_files():
            try:
                with open( path, encoding="utf-8" ) as f:
                    for lineno, line in enumerate( f, start=1 ):
                        if _LITERAL_POKE.search( line ):
                            rel = os.path.relpath( path, _repo_root() )
                            survivors.append( f"{rel}:{lineno}: {line.strip()}" )
            except OSError:                                  # pragma: no cover - unreadable file ⇒ skip, never fail the guard on IO
                continue
        assert survivors == [ ], (
            "Production literal-\"poke\" survivors found (must reference "
            "OUTCOME_POKE / carry the 'poked' value):\n" + "\n".join( survivors )
        )


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
