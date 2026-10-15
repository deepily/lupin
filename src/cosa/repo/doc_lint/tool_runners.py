"""
Runners for ruff, markdownlint-cli2 and the Dart analyzer.

Each runner returns ( findings, warnings ). A tool that is not installed yields no findings and
one loud warning that names what was not checked. It never passes silently. A gate
that skips quietly looks the same as a gate that passed.
"""

import json
import os
import re
import shutil
import subprocess

from .cli import crosses_as_text, shown
from .text_rules import Finding

RUFF_RELATIVE     = [ ".venv/bin/ruff" ]
MARKDOWNLINT_REL  = [ "node_modules/.bin/markdownlint-cli2" ]
MARKDOWNLINT_COUNT = re.compile( r"^Linting: (\d+) file\(s\)$", re.MULTILINE )
MARKDOWNLINT_LINE = re.compile( r"^(.+?):(\d+)(?::\d+)? (?:(?:error|warning) )?(MD\d+/[\w-]+) (.*)$" )
DART_DOC_CODES    = frozenset( { "public_member_api_docs", "slash_for_doc_comments", "dangling_library_doc_comments",
                                 "unintended_html_in_doc_comment", "comment_references" } )


class Unchecked( str ):
    """A warning that a check of staged files could not be made. The blocking gate refuses on it."""


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
        - an exit status other than 0 or 1 yields one Unchecked warning carrying ruff's stderr, and no findings
        - unless ruff also fails on a blank file, which is a version or configuration skew that fails every commit alike:
          that yields one plain warning, no refusal, and the line says how to fix it
        - a program that exits 0 or 1 without printing ruff's JSON list is not ruff: one plain warning, no refusal, no file checked
        - a file name follows the option's equals sign or a -- separator, so one that starts with a dash is read as a name
        - with sources, each run checks one file, and its findings carry the path that was asked for, not the name ruff printed
        - so a file name that is not UTF-8, which ruff prints with a replacement character, keeps its findings
        - without sources, such a name is not handed to ruff, and one warning per file says it was not checked
        - without sources, a finding ruff places in a file that was not asked for yields one warning that names it

    Raises:
        - nothing
    """
    if not paths: return [], []
    tool = find_tool( root, RUFF_RELATIVE, "ruff", "LUPIN_RUFF" )
    if tool is None: return [], [ missing_tool_warning( "ruff", "docstring layout rules (D205, D213 and the rest)" ) ]
    listed   = [ p for p in paths if crosses_as_text( p ) ]
    warnings = [] if sources is not None else [ unnamed_warning( "ruff", p ) for p in paths if p not in listed ]
    jobs     = [ ( p, [ f"--stdin-filename={p}", "-" ], sources[ p ] ) for p in paths ] if sources is not None else [ ( None, [ "--", *listed ], None ) ] if listed else []
    findings = []
    for asked, extra, stdin in jobs:
        res = _ruff_check( runner, tool, root, extra, stdin )
        if res.returncode not in ( 0, 1 ):
            blank = _ruff_check( runner, tool, root, [ "--stdin-filename=probe.py", "-" ], "" )
            why   = res.stderr.strip()[ :200 ]
            if blank.returncode not in ( 0, 1 ):
                return [], [ f"[doc-lint] WARNING: ruff cannot run here (exit {res.returncode}), so no file was checked by it: {why}; fix: install the ruff version pyproject.toml pins, or point LUPIN_RUFF at it" ]
            return [], [ Unchecked( f"[doc-lint] WARNING: ruff failed (exit {res.returncode}), SKIPPED: {why}" ) ]
        try: items = json.loads( res.stdout )
        except ValueError: items = None
        if not isinstance( items, list ):
            return [], [ f"[doc-lint] WARNING: {tool} did not print the JSON report ruff prints, so it is not ruff or not this ruff, and no file was checked by it; fix: install the ruff version pyproject.toml pins, or point LUPIN_RUFF at it" ]
        for item in items:
            rel = asked if asked is not None else os.path.relpath( os.path.join( root, item[ "filename" ] ), root )
            if rel not in paths: warnings.append( f"[doc-lint] WARNING: ruff placed a finding in {shown( rel )}, a file it was not asked about, so that finding is NOT attached to any staged file" )
            findings.append( Finding( rel, item[ "location" ][ "row" ], f"ruff:{item[ 'code' ]}", item[ "message" ] ) )
    return findings, warnings


def _ruff_check( runner, tool, root, extra, stdin ):
    """
    Run ruff check once with the pinned config.

    Requires:
        - runner has the signature of subprocess.run; tool is ruff's path; extra are its trailing arguments
        - stdin is the text to feed it, or None when the arguments name the files

    Ensures:
        - returns the finished process; its exit status is the caller's to read

    Raises:
        - OSError when the process cannot be started
    """
    kwargs = {} if stdin is None else { "input": stdin }
    return runner( [ tool, "check", "--config", os.path.join( root, "pyproject.toml" ), "--output-format", "json", "--no-cache", *extra ],
                   capture_output=True, text=True, encoding="utf-8", cwd=root, **kwargs )


def unnamed_warning( tool, path ):
    """
    Build the loud line for a file a tool cannot be given by name.

    Requires:
        - tool names the tool; path is a repo-relative path whose name the tool cannot read and print back

    Ensures:
        - the line starts with the doc-lint warning prefix, names the file through shown and says it was not checked

    Raises:
        - nothing
    """
    return f"[doc-lint] WARNING: {shown( path )} has a file name that is not UTF-8 or holds a line break, so {tool} cannot be given it and it was NOT checked by {tool}"


def markdownlint_unnamed( root, paths ):
    """
    List the markdown files an installed markdownlint-cli2 cannot be given by name.

    Requires:
        - root is the repo working tree; paths are repo-relative .md files

    Ensures:
        - returns [] when markdownlint-cli2 is not installed, since then no file is checked and run_markdownlint says so
        - else returns each path whose name is not UTF-8 or holds a line break, in the order given
        - the tool reads a name as UTF-8 text and prints one finding per line, so such a name cannot go in and come back

    Raises:
        - nothing
    """
    if find_tool( root, MARKDOWNLINT_REL, "markdownlint-cli2", "LUPIN_MARKDOWNLINT" ) is None: return []
    return [ p for p in paths if not _line_safe( p ) ]


def _glob_read( name ):
    """Say whether markdownlint-cli2 would read a file name as a glob pattern."""
    return name.startswith( ( "#", "!" ) ) or any( c in name for c in "(){}\\*?[]" )


def _line_safe( name ):
    """Say whether a tool that prints one finding per line can be given a file name."""
    return crosses_as_text( name ) and "\n" not in name and "\r" not in name


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
        - an exit status other than 0 or 1 yields one Unchecked warning carrying the tool's stderr
        - the file names follow a -- separator, so one that starts with a dash is read as a name
        - a file markdownlint_unnamed lists is not handed to the tool, and one warning per file says it was not checked
        - a finding the tool places in a file that was not asked for yields one warning that names it
        - a file whose name holds one of ( ) { } \\ * ? [ ] or starts with # or ! is not handed to the tool, and one Unchecked warning per file says it was not checked
        - the word error or warning before the rule is optional, since the pinned 0.18.1 prints neither
        - exit status 1 with no finding read yields one Unchecked warning, so a changed output format cannot pass silently
        - a count of files linted that differs from the files handed over, or no count at all, yields one Unchecked warning and no findings

    Raises:
        - nothing
    """
    if not paths: return [], []
    tool = find_tool( root, MARKDOWNLINT_REL, "markdownlint-cli2", "LUPIN_MARKDOWNLINT" )
    if tool is None: return [], [ missing_tool_warning( "markdownlint-cli2", "markdown structure (headings, fences, tables, links)" ) ]
    listed   = [ p for p in paths if _line_safe( p ) ]
    warnings = [ unnamed_warning( "markdownlint-cli2", p ) for p in paths if p not in listed ]
    globbed  = [ p for p in listed if _glob_read( p ) ]
    warnings += [ Unchecked( f"[doc-lint] WARNING: {shown( p )} has a file name markdownlint-cli2 reads as a glob, so it was NOT handed to the tool and its markdown structure was NOT checked; fix: rename the file" ) for p in globbed ]
    listed   = [ p for p in listed if p not in globbed ]
    if not listed: return [], warnings
    res = runner( [ tool, "--no-globs", "--", *listed ], capture_output=True, text=True, encoding="utf-8", cwd=root )
    if res.returncode not in ( 0, 1 ): return [], warnings + [ Unchecked( f"[doc-lint] WARNING: markdownlint-cli2 failed (exit {res.returncode}), SKIPPED: {res.stderr.strip()[ :200 ]}" ) ]
    counted = MARKDOWNLINT_COUNT.search( res.stdout )
    if counted is None: return [], warnings + [ Unchecked( "[doc-lint] WARNING: markdownlint-cli2 printed no count of files linted, so the markdown structure was NOT checked; fix: keep noProgress out of .markdownlint-cli2.jsonc" ) ]
    if int( counted.group( 1 ) ) != len( listed ): return [], warnings + [ Unchecked( f"[doc-lint] WARNING: markdownlint-cli2 linted {counted.group( 1 )} of {len( listed )} file(s) it was given, so the markdown structure was NOT checked; a name the tool reads as a glob is not linted" ) ]
    findings = []
    for line in ( res.stdout + "\n" + res.stderr ).split( "\n" ):
        m = MARKDOWNLINT_LINE.match( line.strip() )
        if not m: continue
        if m.group( 1 ) not in listed: warnings.append( f"[doc-lint] WARNING: markdownlint-cli2 placed a finding in {shown( m.group( 1 ) )}, a file it was not asked about, so that finding is NOT attached to any staged file" )
        findings.append( Finding( m.group( 1 ), int( m.group( 2 ) ), f"markdownlint:{m.group( 3 )}", m.group( 4 ) ) )
    if res.returncode == 1 and not findings:
        warnings.append( Unchecked( f"[doc-lint] WARNING: markdownlint-cli2 reported findings (exit 1) but none could be read, so the markdown structure was NOT checked: {res.stderr.strip()[ :200 ]}" ) )
    return findings, warnings


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
