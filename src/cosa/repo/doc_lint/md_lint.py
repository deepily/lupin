"""
Markdown linter: text rules, page templates and the link check (plan 1, section 4.1).

Structure (heading order, fences, tables) belongs to markdownlint. This module checks what it
cannot: prose rules 3 to 7, the length caps by page kind and the runbook sections.
It also checks whether relative links and Design paths resolve.
"""

import os
import re
import sys

from .cli import run_linter
from .links import design_path_findings, markdown_link_findings
from .marker_counts import FRONTMATTER, HTML_COMMENT, WORD_REGEX, count_markers, rates_per_thousand
from .text_rules import Finding, defined_labels, defined_steps, lint_text

REFERENCE_MAX_WORDS = 1500
CAPABILITY_MAX_LINES = 40
REFERENCE_SKIP      = ( "src/docs/fastapi/", "src/docs/wiki/", "src/docs/decisions/", "src/docs/doctrine/", "src/docs/auth/" )
RUNBOOK_SECTIONS    = ( "prerequisites", "steps", "verify", "rollback" )
HEADING_REGEX       = re.compile( r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE )
BARE_LABEL_MESSAGE   = re.compile( r"^bare reference '(.*)'$" )
BARE_SECTION_MESSAGE = re.compile( "^section reference '\u00a7(.*)' has no path$" )
NUMBERED_PART      = re.compile( r"^\d{2}-.+\.md$" )
NUMBERED_HEADING     = re.compile( r"^#{1,6}[ \t]+(\d+(?:\.\d+)*)\.?(?:[ \t]|$)", re.MULTILINE )
FENCE_OPENER        = re.compile( r"^[ \t]*(`{3,}|~{3,})" )


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


def blank_fences( source ):
    """
    Blank every closed fenced code block, indented or not.

    Requires:
        - source is markdown text

    Ensures:
        - a fence closes on a line of its own character, at least as long as its opener, with only spaces after it
        - a fence with no such closer is left as it is
        - returns text with the same number of lines, each fenced line reduced to its newline

    Raises:
        - nothing
    """
    lines = source.split( "\n" )
    index = 0
    while index < len( lines ):
        opener = FENCE_OPENER.match( lines[ index ] )
        if opener is None:
            index += 1
            continue
        mark   = opener.group( 1 )
        closer = re.compile( r"^[ \t]*" + re.escape( mark[ 0 ] ) + "{" + str( len( mark ) ) + r",}[ \t]*$" )
        end    = next( ( n for n in range( index + 1, len( lines ) ) if closer.match( lines[ n ] ) ), None )
        if end is None:
            index += 1
            continue
        lines[ index : end + 1 ] = [ "" ] * ( end + 1 - index )
        index = end + 1
    return "\n".join( lines )


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
    return HTML_COMMENT.sub( _blank, blank_fences( FRONTMATTER.sub( _blank, source, count=1 ) ) )


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


def _read_text( full ):
    """
    Read one markdown file as text.

    Requires:
        - full is the path of a readable file

    Ensures:
        - returns the file's text, decoded as UTF-8

    Raises:
        - OSError if the file cannot be read
    """
    with open( full, encoding="utf-8" ) as handle: return handle.read()


def sibling_paths( path, root ):
    """
    List the other markdown files of the split page that path belongs to.

    Requires:
        - path is the repo-relative path of a page
        - root is the repo working tree, or None

    Ensures:
        - a split page is an index at foo.md and the parts directly inside the folder foo beside it
        - a part is named with two digits and a dash first, such as 01-intro.md, so a folder of dated archive files is not a split
        - returns the index and every part except path itself, sorted, as repo-relative paths
        - returns an empty list when root is None, when the folder, the index or every part is missing, or when path is neither the index nor a part
        - a folder nested inside foo is not read

    Raises:
        - nothing
    """
    if root is None: return []
    if NUMBERED_PART.match( os.path.basename( path ) ): folder = os.path.dirname( path )
    elif path.endswith( ".md" ): folder = path[ : -len( ".md" ) ]
    else: return []
    if not folder or not os.path.isdir( os.path.join( root, folder ) ) or not os.path.isfile( os.path.join( root, folder + ".md" ) ): return []
    parts = [ os.path.join( folder, name ) for name in os.listdir( os.path.join( root, folder ) ) if NUMBERED_PART.match( name ) and os.path.isfile( os.path.join( root, folder, name ) ) ]
    if not parts: return []
    group = [ folder + ".md" ] + parts
    return sorted( member for member in group if member != path )


def sibling_resolved( findings, prose, siblings ):
    """
    Drop the bare-ref findings that another part of the same split page resolves.

    Requires:
        - findings is a list of Finding for one page
        - prose is that page's text with code blanked
        - siblings is the blanked text of the other parts, joined, or an empty string

    Ensures:
        - a Phase or case label that the page or a sibling defines is no longer a finding
        - a section mark is no longer a finding when the page or a sibling has a heading with that number
        - with no siblings the findings come back unchanged, so a lone page keeps its old behaviour
        - every other finding, and a label or mark that nothing defines, stays

    Raises:
        - nothing
    """
    if not siblings: return findings
    group    = prose + "\n" + siblings
    labels   = defined_labels( group )
    steps    = defined_steps( group )
    numbers  = set( NUMBERED_HEADING.findall( group ) )
    kept     = []
    for finding in findings:
        label   = BARE_LABEL_MESSAGE.match( finding.message ) if finding.rule == "bare-ref" else None
        section = BARE_SECTION_MESSAGE.match( finding.message ) if finding.rule == "bare-ref" else None
        if label is not None and ( label.group( 1 ) in labels or label.group( 1 ).lower() in steps ): continue
        if section is not None and section.group( 1 ) in numbers: continue
        kept.append( finding )
    return kept


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
    findings = sibling_resolved( findings, prose, "\n".join( blank_non_prose( _read_text( os.path.join( root, name ) ) ) for name in sibling_paths( path, root ) ) )
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
