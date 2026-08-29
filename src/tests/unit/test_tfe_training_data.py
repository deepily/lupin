"""
Unit tests for TFE PEFT voice-routing training data.

Session 1cfcdf73 (2026-04-10): Step 17 validation tests. Verifies that
the training template file exists with enough examples, the command is
registered in the agent-router-agentic-commands.json registry, and the
template content covers the categories documented in plan doc 13.
"""

import json
import os

import pytest

import cosa.utils.util as cu


TEMPLATE_PATH = os.path.join(
    cu.get_project_root(),
    "src", "ephemera", "prompts", "data",
    "synthetic-data-agent-routing-test-fix-expediter.txt",
)

COMMANDS_JSON_PATH = os.path.join(
    cu.get_project_root(),
    "src", "conf", "training", "agent-router-agentic-commands.json",
)


class TestTemplateFile:

    def test_template_file_exists( self ):
        assert os.path.exists( TEMPLATE_PATH ), (
            f"Training template file not found: {TEMPLATE_PATH}"
        )

    def test_template_file_nonempty( self ):
        with open( TEMPLATE_PATH, "r" ) as f:
            lines = [ l.strip() for l in f if l.strip() and not l.strip().startswith( "#" ) ]
        assert len( lines ) >= 65, (
            f"Need at least 65 training templates per plan doc 13; "
            f"got {len( lines )}"
        )

    def test_template_file_no_duplicates( self ):
        with open( TEMPLATE_PATH, "r" ) as f:
            lines = [ l.strip() for l in f if l.strip() and not l.strip().startswith( "#" ) ]
        seen = set()
        dupes = []
        for line in lines:
            if line in seen:
                dupes.append( line )
            seen.add( line )
        assert not dupes, f"Duplicate template entries: {dupes}"

    def test_template_covers_direct_commands( self ):
        """Category 1: direct commands like 'run the test fix expediter'."""
        with open( TEMPLATE_PATH, "r" ) as f:
            content = f.read().lower()
        assert "run the test fix expediter" in content
        assert "launch" in content
        assert "execute" in content
        assert "start" in content

    def test_template_covers_conversational( self ):
        """Category 3: polite/conversational phrasings."""
        with open( TEMPLATE_PATH, "r" ) as f:
            content = f.read().lower()
        assert "please" in content
        assert "can you" in content or "could you" in content

    def test_template_covers_goal_oriented( self ):
        """Category 4: goal-oriented / indirect phrasings."""
        with open( TEMPLATE_PATH, "r" ) as f:
            content = f.read().lower()
        assert "i want" in content or "i need" in content or "i'd like" in content

    def test_template_covers_dry_run_triggers( self ):
        """Dry-run trigger phrases used by conditional_args in commands JSON."""
        with open( TEMPLATE_PATH, "r" ) as f:
            content = f.read().lower()
        # At least one of the dry-run triggers should appear in the templates
        assert "dry run" in content or "dry-run" in content


class TestCommandRegistration:
    """
    The START command "agent router go to test fix expediter" is INTENTIONALLY
    ABSENT from the training corpus (agent-router-agentic-commands.json).

    Decision e5a840c9 (Rachel-approved, executed by commit 14a44cf4) dropped the
    START key from the corpus on purpose: START is SYSTEM-TRIGGERED, not spoken.
    The test-suite completion watchdog fires it at
    src/cosa/rest/test_suite_completion_watchdog.py:259, and it is dispatched at
    runtime by agentic_job_factory.py:327 — nothing reads the training corpus at
    runtime. Its only argument is a non-speakable job id, and it is exempt from the
    served command menu, so a retrain must NOT be taught to emit it. The distinct
    "...resume" key is a separate, speakable command and remains registered.

    These tests were STALE — they asserted START was still registered and failed
    once the key was dropped. They are inverted (presence -> absence), NOT deleted:
    a deleted test is indistinguishable from one that never existed, so the next
    person to re-add the START key must hit RED here, not silence. Each assertion
    fires the instant the bare START key reappears in the corpus, in any shape.
    Menu/row-level absence is pinned separately in
    src/cosa/tests/unit/training/test_agent_router_corpus_roster.py.
    """

    START_COMMAND  = "agent router go to test fix expediter"
    START_TEMPLATE = "synthetic-data-agent-routing-test-fix-expediter.txt"

    def test_command_json_exists( self ):
        assert os.path.exists( COMMANDS_JSON_PATH ), (
            f"agent-router-agentic-commands.json not found: {COMMANDS_JSON_PATH}"
        )

    def test_tfe_start_command_not_registered( self ):
        """e5a840c9: the START key must NOT be a corpus command. Re-adding it fails here."""
        with open( COMMANDS_JSON_PATH, "r" ) as f:
            commands = json.load( f )
        assert self.START_COMMAND not in commands, (
            f"START key '{self.START_COMMAND}' is system-triggered (watchdog:259) and "
            f"must stay OUT of the training corpus — see e5a840c9. Do not re-add it."
        )

    def test_tfe_start_command_has_no_entry( self ):
        """Belt to the suspenders: even an empty-dict re-add of the START key fails."""
        with open( COMMANDS_JSON_PATH, "r" ) as f:
            commands = json.load( f )
        assert commands.get( self.START_COMMAND ) is None, (
            f"START key '{self.START_COMMAND}' must have NO registry entry (e5a840c9)."
        )

    def test_only_the_resume_variant_of_tfe_is_registered( self ):
        """
        Of the TFE-prefixed keys, ONLY the speakable '...resume' command survives;
        the bare START key does not. A re-add makes this list len 2 -> RED.
        """
        with open( COMMANDS_JSON_PATH, "r" ) as f:
            commands = json.load( f )
        tfe_keys = sorted( k for k in commands if k.startswith( "agent router go to test fix expediter" ) )
        assert tfe_keys == [ "agent router go to test fix expediter resume" ], (
            f"Expected only the '...resume' TFE key; got {tfe_keys} (e5a840c9)."
        )

    def test_start_template_not_wired_into_corpus( self ):
        """
        No corpus entry may reference the bare START template file — dropping the key
        removed its training examples, which is the point (roster test docstring).
        The START template file may still exist on disk; it just is not corpus-wired.
        """
        with open( COMMANDS_JSON_PATH, "r" ) as f:
            commands = json.load( f )
        wired = [
            k for k, entry in commands.items()
            if os.path.basename( entry.get( "template_file", "" ) ) == self.START_TEMPLATE
        ]
        assert not wired, (
            f"START template '{self.START_TEMPLATE}' is wired into corpus keys {wired}; "
            f"START trains no examples (e5a840c9)."
        )
