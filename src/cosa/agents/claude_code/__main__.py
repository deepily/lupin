#!/usr/bin/env python3
"""Print this package's argument help from its registry entry.

Without this module, `python -m cosa.agents.claude_code --help` fails with
'No module named ...__main__'. The help-text cache would then store that
error as this agent's help and feed it to the extraction prompt.
The drift guard exercises this entry point through `python -m`.
"""
from cosa.agents.runtime_argument_expeditor.cli_help import run_help_for_module

run_help_for_module( __package__ )   # pragma: no cover — entrypoint, run via `python -m` in the §4 content check
