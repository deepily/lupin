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

    def test_command_json_exists( self ):
        assert os.path.exists( COMMANDS_JSON_PATH ), (
            f"agent-router-agentic-commands.json not found: {COMMANDS_JSON_PATH}"
        )

    def test_tfe_command_registered( self ):
        with open( COMMANDS_JSON_PATH, "r" ) as f:
            commands = json.load( f )
        assert "agent router go to test fix expediter" in commands

    def test_tfe_command_has_template_file( self ):
        with open( COMMANDS_JSON_PATH, "r" ) as f:
            commands = json.load( f )
        entry = commands[ "agent router go to test fix expediter" ]
        assert "template_file" in entry
        assert "test-fix-expediter" in entry[ "template_file" ]

    def test_tfe_command_has_dry_run_conditional( self ):
        with open( COMMANDS_JSON_PATH, "r" ) as f:
            commands = json.load( f )
        entry = commands[ "agent router go to test fix expediter" ]
        cond = entry.get( "conditional_args", {} )
        assert "dry_run" in cond
        dry_run = cond[ "dry_run" ]
        assert dry_run[ "value" ] == "True"
        assert "dry run" in dry_run[ "triggers" ]

    def test_tfe_template_file_matches_command_json( self ):
        """The path referenced in commands.json resolves to the actual file."""
        with open( COMMANDS_JSON_PATH, "r" ) as f:
            commands = json.load( f )
        entry = commands[ "agent router go to test fix expediter" ]
        template_rel = entry[ "template_file" ]
        # Path is project-root-relative with a leading slash
        template_abs = cu.get_project_root() + template_rel
        assert os.path.exists( template_abs ), (
            f"Template file referenced by commands.json not found: {template_abs}"
        )
