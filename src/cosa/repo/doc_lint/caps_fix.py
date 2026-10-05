"""
Lowers the capitals that the docstring linter's caps rule flags, and nothing else.

The words are found with the linter's own caps rule, so there is no second word list. A flagged
word that is also an identifier in the same file's code, such as a constant, is left alone and
reported. A file is written only when docs_only_diff says the edit changed docstrings alone.
"""

import argparse
import ast
import sys

from .cli import tracked_files
from .docs_only_diff import python_difference
from .docstring_lint import extract_docstrings, lint_source
from .marker_counts import CAPS_REGEX, INLINE_CODE, caps_words
from .sweep_packages import split_packages
from .word_list import configure_root


def code_identifiers( source ):
    """
    List the names that a Python source uses as identifiers.

    Requires:
        - source is valid Python text

    Ensures:
        - returns a set of variable, attribute, function, class, argument, keyword and import names
        - names that only appear inside strings and docstrings are not included

    Raises:
        - SyntaxError when source does not parse
    """
    names = set()
    for node in ast.walk( ast.parse( source ) ):
        if isinstance( node, ast.Name ): names.add( node.id )
        elif isinstance( node, ast.Attribute ): names.add( node.attr )
        elif isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef ) ): names.add( node.name )
        elif isinstance( node, ast.arg ): names.add( node.arg )
        elif isinstance( node, ast.keyword ) and node.arg is not None: names.add( node.arg )
        elif isinstance( node, ast.alias ): names.add( node.asname or node.name )
    return names


def _flagged( line ):
    """
    List the words the caps rule flags on one docstring line.

    Requires:
        - line is a str with no newline

    Ensures:
        - returns the same words the linter reports for that line, in order

    Raises:
        - OSError when the word list is missing
    """
    return caps_words( INLINE_CODE.sub( " ", line ) )


def lower_line( line, identifiers ):
    """
    Lower every flagged word on one docstring line, except identifiers.

    Requires:
        - line is a str with no newline
        - identifiers is a set of names to leave alone

    Ensures:
        - returns ( new_line, lowered, left_alone ) where left_alone lists the flagged identifier words that stayed
        - a word is lowered only when lowering it removes one linter finding, so quoted and code spans never change
        - the new line has the length of the old one

    Raises:
        - OSError when the word list is missing
    """
    before = len( _flagged( line ) )
    new    = line
    for match in CAPS_REGEX.finditer( line ):
        word = match.group( 0 )
        if word in identifiers: continue
        trial = new[ : match.start() ] + word.lower() + new[ match.end() : ]
        if len( _flagged( trial ) ) < len( _flagged( new ) ): new = trial
    left_alone = _flagged( new )
    return new, before - len( left_alone ), left_alone


def fix_source( path, source, root ):
    """
    Lower the flagged capitals in the docstrings of one Python source.

    Requires:
        - path is the repo-relative path and source its text; root is the working tree the linter reads

    Ensures:
        - returns a dict with new_source, lowered, left_alone as [ ( line, word ) ], and unlocated
        - only lines the linter reports a caps finding on are touched, and only inside the docstring text
        - unlocated counts words on lines whose docstring text could not be found in the source line, left unchanged
        - a source with no caps findings, or one that does not parse, comes back unchanged with zero counts

    Raises:
        - nothing
    """
    result = { "new_source": source, "lowered": 0, "left_alone": [], "unlocated": 0 }
    hit_lines = { f.line for f in lint_source( path, source, root ) if f.rule == "caps" }
    if not hit_lines: return result
    identifiers = code_identifiers( source )
    lines       = source.split( "\n" )
    for _, _, first_line, text in extract_docstrings( source ):
        for offset, doc_line in enumerate( text.split( "\n" ) ):
            number = first_line + offset
            if number not in hit_lines: continue
            new_doc, lowered, left_alone = lower_line( doc_line, identifiers )
            result[ "left_alone" ] += [ ( number, word ) for word in left_alone ]
            position = lines[ number - 1 ].find( doc_line )
            if position < 0:
                result[ "unlocated" ] += lowered
                continue
            line = lines[ number - 1 ]
            lines[ number - 1 ] = line[ : position ] + new_doc + line[ position + len( doc_line ) : ]
            result[ "lowered" ] += lowered
    result[ "new_source" ] = "\n".join( lines )
    return result


