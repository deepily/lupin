#!/usr/bin/env python3
"""
Unit tests for SWE Team LORA training data validation.

Tests:
    - File existence and non-empty content
    - Minimum utterance count (>= 50)
    - No duplicate lines
    - Agent keyword coverage (canonical + ASR variants)
    - FEATURE placeholder coverage (>= 80%)
    - Line length limit (<= 200 chars)
    - Router config entry presence
    - No overlap with other agent routing files
"""

import json
import os
import pytest

import cosa.utils.util as cu


# ============================================================================
# Constants
# ============================================================================

TRAINING_DATA_PATH = "/src/ephemera/prompts/data/synthetic-data-agent-routing-swe-team.txt"
ROUTER_CONFIG_PATH = "/src/conf/training/agent-router-agentic-commands.json"
TRAINING_DATA_DIR  = "/src/ephemera/prompts/data"

# Expanded keyword set — canonical + synonyms + ASR near-misses
VALID_KEYWORDS = [
    "swe",                # canonical
    "sweet",              # ASR: phonetic match
    "suite",              # ASR: phonetic match
    "sway",               # ASR: vowel shift
    "swee",               # ASR: elongated
    "s w e",              # ASR: spelled out
    "s.w.e.",             # ASR: spelled out with periods
    "engineering team",   # synonym
    "software team",      # synonym
    "dev team",           # synonym
]


# ============================================================================
# Helpers
# ============================================================================

def _load_utterances():
    """
    Load non-empty, non-comment lines from the training data file.

    Requires:
        - Training data file exists at TRAINING_DATA_PATH

    Ensures:
        - Returns list of stripped, non-empty, non-comment lines
    """
    path = cu.get_project_root() + TRAINING_DATA_PATH
    with open( path, "r" ) as f:
        lines = [ line.strip() for line in f if line.strip() and not line.strip().startswith( "#" ) ]
    return lines


def _load_other_training_files():
    """
    Load all other synthetic-data-agent-routing-*.txt files.

    Requires:
        - Training data directory exists

    Ensures:
        - Returns set of all lines from other agent routing files (excluding SWE team)
    """
    data_dir   = cu.get_project_root() + TRAINING_DATA_DIR
    other_lines = set()

    for filename in os.listdir( data_dir ):
        if filename.startswith( "synthetic-data-agent-routing-" ) and filename.endswith( ".txt" ):
            if filename == "synthetic-data-agent-routing-swe-team.txt":
                continue
            filepath = os.path.join( data_dir, filename )
            with open( filepath, "r" ) as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith( "#" ):
                        other_lines.add( stripped.lower() )

    return other_lines


# ============================================================================
# Tests
# ============================================================================

