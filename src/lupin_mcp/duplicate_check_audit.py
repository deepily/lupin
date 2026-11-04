"""
Queue a known-miss audit for each duplicate the daily check finds.

A duplicate the lookup tool should have caught is tied to the lookup receipt behind it (reuse_tie.find_tie).
When that receipt holds a need, the lookup is queued for the shadow audit. The item carries a known-miss marker and the tie kind. It also carries the new definition's own id, which the sweep leaves out.
Only the pending-file write is used, so no lookup is counted and nothing is sampled.
Nothing here runs a model, sends a request or reads the store; the receipt reader and the tie finder are passed in.
"""
from lupin_mcp import reuse_shadow as rs
from lupin_mcp import reuse_tools as rt
from cosa.repo.symindex.candidates import shadow_audit as sa

QUEUED          = "queued"
NO_TIE          = "no_tie"
NO_NEED_TEXT    = "no_need_text"
NO_SHORTLIST    = "no_shortlist"
UNREADABLE      = "receipt_unreadable"
TIE_ERROR       = "tie_error"
HEURISTIC_QUEUED = "heuristic_queued"
COUNTERS        = ( QUEUED, HEURISTIC_QUEUED, NO_TIE, NO_NEED_TEXT, NO_SHORTLIST, UNREADABLE, TIE_ERROR )
FETCH_SIMILAR   = "fetch_similar"


def queue_audits( findings, tie_of, receipt_of, data_dir, today ):
    """
    Queue a known-miss audit for each finding whose tie gives a lookup with a need.

    Requires:
        - findings are the daily check's findings, each with an id
        - tie_of( finding ) returns reuse_tie.find_tie's answer for it, and may raise ValueError
        - receipt_of( receipt id ) returns the stored receipt, or raises ReuseError
        - today is an ISO date string

    Ensures:
        - returns { counters, reasons }: counters has every counter name, and reasons maps a finding id to why it was not queued
        - a finding with no tie counts no_tie, and one whose tie error was raised counts tie_error
        - a tie to a fetch_similar receipt counts no_need_text, because that receipt holds a symbol id and not a need; the receipt is not read when the tie already says so
        - a receipt that cannot be read counts receipt_unreadable; one that is not a shortlist answer of check_exists counts no_shortlist
        - otherwise the lookup is queued with known_miss, the finding's id as the id the sweep leaves out, and the tie kind
        - a heuristic tie counts both queued and heuristic_queued, so the figures can be split by tie
        - no lookup count is added and no sample is taken
    """
    counters = dict.fromkeys( COUNTERS, 0 )
    reasons  = {}

    def skip( finding, name, why ):
        """Ensures: counts the finding under name and keeps the reason."""
        counters[ name ] += 1
        reasons[ finding[ "id" ] ] = why

    for finding in findings:
        try: tie = tie_of( finding )
        except ValueError as exc: skip( finding, TIE_ERROR, str( exc ) ); continue
        if tie[ "tie" ] == "none": skip( finding, NO_TIE, tie[ "reason" ] ); continue
        if tie[ "tool" ] == FETCH_SIMILAR: skip( finding, NO_NEED_TEXT, f"receipt {tie[ 'receipt_id' ]} is a fetch_similar lookup" ); continue
        try: receipt = receipt_of( tie[ "receipt_id" ] )
        except rt.ReuseError as exc: skip( finding, UNREADABLE, str( exc ) ); continue
        if receipt[ "tool" ] == FETCH_SIMILAR: skip( finding, NO_NEED_TEXT, f"receipt {tie[ 'receipt_id' ]} is a fetch_similar lookup" ); continue
        inputs = rs.audit_inputs( receipt )
        if inputs is None: skip( finding, NO_SHORTLIST, f"receipt {tie[ 'receipt_id' ]} is not a shortlist answer of check_exists" ); continue
        sa.enqueue_pending( data_dir, *inputs, today, known_miss=True, exclude_id=finding[ "id" ], tie=tie[ "tie" ] )
        counters[ QUEUED ] += 1
        if tie[ "tie" ] == "heuristic": counters[ HEURISTIC_QUEUED ] += 1
    return { "counters": counters, "reasons": reasons }