def fix_files( root, paths, dry_run ):
    """
    Fix the docstring capitals of several files.

    Requires:
        - root is a git working tree that holds the word list; paths are tracked repo-relative .py files

    Ensures:
        - returns one dict per file that had a caps finding, with path, lowered, left_alone, unlocated and refused
        - with dry_run False a file is written only when its edit passes docs_only_diff; otherwise refused names the difference and the file is untouched
        - with dry_run True nothing is written, and lowered is the count that a real run would write
        - a file that cannot be read as UTF-8 is left alone and reported with refused set

    Raises:
        - nothing
    """
    configure_root( root )
    report = []
    for path in paths:
        try:
            with open( f"{root}/{path}", encoding="utf-8", newline="" ) as handle: source = handle.read()
        except ( OSError, UnicodeDecodeError ) as err:
            report.append( { "path": path, "lowered": 0, "left_alone": [], "unlocated": 0, "refused": f"could not read: {err}" } )
            continue
        result = fix_source( path, source, root )
        if not ( result[ "lowered" ] or result[ "left_alone" ] or result[ "unlocated" ] ): continue
        new_source = result.pop( "new_source" )
        refused    = python_difference( source, new_source ) if result[ "lowered" ] else None
        if refused is not None: result[ "lowered" ] = 0
        elif not dry_run and result[ "lowered" ]:
            with open( f"{root}/{path}", "w", encoding="utf-8", newline="" ) as handle: handle.write( new_source )
        report.append( { "path": path, **result, "refused": refused } )
    return report


def format_report( report, dry_run ):
    """
    Render a fix report as text.

    Requires:
        - report comes from fix_files

    Ensures:
        - returns one line per file, then a total line that says whether anything was written
        - words left alone are listed with their line, so they can be checked by hand

    Raises:
        - nothing
    """
    lines = []
    for row in report:
        lines.append( f"{row[ 'path' ]}: {row[ 'lowered' ]} lowered, {len( row[ 'left_alone' ] )} left alone, {row[ 'unlocated' ]} unlocated" )
        lines += [ f"  left alone {word} at line {number}" for number, word in row[ "left_alone" ] ]
        if row[ "refused" ]: lines.append( f"  refused: {row[ 'refused' ]}" )
    lowered = sum( row[ "lowered" ] for row in report )
    touched = sum( 1 for row in report if row[ "lowered" ] )
    lines.append( f"{lowered} words in {touched} files " + ( "would be lowered, nothing written" if dry_run else "lowered and written" ) )
    return "\n".join( lines ) + "\n"


def main( argv=None, out=None ):
    """
    Command-line entry point.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]

    Ensures:
        - prints the report to out and returns 0
        - --dry-run writes nothing; --packages-only keeps only files that sit in a package
        - with no paths given, every tracked in-scope .py file is read

    Raises:
        - RuntimeError from git when a listing fails
    """
    out    = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser( description="Lower the ALL-CAPS words the docstring linter flags." )
    parser.add_argument( "paths", nargs="*", help="repo-relative .py files; default is every tracked file" )
    parser.add_argument( "--dry-run", action="store_true", help="print the counts and change nothing" )
    parser.add_argument( "--packages-only", action="store_true", help="skip files that sit in no package" )
    parser.add_argument( "--repo-root", default=".", help="git working tree to read" )
    args  = parser.parse_args( sys.argv[ 1: ] if argv is None else argv )
    paths = args.paths if args.paths else tracked_files( args.repo_root, ( ".py", ) )
    if args.packages_only: paths = [ p for files in split_packages( paths )[ 0 ].values() for p in files ]
    out.write( format_report( fix_files( args.repo_root, sorted( paths ), args.dry_run ), args.dry_run ) )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
