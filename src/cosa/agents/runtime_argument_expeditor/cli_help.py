#!/usr/bin/env python3
"""
CLI --help surface for agentic packages whose `cli_module` is the PACKAGE
(2026.08.15-agent-registration-single-source.md §4, phase 3).

Three agentic packages named a `cli_module` that had no runnable entry point
(`cosa.agents.claude_code`, `…bug_fix_expediter`, `…test_fix_expediter`). Because
`get_cli_help` returns `result.stdout or result.stderr or ""` and CACHES it, the
string "No module named …__main__" became those agents' cached help text and was
injected into the phi4 argument-extraction prompt — extraction ran against an error
message.

This builds each package's `python -m <pkg> --help` output FROM its registry entry,
so the help NAMES the command's declared arguments and stays in sync with the arg
spec by construction — it cannot drift into a stub that merely exits 0. Each
package's `__main__.py` is two lines that call `run_help_for_module( __package__ )`.
"""

import argparse

from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS


def build_parser( command_key ):
    """
    Build an argparse parser for an agentic command from its AGENTIC_AGENTS entry.

    Requires:
        - command_key is a key of AGENTIC_AGENTS

    Ensures:
        - Every declared required_user_arg is a REQUIRED --option whose dest is the
          raw arg name, so `--help` prints the name (as metavar) and its description
        - arg_mapping targets not already required are added as optional --options
        - The parser's --help names each declared required argument
    """
    entry     = AGENTIC_AGENTS[ command_key ]
    parser    = argparse.ArgumentParser(
        prog        = command_key,
        description = f"{entry.get( 'display_name' ) or command_key}: argument surface for the runtime argument expeditor.",
    )
    required  = list( entry.get( "required_user_args", [] ) )
    optional  = [ a for a in dict.fromkeys( entry.get( "arg_mapping", {} ).values() ) if a not in required ]
    questions = entry.get( "fallback_questions", {} )
    for name in required + optional:
        parser.add_argument(
            "--" + name.replace( "_", "-" ),
            dest     = name,
            required = name in required,
            help     = f"{name}: " + questions.get( name, f"the {name} argument" ),
        )
    return parser


def run_help_for_module( module_name, argv=None ):
    """
    Find the agentic command whose cli_module is `module_name` and parse its args.

    Requires:
        - module_name is the dotted package name of a `__main__.py` caller
          (pass `__package__`)

    Ensures:
        - Parses argv (or sys.argv[1:] when None) with that command's parser; `--help`
          prints usage naming the declared args and exits 0
        - Raises SystemExit with a clear message when no command names this module
    """
    for command_key, entry in AGENTIC_AGENTS.items():
        if entry.get( "cli_module" ) == module_name:
            build_parser( command_key ).parse_args( argv )
            return
    raise SystemExit( f"no agentic command registered for cli_module {module_name!r}" )
