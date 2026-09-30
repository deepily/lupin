"""
Linter for `#` comment lines in Python: banners, shouting and emphasis glyphs.

Uses tokenize, so a `#` inside a string is not a comment. The sentence, reference and history
rules are not applied to comments, which hold working notes rather than documentation.
"""

import io
import sys
import tokenize

from .cli import run_linter
from .text_rules import Finding, emphasis_findings, rhetoric_findings, history_findings


def lint_source( path, source, root=None ):
    """
    Lint every `#` comment in one Python file.

    Requires:
        - path is the repo-relative path used in findings
        - root is the repo working tree, or None to skip checks that need it

    Ensures:
        - returns a list of Finding, sorted by line
        - the shebang line is skipped
        - a file that cannot be tokenized yields one parse-error finding

    Raises:
        - nothing
    """
    findings = []
    try:
        for tok in tokenize.generate_tokens( io.StringIO( source ).readline ):
            if tok.type != tokenize.COMMENT: continue
            line, text = tok.start[ 0 ], tok.string[ 1 : ]
            if line == 1 and tok.string.startswith( "#!" ): continue
            findings += emphasis_findings( text, path, line )
            findings += rhetoric_findings( text, path, line )
            findings += history_findings( text, path, line )
    except ( tokenize.TokenError, IndentationError ) as err:
        return [ Finding( path, 1, "parse-error", f"cannot tokenize: {err}" ) ]
    return sorted( findings, key=lambda f: ( f.line, f.rule, f.message ) )


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
    return run_linter( "Lint Python # comments for banners and shouting.", ( ".py", ), lint_source, sys.argv[ 1: ] if argv is None else argv, out )


if __name__ == "__main__":
    sys.exit( main() )
