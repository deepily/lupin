"""
Runners for ruff, markdownlint-cli2 and the Dart analyzer.

Each runner returns ( findings, warnings ). A tool that is not installed yields no findings and
one loud warning that names what was not checked; it never passes silently, because a gate
that skips quietly looks the same as a gate that passed.
"""

import json
import os
import re
import shutil
import subprocess

from .text_rules import Finding

RUFF_RELATIVE     = [ ".venv/bin/ruff" ]
MARKDOWNLINT_LINE = re.compile( r"^(.+?):(\d+)(?::\d+)? (?:error|warning) (MD\d+/[\w-]+) (.*)$" )
DART_DOC_CODES    = frozenset( { "public_member_api_docs", "slash_for_doc_comments", "dangling_library_doc_comments",
                                 "unintended_html_in_doc_comment", "comment_references" } )


def find_tool( root, relative_candidates, name, env_var ):
    """
    Locate an external tool.

    Requires:
        - root is the repo working tree
        - relative_candidates are paths under root to try first

    Ensures:
        - returns the first of: the env_var override, a candidate under root, the name on the search path
        - returns None when none exists

    Raises:
        - nothing
    """
    override = os.environ.get( env_var )
    if override and os.path.exists( override ): return override
    for rel in relative_candidates:
        full = os.path.join( root, rel )
        if os.path.exists( full ): return full
    return shutil.which( name )


def missing_tool_warning( tool, unchecked ):
    """
    Build the loud line printed when a tool is absent.

    Requires:
        - tool names the missing tool; unchecked says what therefore went unchecked

    Ensures:
        - the line starts with the doc-lint warning prefix and says the check was skipped

    Raises:
        - nothing
    """
    return f"[doc-lint] WARNING: {tool} not found, SKIPPED: {unchecked} were NOT checked"


def run_ruff( root, paths, runner=subprocess.run, sources=None ):
    """
    Run ruff's docstring rules over Python files, with the pinned config in pyproject.toml.

    Requires:
        - paths are repo-relative .py files
        - runner has the signature of subprocess.run
        - sources, when given, maps each path to the text to check (the staged content); ruff
          then reads it from stdin instead of reading the working-tree file

    Ensures:
        - returns ( findings, warnings ); findings carry the rule as ruff:<code>
        - a missing ruff yields one warning and no findings
        - an exit status other than 0 or 1 yields one warning carrying ruff's stderr

    Raises:
        - nothing
    """
    if not paths: return [], []
    tool = find_tool( root, RUFF_RELATIVE, "ruff", "LUPIN_RUFF" )
    if tool is None: return [], [ missing_tool_warning( "ruff", "docstring layout rules (D205, D213 and the rest)" ) ]
    jobs     = [ ( [ "--stdin-filename", p, "-" ], sources[ p ] ) for p in paths ] if sources is not None else [ ( list( paths ), None ) ]
    findings = []
    for extra, stdin in jobs:
        kwargs = {} if stdin is None else { "input": stdin }
        res = runner( [ tool, "check", "--config", os.path.join( root, "pyproject.toml" ), "--output-format", "json", "--no-cache", *extra ],
                      capture_output=True, text=True, encoding="utf-8", cwd=root, **kwargs )
        if res.returncode not in ( 0, 1 ): return [], [ f"[doc-lint] WARNING: ruff failed (exit {res.returncode}), SKIPPED: {res.stderr.strip()[ :200 ]}" ]
        for item in json.loads( res.stdout or "[]" ):
            rel = os.path.relpath( os.path.join( root, item[ "filename" ] ), root )
            findings.append( Finding( rel, item[ "location" ][ "row" ], f"ruff:{item[ 'code' ]}", item[ "message" ] ) )
    return findings, []


def run_markdownlint( root, paths, runner=subprocess.run ):
    """
    Run markdownlint-cli2 over markdown files, with the config in .markdownlint-cli2.jsonc.

    Requires:
        - paths are repo-relative .md files
        - runner has the signature of subprocess.run

    Ensures:
        - returns ( findings, warnings ); findings carry the rule as markdownlint:<id>
        - no paths yields nothing, without looking for the tool
        - a missing tool yields one warning and no findings
        - an exit status other than 0 or 1 yields one warning carrying the tool's stderr

    Raises:
        - nothing
    """
    if not paths: return [], []
    tool = find_tool( root, [ "node_modules/.bin/markdownlint-cli2" ], "markdownlint-cli2", "LUPIN_MARKDOWNLINT" )
    if tool is None: return [], [ missing_tool_warning( "markdownlint-cli2", "markdown structure (headings, fences, tables, links)" ) ]
    res = runner( [ tool, "--no-globs", *paths ], capture_output=True, text=True, encoding="utf-8", cwd=root )
    if res.returncode not in ( 0, 1 ): return [], [ f"[doc-lint] WARNING: markdownlint-cli2 failed (exit {res.returncode}), SKIPPED: {res.stderr.strip()[ :200 ]}" ]
    findings = []
    for line in ( res.stdout + "\n" + res.stderr ).split( "\n" ):
        m = MARKDOWNLINT_LINE.match( line.strip() )
        if m: findings.append( Finding( m.group( 1 ), int( m.group( 2 ) ), f"markdownlint:{m.group( 3 )}", m.group( 4 ) ) )
    return findings, []


def run_dart_analyze( root, directory, runner=subprocess.run ):
    """
    Run the Dart analyzer over one directory and keep the documentation diagnostics.

    Requires:
        - root is a Flutter working tree that carries flutter/bin/dart, or dart is on the search path
        - directory is a path under root, for example lib/features/holding_area
        - runner has the signature of subprocess.run

    Ensures:
        - returns ( findings, warnings ); findings carry the rule as dart:<code>
        - only codes in DART_DOC_CODES are kept; other diagnostics are not this tool's business
        - a missing dart yields one warning and no findings

    Raises:
        - nothing
    """
    tool = find_tool( root, [ "flutter/bin/dart" ], "dart", "LUPIN_DART" )
    if tool is None: return [], [ missing_tool_warning( "dart", "Dart documentation coverage" ) ]
    res = runner( [ tool, "analyze", "--format=machine", directory ], capture_output=True, text=True, encoding="utf-8", cwd=root )
    if res.returncode not in ( 0, 1, 2, 3 ): return [], [ f"[doc-lint] WARNING: dart analyze failed (exit {res.returncode}), SKIPPED: {res.stderr.strip()[ :200 ]}" ]
    findings = []
    for line in res.stdout.split( "\n" ):
        parts = line.split( "|" )
        if len( parts ) < 8 or parts[ 2 ].lower() not in DART_DOC_CODES: continue
        findings.append( Finding( os.path.relpath( parts[ 3 ], root ), int( parts[ 4 ] ), f"dart:{parts[ 2 ].lower()}", "|".join( parts[ 7 : ] ) ) )
    return findings, []
