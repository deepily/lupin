"""
Command-line arguments shared by the repo analyzer runners.

run_branch_analyzer and run_directory_analyzer take the same five options after their own
path arguments. They are a configuration file, an output format, a file to save to, and the
verbose and debug switches. Only the output default and two help sentences differ.
"""

import argparse


def add_common_output_args( parser: argparse.ArgumentParser, output_default, output_help: str, verbose_help: str ) -> None:
    """
    Add --config, --output, --save-output, --verbose and --debug to an analyzer parser.

    Requires:
        - parser is an argparse.ArgumentParser the caller has already given its own path arguments
        - output_default is the default for --output: None to defer to the config file, or a format name
        - output_help and verbose_help are the help sentences for --output and --verbose

    Ensures:
        - the five options are added in that order, after the caller's own arguments
        - --output accepts console, json or markdown only
        - nothing else on the parser changes
    """
    parser.add_argument(
        '--config',
        type    = str,
        default = None,
        metavar = 'FILE',
        help    = 'Configuration file path (default: embedded default_config.yaml)'
    )
    parser.add_argument(
        '--output',
        type    = str,
        choices = ['console', 'json', 'markdown'],
        default = output_default,
        metavar = 'FORMAT',
        help    = output_help
    )
    parser.add_argument(
        '--save-output',
        type    = str,
        default = None,
        metavar = 'FILE',
        help    = 'Save output to file instead of printing to stdout'
    )
    parser.add_argument(
        '--verbose', '-v',
        action  = 'store_true',
        help    = verbose_help
    )
    parser.add_argument(
        '--debug', '-d',
        action  = 'store_true',
        help    = 'Debug mode (show internal operations)'
    )
