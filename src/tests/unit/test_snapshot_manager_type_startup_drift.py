#!/usr/bin/env python3
"""
Drift guard: every `solution snapshots manager type` value the INI ships must be a
value the STARTUP block in src/lupin_app/main.py actually accepts.

THE DEFECT THIS EXISTS FOR (2026-08-17, row 5ff7b8f5). The factory and the startup
block are two independent authorities on the same key. The factory learned
`postgres`; main.py had not, and its else-arm raised
"only lancedb solution snapshot type supported" for everything else. So the dev key
was flipped to a value the factory built happily and startup rejected — latent,
because uvicorn reload is off and the running process still held the pre-flip
config. The next bounce would have failed the server. Nothing in either unit suite
touched main.py's startup block, which is why it took a human reader to catch.

This test reads the ACCEPTED SET out of main.py's source rather than restating it,
so adding a branch there cannot leave this guard behind, and deleting one cannot
leave the INI pointing at a value nothing accepts.

Created: 2026-08-17 (Cheech, after Rachel flagged main.py:698)
"""
import configparser
import os
import re
import sys
import unittest
from pathlib import Path

# Bootstrap
_LUPIN_ROOT = Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) )
_src_path   = str( _LUPIN_ROOT / "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

_MAIN_PY   = _LUPIN_ROOT / "src" / "lupin_app" / "main.py"
_INI       = _LUPIN_ROOT / "src" / "conf" / "lupin-app.ini"
_SPLAINER  = _LUPIN_ROOT / "src" / "conf" / "lupin-app-splainer.ini"
_KEY       = "solution snapshots manager type"


def _startup_accepted_types():
    """
    Extract the manager-type literals main.py's startup block compares against.

    Ensures:
        - returns the set of lower-cased literals from `manager_type.lower() == "<x>"`
        - an empty result means the pattern moved and this guard has gone blind,
          which the first test below reports as a failure rather than a pass
        - the literal class admits DIGITS, so the guard cannot go PARTIALLY blind. The
          empty case above is already handled; a narrower class fails differently and
          worse — it returns a non-empty set that is silently short, so the
          gone-blind check passes while the drift check covers less than it claims

    ⚠️ LATENT, NOT A LIVE DEFECT — stated plainly because the distinction is the point.
    The only literal in `main.py` today is `"postgres"`, so widening `[a-z_]+` to
    `[a-z0-9_]+` changes nothing right now: measured both ways, the extracted set is
    `{"postgres"}` either side. It is worth the character anyway because the cost is one
    character and the failure is silent — a value like `postgres2` or `pg_v2` would be
    dropped without the guard noticing, since it only watches for EMPTY.

    Found 2026-09-01 by sweeping for the shape behind `gate_reachability`'s
    `_SUITE_SCRIPT_RE`, which really had dropped two keys (`e2e`, `v2_eval`). ⚠️ AND THIS
    ONE WAS HIDDEN BY MY OWN SWEEP'S FILTER: I excluded candidate lines whose text
    mentioned `slug|persona|ident|…`, which is name-based narrowing — the exact move that
    hides cases. Six lines were filtered out that way and this was among them.
    """
    source = _MAIN_PY.read_text()
    return set( re.findall( r'manager_type\.lower\(\)\s*==\s*"([a-z0-9_]+)"', source ) )


def _configured_types():
    """
    Every value the shipped INI assigns to the key, per section.

    Ensures:
        - returns { section_name: value } for each section that sets the key
    """
    parser = configparser.ConfigParser( interpolation=None )
    parser.read( _INI )
    return { section: parser.get( section, _KEY )
             for section in parser.sections() if parser.has_option( section, _KEY ) }


class TestStartupAcceptsEveryShippedValue( unittest.TestCase ):
    """The INI and main.py must agree — in both directions."""

    def test_startup_pattern_still_parses( self ):
        # If this fails, the comparison in main.py was rewritten and the guard below
        # would silently pass on an empty set.
        self.assertTrue( _startup_accepted_types(),
                         f"no `manager_type.lower() == \"...\"` comparisons found in {_MAIN_PY}" )

    def test_every_configured_value_is_accepted_at_startup( self ):
        accepted   = _startup_accepted_types()
        configured = _configured_types()
        self.assertTrue( configured, f"no section of {_INI} sets '{_KEY}'" )
        for section, value in configured.items():
            self.assertIn(
                value.lower(), accepted,
                f"[{section}] {_KEY} = {value!r}, which main.py's startup block "
                f"rejects — it accepts only {sorted( accepted )}. The server would "
                f"fail on its next bounce."
            )

    def test_every_configured_value_is_buildable_by_the_factory( self ):
        # The other authority on the same key. Both must accept it, not just one.
        from cosa.memory.solution_manager_factory import ManagerType
        for section, value in _configured_types().items():
            try:
                ManagerType.from_string( value )
            except ValueError as e:                              # pragma: no cover - only on drift
                self.fail( f"[{section}] {_KEY} = {value!r} is not a ManagerType: {e}" )

    def test_startup_accepted_values_are_all_real_manager_types( self ):
        # Reverse direction: a branch in main.py for a type the factory dropped would
        # build nothing. Catches the deletion half of the same drift.
        from cosa.memory.solution_manager_factory import ManagerType
        known = { member.value for member in ManagerType }
        for value in _startup_accepted_types():
            self.assertIn( value, known,
                           f"main.py accepts {value!r} but ManagerType has no such member" )


class TestKeysAreDocumented( unittest.TestCase ):
    """The splainer mandate, enforced rather than remembered."""

    def test_manager_type_and_postgres_table_keys_have_splainer_entries( self ):
        splainer = configparser.ConfigParser( interpolation=None )
        splainer.read( _SPLAINER )
        documented = { option for section in splainer.sections() for option in splainer.options( section ) }
        documented |= set( splainer.defaults() )
        for key in ( _KEY, "solution snapshots postgres table" ):
            self.assertIn( key, documented, f"'{key}' ships without a splainer entry" )


if __name__ == "__main__":
    unittest.main()
