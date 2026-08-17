#!/usr/bin/env python3
"""
Row 95924f2d — the generator PIN (design 2026.08.16 §2.3; Rachel's zero-diff ruling).

EXECUTOR: AI — pure import + file read, no server, no inference. :7999-class.

The point of this file is one assertion: the checked-in router prompt equals what
`router_prompt_generator.render_router_prompt()` emits right now. Hand-edit the
prompt and it goes red — THAT is the step that converts the §9 drift guard from a
detector into a preventer.

Every other test here keeps the pin honest: a control proving the equality CAN
fail (§3); the ratified held-out set (the START exemption reads as exempt, not
drift); the fail-loud order cross-check; and 100% coverage of the generator module.

Run: PYTHONPATH=src python -m pytest src/tests/unit/test_v2_router_prompt_generator.py -v
Coverage: --cov=cosa.rest.v2.router_prompt_generator --cov-branch --cov-report=term-missing
"""

import os
import tempfile
import unittest
from unittest import mock

import cosa.utils.util as cu
from cosa.rest.v2 import router_prompt_generator as gen


def _on_disk_prompt():
    return cu.get_file_as_string( cu.get_project_root() + gen.TEMPLATE_REL_PATH )


class TestGeneratorPin( unittest.TestCase ):
    """The preventer: on-disk == generated (a provable no-op on the served file)."""

    def test_on_disk_prompt_equals_generator( self ):
        """
        The checked-in prompt must equal render_router_prompt() byte-for-byte.
        Regenerate (`python -m cosa.rest.v2.router_prompt_generator`) after any
        registry change; do NOT hand-edit the file.
        """
        self.assertEqual( _on_disk_prompt(), gen.render_router_prompt() )

    def test_pin_detects_a_dropped_command( self ):
        """
        Control (§3): the equality above must be able to go RED. Drop one command
        line from the emitted text and confirm it no longer matches — so a green
        pin means agreement, not a comparison that cannot fail.
        """
        emitted   = gen.render_router_prompt()
        first_cmd = gen.speakable_commands()[ 0 ]
        mutated   = emitted.replace( f"    <command>{first_cmd}</command>\n", "", 1 )

        self.assertNotEqual( mutated, emitted )
        self.assertNotEqual( mutated, _on_disk_prompt() )


class TestRatifiedSpeakableSet( unittest.TestCase ):
    """The prompt lists exactly the 18 ratified commands; the 3 held-out stay out."""

    HELD_OUT = (
        "agent router go to bug fix expediter",
        "agent router go to test fix expediter",     # START — exempt, not drift
        "agent router go to heartbeat poker",
    )
    SPEAKABLE_AGENTIC = (
        "agent router go to deep research",
        "agent router go to podcast generator",
        "agent router go to research to podcast",
        "agent router go to presentation generator",
        "agent router go to research to presentation",
        "agent router go to claude code",
        "agent router go to swe team",
        "agent router go to test fix expediter resume",
        "agent router go to test suite",
    )

    def test_held_out_agentic_commands_are_absent( self ):
        emitted = gen.render_router_prompt()
        for command in self.HELD_OUT:
            self.assertNotIn( f"<command>{command}</command>", emitted,
                              f"held-out command leaked into the prompt: {command}" )

    def test_speakable_agentic_commands_are_present( self ):
        emitted = gen.render_router_prompt()
        for command in self.SPEAKABLE_AGENTIC:
            self.assertIn( f"<command>{command}</command>", emitted,
                           f"speakable command missing from the prompt: {command}" )

    def test_command_count_is_the_ratified_eighteen( self ):
        self.assertEqual( len( gen.speakable_commands() ), 18 )

    def test_emission_order_is_the_served_order( self ):
        """Rachel's ruling: emit in served order for a provable no-op."""
        self.assertEqual( tuple( gen.speakable_commands() ), gen._SERVED_ORDER )


class TestOrderCrossCheck( unittest.TestCase ):
    """`_SERVED_ORDER` is a presentation order guarded against the registry — it must
    fail LOUD on drift in either direction, never emit a stale order silently."""

    def test_missing_command_raises( self ):
        """A speakable command absent from _SERVED_ORDER must raise, not vanish."""
        with mock.patch.object( gen, "_SERVED_ORDER", gen._SERVED_ORDER[ :-1 ] ):
            with self.assertRaises( ValueError ) as ctx:
                gen.speakable_commands()
        self.assertIn( "order drift", str( ctx.exception ) )

    def test_extra_command_raises( self ):
        """An order entry the registry does not mark speakable must raise too."""
        with mock.patch.object( gen, "_SERVED_ORDER",
                                gen._SERVED_ORDER + ( "agent router go to nowhere", ) ):
            with self.assertRaises( ValueError ):
                gen.speakable_commands()


class TestScaffoldingSurvives( unittest.TestCase ):
    """Generation must not disturb the hand-authored scaffolding."""

    def test_voice_command_slot_is_a_literal( self ):
        """`{voice_command}` must reach the file unsubstituted for serve-time format()."""
        self.assertIn( "<voice-command>{voice_command}</voice-command>", gen.render_router_prompt() )

    def test_response_block_is_present( self ):
        emitted = gen.render_router_prompt()
        self.assertIn( "<response>", emitted )
        self.assertIn( "<command></command>", emitted )   # the empty answer slot, not a command


class TestWriter( unittest.TestCase ):
    """write_router_prompt / main — both path arms, without touching the repo file."""

    def test_write_to_explicit_path_roundtrips( self ):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join( tmp, "prompt.txt" )
            written = gen.write_router_prompt( target )
            self.assertEqual( written, target )
            with open( target ) as handle:
                self.assertEqual( handle.read(), gen.render_router_prompt() )

    def test_main_writes_the_default_path( self ):
        """
        main() resolves the default path under the project root. Redirect the root
        to a temp dir so the default-path arm is covered without rewriting the
        tracked prompt file.
        """
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs( os.path.join( tmp, "src", "conf", "prompts" ) )
            with mock.patch.object( cu, "get_project_root", return_value=tmp ):
                path = gen.main()
            self.assertEqual( path, tmp + gen.TEMPLATE_REL_PATH )
            with open( path ) as handle:
                self.assertEqual( handle.read(), gen.render_router_prompt() )


if __name__ == "__main__":
    unittest.main()