class TestSweTeamTrainingData:
    """Validation tests for SWE Team LORA training data."""

    def test_file_exists( self ):
        """Training data file exists and is non-empty."""
        path = cu.get_project_root() + TRAINING_DATA_PATH
        assert os.path.exists( path ), f"File not found: {path}"
        assert os.path.getsize( path ) > 0, f"File is empty: {path}"

    def test_minimum_count( self ):
        """At least 50 utterances in the file."""
        lines = _load_utterances()
        assert len( lines ) >= 50, f"Expected >= 50 utterances, got {len( lines )}"

    def test_no_duplicates( self ):
        """No duplicate lines in the file."""
        lines   = _load_utterances()
        seen    = set()
        dupes   = []
        for line in lines:
            lower = line.lower()
            if lower in seen:
                dupes.append( line )
            seen.add( lower )
        assert len( dupes ) == 0, f"Found {len( dupes )} duplicate(s): {dupes}"

    def test_agent_keyword_present( self ):
        """Every line contains at least one recognized keyword from VALID_KEYWORDS."""
        lines   = _load_utterances()
        missing = []
        for line in lines:
            lower = line.lower()
            if not any( kw in lower for kw in VALID_KEYWORDS ):
                missing.append( line )
        assert len( missing ) == 0, \
            f"{len( missing )} line(s) missing keywords:\n" + "\n".join( f"  -> {m}" for m in missing )

    def test_placeholder_coverage( self ):
        """FEATURE placeholder appears in >= 80% of lines."""
        lines         = _load_utterances()
        feature_count = sum( 1 for line in lines if "FEATURE" in line )
        coverage      = feature_count / len( lines ) if lines else 0
        assert coverage >= 0.80, \
            f"FEATURE placeholder coverage {coverage:.1%} < 80% ({feature_count}/{len( lines )})"

    def test_line_length( self ):
        """No line exceeds 200 characters."""
        lines     = _load_utterances()
        too_long  = [ ( i + 1, line ) for i, line in enumerate( lines ) if len( line ) > 200 ]
        assert len( too_long ) == 0, \
            f"{len( too_long )} line(s) exceed 200 chars: {too_long}"

    def test_router_config_entry( self ):
        """Router config contains SWE Team entry with enriched structure pointing to a valid file."""
        config_path = cu.get_project_root() + ROUTER_CONFIG_PATH
        with open( config_path, "r" ) as f:
            config = json.load( f )

        assert "agent router go to swe team" in config, \
            "Missing 'agent router go to swe team' in router config"

        entry = config[ "agent router go to swe team" ]

        # Enriched structure validation
        for key in ( "template_file", "placeholders", "args_key" ):
            assert key in entry, f"SWE Team config missing required key: '{key}'"

        assert isinstance( entry[ "placeholders" ], dict ), "placeholders must be a dict"
        assert len( entry[ "placeholders" ] ) > 0, "placeholders must not be empty"

        data_path = cu.get_project_root() + entry[ "template_file" ]
        assert os.path.exists( data_path ), f"Router config points to missing file: {data_path}"

    def test_no_overlap_with_other_files( self ):
        """No lines shared with other synthetic-data-agent-routing-*.txt files."""
        swe_lines   = { line.lower() for line in _load_utterances() }
        other_lines = _load_other_training_files()
        overlap     = swe_lines & other_lines
        assert len( overlap ) == 0, \
            f"{len( overlap )} overlapping line(s) with other training files:\n" + \
            "\n".join( f"  -> {o}" for o in sorted( overlap ) )


# ============================================================================
# Config-driven pipeline validation tests
# ============================================================================

REQUIRED_CONFIG_KEYS = { "template_file", "placeholders", "args_key" }
VALID_GETTER_NAMES   = { "research_topics", "document_paths", "claude_code_tasks" }


def _load_full_config():
    """Load the full agentic commands config."""
    config_path = cu.get_project_root() + ROUTER_CONFIG_PATH
    with open( config_path, "r" ) as f:
        return json.load( f )


class TestAgenticCommandsConfig:
    """Validation tests for the enriched agentic commands config."""

    def test_all_config_entries_have_required_keys( self ):
        """Every entry in the JSON config has template_file, placeholders, and args_key."""
        config  = _load_full_config()
        missing = {}
        for command_name, entry in config.items():
            absent = REQUIRED_CONFIG_KEYS - set( entry.keys() )
            if absent:
                missing[ command_name ] = absent
        assert len( missing ) == 0, \
            f"Entries missing required keys:\n" + \
            "\n".join( f"  {cmd}: {keys}" for cmd, keys in missing.items() )

    def test_all_config_template_files_exist( self ):
        """Every template_file path in the config resolves to an existing file."""
        config    = _load_full_config()
        not_found = []
        for command_name, entry in config.items():
            full_path = cu.get_project_root() + entry[ "template_file" ]
            if not os.path.exists( full_path ):
                not_found.append( f"{command_name} -> {full_path}" )
        assert len( not_found ) == 0, \
            f"Template files not found:\n" + "\n".join( f"  {nf}" for nf in not_found )

    def test_all_config_placeholder_getters_valid( self ):
        """Every getter name in placeholders is in the known valid set."""
        config  = _load_full_config()
        invalid = {}
        for command_name, entry in config.items():
            for placeholder, getter_name in entry[ "placeholders" ].items():
                if getter_name not in VALID_GETTER_NAMES:
                    invalid[ f"{command_name}.{placeholder}" ] = getter_name
        assert len( invalid ) == 0, \
            f"Unknown getter names:\n" + \
            "\n".join( f"  {k}: '{v}' (valid: {VALID_GETTER_NAMES})" for k, v in invalid.items() )


# ============================================================================
# Run inline if needed
# ============================================================================

if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
