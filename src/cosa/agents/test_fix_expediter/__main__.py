#!/usr/bin/env python3
"""Runnable --help surface: builds the package's argument help from its registry entry.

`python -m cosa.agents.test_fix_expediter --help` then names the declared args.
Without this file it fails with "No module named ...__main__", which get_cli_help
would cache as this agent's help text and feed to the extraction prompt.
The drift-guard content check exercises it via `python -m`."""
from cosa.agents.runtime_argument_expeditor.cli_help import run_help_for_module

run_help_for_module( __package__ )   # pragma: no cover — entrypoint, run via `python -m` in the §4 content check
