"""
Refuse a report table that cannot be read alone, and archive cards in confirmatory work.

A report is a list of tables. Each table is a dict with these keys.

- title: text.
- cohort: "archive" or "window".
- stamp: text, which is "development" for an archive table.
- unit: what one count in the header stands for, such as "cards".
- denominator: a dict of count, a whole number above 0, and unit, a text.
- paired_differences: a list of dicts with name, difference and interval. It is empty when the table has none.

The lint reads this structure and nothing else, so a report is written from the tables it passed.
The refusal follows doc_lint.judge_comparison.check_report_binds: it raises and names what differs.
The plan is 2026.11.23-answer-signal-experiment-plan.md, the retrospective re-score.
"""
from cosa.repo.labelling.items import _text
from cosa.repo.symindex.verdict import _number_reason

ARCHIVE     = "archive"
WINDOW      = "window"
DEVELOPMENT = "development"
ANY_SIZE    = ( float( "-inf" ), float( "inf" ) )   # the bounds that leave _number_reason checking only for a finite number


class ReportRefused( ValueError ):
    """A report, or a cohort, that may not be used."""


def table_findings( table ):
    """
    List what is wrong with one report table.

    Requires:
        - table is a dict

    Ensures:
        - returns a list of sentences, empty when the table passes
        - a finding is made for a missing title, a cohort that is neither archive nor window, an archive table not stamped
          development, a missing unit, a missing denominator count or unit, a denominator unit that differs from the unit,
          a table that does not say its paired differences, and a paired difference with no number or no interval around it
    """
    name  = table.get( "title" )
    found = [] if _text( name ) else [ "has no title" ]
    if table.get( "cohort" ) not in ( ARCHIVE, WINDOW ): found.append( f"has no cohort of {ARCHIVE} or {WINDOW}" )
    if table.get( "cohort" ) == ARCHIVE and table.get( "stamp" ) != DEVELOPMENT: found.append( f"is an archive table not stamped {DEVELOPMENT}" )
    unit  = table.get( "unit" )
    if not _text( unit ): found.append( "has no unit" )
    below = table.get( "denominator" )
    below = below if isinstance( below, dict ) else {}
    count = below.get( "count" )
    if not ( isinstance( count, int ) and not isinstance( count, bool ) and count > 0 ): found.append( "has no denominator count above 0" )
    if not _text( below.get( "unit" ) ): found.append( "has a denominator with no unit" )
    elif _text( unit ) and below[ "unit" ] != unit: found.append( f"counts {unit!r} over a denominator of {below[ 'unit' ]!r}" )
    differences = table.get( "paired_differences" )
    if not isinstance( differences, list ):
        found.append( "does not list its paired differences, not even as an empty list" )
        differences = []
    for d in differences:
        value, interval = d.get( "difference" ), d.get( "interval" )
        held = isinstance( interval, ( list, tuple ) ) and len( interval ) == 2 and _number_reason( interval, *ANY_SIZE ) is None
        if _number_reason( [ value ], *ANY_SIZE ) is not None: found.append( f"has a paired difference {d.get( 'name' )!r} with no number" )
        elif not ( held and interval[ 0 ] <= value <= interval[ 1 ] ): found.append( f"has a paired difference {d.get( 'name' )!r} with no interval around it" )
    return [ f"table {name!r} {f}" for f in found ]


def check_report( tables ):
    """
    Refuse a report with a table that fails the lint.

    Requires:
        - tables is a list of dicts

    Ensures:
        - returns None when there is at least one table and every table passes

    Raises:
        - ReportRefused naming every finding of every table, or saying that the report has no table
    """
    if not tables: raise ReportRefused( "the report has no table" )
    found = [ f for table in tables for f in table_findings( table ) ]
    if found: raise ReportRefused( "; ".join( found ) )


def refuse_archive_cohort( cohort ):
    """
    Let only the prospective window into a confirmatory path.

    Requires:
        - cohort is the name of the cohort the path is about to read

    Ensures:
        - returns None for the window cohort

    Raises:
        - ReportRefused for the archive, which has already shaped the design, and for any other name
    """
    if cohort != WINDOW: raise ReportRefused( f"a confirmatory result may use only the {WINDOW} cohort, not {cohort!r}" )
