"""
The results page of the offline comparison.

The page names the winning arm and gives every figure with the run and the shas it came from. It is
built from numbers the caller measured, so this module reads no cache, no needs file and no index.
"""
import hashlib
import pathlib

from cosa.repo.symindex.candidates.errors import CandidateError

REPORT_META_MISSING = "REPORT_META_MISSING"
META_KEYS           = ( "run_id", "code_sha", "index_sha", "manifest_hash", "needs_sha", "cache_sha" )


def count_redactable( needs, redactor, planted_text ):
    """
    Count the needs that hold a token the redactor would blank, and run the positive control.

    Requires:
        - needs is a mapping of need id to need text
        - redactor takes a text and returns the number of spans it would blank
        - planted_text holds a token the redactor is meant to find

    Ensures:
        - returns the count of needs with at least one span, their sorted ids, the number of needs,
          and a control flag that is True only when the redactor finds a span in planted_text
    """
    hit = sorted( n for n, text in needs.items() if redactor( text ) > 0 )
    return { "count": len( hit ), "ids": hit, "of": len( needs ), "control": redactor( planted_text ) > 0 }


def percent( value ):
    """Format a share as a percentage, or a dash when it was not measured."""
    return "-" if value is None else f"{100 * value:.1f}%"


def size( value ):
    """Format a mean shortlist size, or a dash when no shortlist was measured."""
    return "-" if value is None else f"{value:.0f}"


def render_report( meta, t1, t3, t2, vectors_choice, fusion, redactable ):
    """
    Build the markdown results page.

    Requires:
        - meta holds every key of META_KEYS
        - t1 is the t1_table result, t3 maps arm to the t3_summary result, t2 maps arm to the t2_replay result
        - vectors_choice is the one-vector or the two-vector arm name, fusion is ( k, depth, head )
        - redactable is count_redactable's result, whose control flag the page prints

    Ensures:
        - returns the page text, with the run id and the five shas in the header
        - states that every figure is in-sample and is not a flip rate

    Raises:
        - CandidateError REPORT_META_MISSING naming the absent keys
    """
    absent = [ key for key in META_KEYS if not meta.get( key ) ]
    if absent: raise CandidateError( REPORT_META_MISSING, ", ".join( absent ) )
    lines = [ "# Offline comparison of the arms", "",
              "All figures are in-sample, so they rank the arms against each other. They are not a flip rate.", "",
              "| key | value |", "|---|---|" ] + [ f"| {key} | {meta[ key ]} |" for key in META_KEYS ]
    lines += [ "", f"**Winning vector arm:** {vectors_choice}", "",
               f"**Fusion constants:** k {fusion[ 0 ]}, depth {fusion[ 1 ]}, head {fusion[ 2 ]}", "",
               "## T1: recall of the full-sweep shortlist", "", "Each cell is the mean recall, then the mean number of ids in the shortlist at that K.", "",
               "| arm | " + " | ".join( f"K={k}" for k in sorted( next( iter( t1.values() ) ) ) ) + " |",
               "|---|" + "---|" * len( next( iter( t1.values() ) ) ) ]
    for arm in sorted( t1 ):
        cells = [ f"{percent( t1[ arm ][ k ][ 'mean' ] )} ({size( t1[ arm ][ k ][ 'mean_size' ] )} ids)" for k in sorted( t1[ arm ] ) ]
        lines.append( f"| {arm} | " + " | ".join( cells ) + " |" )
    lines += [ "", "## T3: where the known twin lands", "", "| arm | language | members | unranked | median of ranked | median of all | in top 10 | in top 50 | in top 128 |", "|---|---|---|---|---|---|---|---|---|" ]
    for arm in sorted( t3 ):
        for language in sorted( t3[ arm ] ):
            row = t3[ arm ][ language ]
            lines.append( f"| {arm} | {language} | {row[ 'members' ]} | {row[ 'unranked' ]} | {row[ 'median' ]} | {row[ 'median_all' ]} | {row[ 'within' ][ 10 ]} | {row[ 'within' ][ 50 ]} | {row[ 'within' ][ 128 ]} |" )
    lines += [ "", "## T2: replayed verdicts", "", "| arm | needs | verdict flip rate | agreement | uncached answers |", "|---|---|---|---|---|" ]
    for arm in sorted( t2 ):
        row = t2[ arm ]
        lines.append( f"| {arm} | {row[ 'needs' ]} | {percent( row[ 'flip_rate' ] )} | {percent( row[ 'agreement' ] )} | {row[ 'uncached' ]} |" )
    lines += [ "", "## Redaction", "",
               f"{redactable[ 'count' ]} of {redactable[ 'of' ]} needs hold a redactable token. The replay uses the raw needs.",
               f"Positive control: the redactor {'found' if redactable[ 'control' ] else 'did NOT find'} a planted token." ]
    return "\n".join( lines ) + "\n"


def write_report( path, text ):
    """
    Write the page and return its hash.

    Requires:
        - path is where the page goes, in a folder that exists or can be made

    Ensures:
        - writes UTF-8 text and returns the sha256 of the bytes written
    """
    target = pathlib.Path( path )
    target.parent.mkdir( parents=True, exist_ok=True )
    data = text.encode( "utf-8" )
    target.write_bytes( data )
    return hashlib.sha256( data ).hexdigest()
