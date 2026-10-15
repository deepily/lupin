"""
Repair the table rows openapi-to-markdown breaks across two lines.

The tool writes the 422 response row of every route as the row, a newline, then a lone pipe.
That is not a table row, and markdownlint refuses it. This joins the lone pipe back onto its row.
"""
import sys


def join_split_rows( text ):
    """
    Join a table row that the generator ended on the next line.

    Requires:
        - text is the generated markdown

    Ensures:
        - a line that starts with a pipe and does not end with one, followed by a line that is only a space and a pipe, becomes one line
        - every other line is returned unchanged, with its line breaks
        - applying it twice gives the same text
    """
    lines, out, i = text.split( "\n" ), [], 0
    while i < len( lines ):
        row = lines[ i ]
        if row.startswith( "|" ) and not row.endswith( "|" ) and i + 1 < len( lines ) and lines[ i + 1 ] == " |":
            out.append( row + " |" ); i += 2
        else:
            out.append( row ); i += 1
    return "\n".join( out )


def main( argv ):
    """
    Repair one markdown file in place.

    Requires:
        - argv holds the program name and one path

    Ensures:
        - rewrites the file only when a row was joined
        - returns 0, or 2 when the argument count is wrong
    """
    if len( argv ) != 2:
        print( "usage: fix_api_md_tables.py <markdown file>", file=sys.stderr )
        return 2
    with open( argv[ 1 ], encoding="utf-8" ) as f: text = f.read()
    fixed = join_split_rows( text )
    if fixed != text:
        with open( argv[ 1 ], "w", encoding="utf-8" ) as f: f.write( fixed )
    return 0


if __name__ == "__main__":    # pragma: no cover -- process entry, main() is tested
    sys.exit( main( sys.argv ) )
