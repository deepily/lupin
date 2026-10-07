"""
Markdown linter: text rules, page templates and the link check (plan 1, section 4.1).

Structure (heading order, fences, tables) belongs to markdownlint. This module checks what it
cannot: prose rules 3 to 7, the length caps by page kind and the runbook sections.
It also checks whether relative links and Design paths resolve.
"""

import re
import sys

from .cli import run_linter
from .links import design_path_findings, markdown_link_findings
from .marker_counts import FENCED_BLOCK, FRONTMATTER, HTML_COMMENT, WORD_REGEX, count_markers, rates_per_thousand
from .text_rules import Finding, lint_text

REFERENCE_MAX_WORDS = 1500
CAPABILITY_MAX_LINES = 40
REFERENCE_SKIP      = ( "src/docs/fastapi/", "src/docs/wiki/", "src/docs/decisions/", "src/docs/doctrine/", "src/docs/auth/" )
RUNBOOK_SECTIONS    = ( "prerequisites", "steps", "verify", "rollback" )
HEADING_REGEX       = re.compile( r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE )


def _blank( match ):
    """
    Replace a matched block with as many newlines as it spans.

    Requires:
        - match is a re match object

    Ensures:
        - returns newlines only, so line numbers after the block do not move

    Raises:
        - nothing
    """
    return "\n" * match.group( 0 ).count( "\n" )


def blank_non_prose( source ):
    """
    Blank the front matter, fenced code and HTML comments of a page.

    Requires:
        - source is markdown text

    Ensures:
        - returns text with the same number of lines, the blocks reduced to newlines

    Raises:
        - nothing
    """
    return HTML_COMMENT.sub( _blank, FENCED_BLOCK.sub( _blank, FRONTMATTER.sub( _blank, source, count=1 ) ) )


def template_findings( path, source, prose ):
    """
    Check the length caps and runbook sections for the kind of page this is.

    Requires:
        - path is the repo-relative path; prose is the page with code blanked

    Ensures:
        - a capability page under src/docs/wiki/capabilities/ has at most CAPABILITY_MAX_LINES lines
        - a reference page under src/docs/ has at most REFERENCE_MAX_WORDS words
        - a page named like a runbook has a heading for each of RUNBOOK_SECTIONS

    Raises:
        - nothing
    """
    findings = []
    if "/wiki/capabilities/" in path:
        lines = len( source.strip( "\n" ).split( "\n" ) )
        if lines > CAPABILITY_MAX_LINES:
            findings.append( Finding( path, 1, "capability-length", f"capability page of {lines} lines, limit {CAPABILITY_MAX_LINES}" ) )
    elif path.startswith( "src/docs/" ) and not path.startswith( REFERENCE_SKIP ):
        words = len( WORD_REGEX.findall( prose ) )
        if words > REFERENCE_MAX_WORDS:
            findings.append( Finding( path, 1, "reference-length", f"reference page of {words} words, limit {REFERENCE_MAX_WORDS}" ) )
    if "runbook" in path.rsplit( "/", 1 )[ -1 ].lower():
        headings = " ".join( h.lower() for h in HEADING_REGEX.findall( prose ) )
        for section in RUNBOOK_SECTIONS:
            if section not in headings:
                findings.append( Finding( path, 1, "runbook-template", f"runbook has no {section} section" ) )
    return findings


def lint_source( path, source, root=None, stats=None ):
    """
    Lint one markdown page.

    Requires:
        - path is the repo-relative path used in findings
        - root is the repo working tree, or None to skip the link checks
        - stats is a dict that may hold a not_checked list, or None

    Ensures:
        - returns a list of Finding, sorted by line
        - front matter and fenced code are not linted as prose
        - a Design: path outside the root is not judged, and goes to stats["not_checked"] when that list is there

    Raises:
        - nothing
    """
    prose    = blank_non_prose( source )
    findings = lint_text( prose, path, 1, structure=False, markdown=True )
    findings += template_findings( path, source, prose )
    if root is not None:
        findings += markdown_link_findings( prose, path, root )
        findings += design_path_findings( prose, path, 1, root, stats[ "not_checked" ] if stats is not None and "not_checked" in stats else None )
    return sorted( findings, key=lambda f: ( f.line, f.rule, f.message ) )


def page_rates( source ):
    """
    Return the marker rates per 1,000 words for one page.

    Requires:
        - source is markdown text

    Ensures:
        - returns the dict from rates_per_thousand over the prose of the page

    Raises:
        - nothing
    """
    return rates_per_thousand( count_markers( blank_non_prose( source ) ) )


def main( argv=None, out=None ):
    """
    Command-line entry point.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]

    Ensures:
        - returns the exit code from run_linter

    Raises:
        - nothing beyond run_linter's
    """
    stats = { "not_checked": [] }
    return run_linter(
        "Lint markdown pages against the eight rules.", ( ".md", ),
        lambda path, source, root: lint_source( path, source, root, stats ),
        sys.argv[ 1: ] if argv is None else argv, out,
        footer=lambda: f"Design paths not checked: {len( stats[ 'not_checked' ] )}\n" if stats[ "not_checked" ] else ""
    )


if __name__ == "__main__":
    sys.exit( main() )
