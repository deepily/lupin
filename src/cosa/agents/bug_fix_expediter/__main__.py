#!/usr/bin/env python3
"""Runnable --help surface (design §4, phase 3): builds this package's argument
help from its registry entry so `python -m cosa.agents.bug_fix_expediter --help`
names the declared args instead of failing with 'No module named …__main__' (which
get_cli_help would cache as this agent's help text and feed to the extraction
prompt). Exercised via `python -m` in the drift-guard §4 content check."""
from cosa.agents.runtime_argument_expeditor.cli_help import run_help_for_module

run_help_for_module( __package__ )   # pragma: no cover — entrypoint, run via `python -m` in the §4 content check
