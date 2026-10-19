"""
Unit tests for cosa.repo.cli_common and the two runners that use it.

The helper adds five options to an analyzer parser. The two tables below were read off the
parsers as they were before the helper existed. A change to a default, a choice or a help
sentence in either runner fails here.
"""

import argparse

import pytest

import cosa.repo.run_branch_analyzer as rba
import cosa.repo.run_directory_analyzer as rda
from cosa.repo.cli_common import add_common_output_args


def _table( parser ):
    """Ensures: returns one tuple per action, in order: strings, default, choices, metavar, help."""
    return [ ( tuple( a.option_strings ), a.default, None if a.choices is None else list( a.choices ), a.metavar, a.help ) for a in parser._actions ]


BRANCH_TABLE = [
    ( ( "-h", "--help" ),    "==SUPPRESS==", None, None, "show this help message and exit" ),
    ( ( "--repo-path", ),    ".",   None, "PATH",   "Path to git repository to analyze (default: . = current directory)" ),
    ( ( "--base", ),         None,  None, "BRANCH", "Base branch for comparison - what you are comparing FROM (default: main)" ),
    ( ( "--head", ),         None,  None, "BRANCH", "Head branch for comparison - what you are comparing TO (default: HEAD = current branch, auto-resolved to actual name)" ),
    ( ( "--config", ),       None,  None, "FILE",   "Configuration file path (default: embedded default_config.yaml)" ),
    ( ( "--output", ),       None,  [ "console", "json", "markdown" ], "FORMAT", "Output format: console, json, markdown (default: console from config)" ),
    ( ( "--save-output", ),  None,  None, "FILE",   "Save output to file instead of printing to stdout" ),
    ( ( "--verbose", "-v" ), False, None, None,     "Verbose output (show progress and details)" ),
    ( ( "--debug", "-d" ),   False, None, None,     "Debug mode (show internal operations)" ),
]

DIRECTORY_TABLE = [
    ( ( "-h", "--help" ),    "==SUPPRESS==", None, None, "show this help message and exit" ),
    ( ( "--path", ),         ".",   None, "PATH",   "Directory to analyze (default: . = current directory)" ),
    ( ( "--config", ),       None,  None, "FILE",   "Configuration file path (default: embedded default_config.yaml)" ),
    ( ( "--output", ),       "console", [ "console", "json", "markdown" ], "FORMAT", "Output format: console, json, markdown (default: console)" ),
    ( ( "--save-output", ),  None,  None, "FILE",   "Save output to file instead of printing to stdout" ),
    ( ( "--verbose", "-v" ), False, None, None,     "Verbose output (show progress)" ),
    ( ( "--debug", "-d" ),   False, None, None,     "Debug mode (show internal operations)" ),
]


def test_the_branch_runner_parser_is_unchanged():
    """Ensures: the branch runner matches the table read before the helper existed."""
    assert _table( rba.create_parser() ) == BRANCH_TABLE


def test_the_directory_runner_parser_is_unchanged():
    """Ensures: the directory runner matches the table read before the helper existed."""
    assert _table( rda.create_parser() ) == DIRECTORY_TABLE


def test_the_helper_adds_five_options_after_the_callers_own_and_passes_its_three_parameters_through():
    """Ensures: the three parameters land on --output and --verbose; the rest are fixed."""
    parser = argparse.ArgumentParser()
    parser.add_argument( "--mine" )
    add_common_output_args( parser, output_default="json", output_help="OUT", verbose_help="VERB" )
    table = _table( parser )
    assert [ t[ 0 ][ 0 ] for t in table ] == [ "-h", "--mine", "--config", "--output", "--save-output", "--verbose", "--debug" ]
    assert table[ 3 ][ 1 ] == "json" and table[ 3 ][ 4 ] == "OUT" and table[ 5 ][ 4 ] == "VERB"
    assert parser.parse_args( [ "-v", "-d" ] ).verbose is True


def test_the_helper_refuses_an_output_format_outside_its_three():
    """Raises: SystemExit from argparse for --output xml."""
    parser = argparse.ArgumentParser()
    add_common_output_args( parser, None, "o", "v" )
    with pytest.raises( SystemExit ):
        parser.parse_args( [ "--output", "xml" ] )
