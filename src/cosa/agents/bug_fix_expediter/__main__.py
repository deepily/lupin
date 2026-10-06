#!/usr/bin/env python3
"""Print this package's argument help from its registry entry via `python -m`.

Running `python -m cosa.agents.bug_fix_expediter --help` names the declared args.
Without this module it fails with 'No module named ...__main__'.
get_cli_help would cache that error as this agent's help text.
The extraction prompt would then be fed that cached error.
The drift-guard content check exercises this entry point via `python -m`.
"""
from cosa.agents.runtime_argument_expeditor.cli_help import run_help_for_module

run_help_for_module( __package__ )   # pragma: no cover — entrypoint, run via `python -m` in the §4 content check
