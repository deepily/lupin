"""
Prose-reference scanner: flags rows citing a terminal task id in prose with no edge.

`blocker_terminal` (`task_store_owed.blocker_is_terminal`) catches a stranded row whose
dependency is a typed `blocked_by` edge. It is blind to the commoner shape, a row that names its
precondition only in prose. Such a dependency cannot be scheduled, chased or transitioned.

The prose arm has two halves, and only one is detectable:

    (A) Cites an id in prose, "blocked on <id>". Scannable: extract the token, resolve it,
        and flag a citation of a terminal id that has no matching edge.
    (B) Cites a premise, "until the demos ship". There is no token to resolve. This is an
        authoring problem, because no oracle can follow a dependency never written as an id.

This module implements (A) only, and is built so that boundary is impossible to miss.
It must not produce a false green, an instrument answering a narrower question than its reader believes.
A clean (A) result reads as "no dangling preconditions" while the unscannable (B) half sits underneath.
So `scope_disclosure()` is required output: the CLI prints it every run, and `scan_rows` returns it.

Counts are never collapsed to one. An 8-hex token may be a task id, a commit sha or a session
id, and no regex separates them. Shas share the shape and are dense in the bodies. Session ids
are the largest population: every amendment header is stamped `<persona> <8-hex>`. That count
grows continuously, which means neither a broken scanner nor a spreading defect.

A false positive, a sha reported as a broken id, is visible. A false negative is silent and more
dangerous: treating every unresolvable token as "not a task id" loses a mistyped id among the shas.
So the report carries the unresolved bucket as a number, split by tier, and the amendment-stamp
exclusion as its own count. An unreported exclusion looks like tokens never seen, and an empty-looking
bucket that is merely unexamined is a false green.

Tiers:
    - Full UUID citation: high confidence, resolved against the task store.
    - 8-hex citation: low confidence. It lands in unresolved by default and is never resolved
      by prefix, because a prefix resolve turns an amendment stamp into a finding.

Store ids are 36-char dashed UUIDs, and the 8-hex form is an abbreviation. A dashed UUID cannot
collide with a 40-hex git sha, but the tier buys nothing against other UUIDs the fleet writes.
Session ids are one. A resolve therefore means "found in the task store", not "is UUID-shaped".
The caller injects `status_by_id` from a task-store lookup, and this module has no resolver of its own.

The long-run fix is authoring: full ids shrink the unresolved bucket; a dependency minted as a row leaves it. It never reaches zero.
"""

import re

from cosa.rest.task_store_rules import TERMINAL_STATUSES

from cosa.rest.task_store_owed import is_canonical_uuid, item_blocker_ids


# A full canonical UUID as it appears inside prose. 40-hex git shas cannot match: the
# dashes are required and the group widths are fixed.
CANONICAL_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

# The 8-hex abbreviation we all type. Deliberately matched ONLY after canonical UUIDs have
# been removed from the text, so a UUID's first group is never double-counted as a prefix.
ABBREVIATED_ID_RE = re.compile( r"\b[0-9a-f]{8}\b" )

# The amendment header this store writes on every `task_amend`:
#   [amendment · mr radio 43ff094e · 2026-07-25T22:02:28.169063+00:00]
# The 8-hex inside is a SESSION id and is never a citation. Excluded before counting, and
# the exclusion is REPORTED (see module docstring).
AMENDMENT_STAMP_RE = re.compile( r"\[amendment\s*·[^\]]*?\b([0-9a-f]{8})\b[^\]]*\]" )


def strip_amendment_stamps( body ):
    """
    Remove amendment header stamps from a body and return how many were removed.

    The count is the point, more than the strip. A silent exclusion looks like a scanner that never saw those tokens.
    Without the count a caller cannot tell a shrinking bucket from a working filter.
    Stamps are the largest 8-hex population and grow once per amendment, indefinitely.

    Requires:
        - body is any object (non-str yields ( "", 0 ))

    Ensures:
        - returns ( text_with_stamps_removed, n_stamps_removed )
        - n counts stamps, not distinct session ids. Two amendments by one seat count 2,
          because the question is how much text was withheld from the scan
        - never raises
    """
    if not isinstance( body, str ): return ( "", 0 )

    stamps = AMENDMENT_STAMP_RE.findall( body )
    return ( AMENDMENT_STAMP_RE.sub( " ", body ), len( stamps ) )


def extract_prose_refs( body ):
    """
    Pull id-shaped citations out of one body, tiered by confidence.

    Requires:
        - body is any object (non-str yields empty tiers with zero exclusions)

    Ensures:
        - returns { "canonical": [...], "abbreviated": [...], "stamps_excluded": int }
        - `canonical` holds full 36-char dashed UUIDs, lowercased, de-duplicated and in
          first-appearance order, so a body citing one id four times is one citation
        - `abbreviated` holds 8-hex tokens found after canonical UUIDs and amendment
          stamps are removed, de-duplicated, order-preserved
        - a UUID's own first group never lands in `abbreviated`, because canonicals are
          excised from the text before the abbreviation pass
        - never raises
    """
    text, stamps_excluded = strip_amendment_stamps( body )

    canonical = [ ]
    for match in CANONICAL_UUID_RE.findall( text ):
        lowered = match.lower()
        if lowered not in canonical: canonical.append( lowered )

    # Excise canonicals BEFORE hunting abbreviations, or every full UUID donates a
    # phantom 8-hex "citation" of itself.
    remainder = CANONICAL_UUID_RE.sub( " ", text )

    abbreviated = [ ]
    for match in ABBREVIATED_ID_RE.findall( remainder ):
        if match not in abbreviated: abbreviated.append( match )

    return { "canonical": canonical, "abbreviated": abbreviated, "stamps_excluded": stamps_excluded }


def classify_prose_refs( body, blocked_by, status_by_id ):
    """
    Classify one row's prose citations against resolved task-store statuses.

    A finding is a citation of a terminal id with no matching `blocked_by` edge. An edge-covered citation is
    already covered by `blocker_is_terminal`, and reporting it here double-counts one row, inflating the count.

    Requires:
        - body is the row's body (any type)
        - blocked_by is the row's blocked_by value (any type)
        - status_by_id maps id -> status str, or -> None for looked-up-and-absent; an id
          not present as a key was never looked up, which is a different fact

    Ensures:
        - returns dict with keys: findings, resolved_live, resolved_terminal,
          unresolved_canonical, unresolved_abbreviated, stamps_excluded, edge_covered
        - `findings` is a list of { "id", "status", "reason" }, the actionable half
        - an abbreviated 8-hex token is never resolved and never a finding. It counts
          into `unresolved_abbreviated` by tier, because a prefix resolve turns a commit
          sha or an amendment session id into a false finding
        - a canonical id never looked up counts as `unresolved_canonical`, not as a
          finding, because absence from the map is a fact about the lookup, not about the row
        - a canonical id looked up and absent is a finding ("absent"), because the typed
          tier removes the shape collision that makes an 8-hex absence ambiguous
        - never raises
    """
    refs         = extract_prose_refs( body )
    edge_ids     = { ref_id.lower() for ref_id in item_blocker_ids( blocked_by ) }

    findings             = [ ]
    resolved_live        = 0
    resolved_terminal    = 0
    unresolved_canonical = 0
    edge_covered         = 0

    # NO `is_canonical_uuid` RE-CHECK HERE, AND THAT IS DELIBERATE. The first draft had one.
    # It was UNREACHABLE — CANONICAL_UUID_RE fixes every group width, so its every match is
    # 36 chars and parses. A pragma would have hidden a branch nobody could prove works, which
    # is the shape row 3c0d3d1c just corrected in pyproject.toml. It is also REDUNDANT: were
    # the regex ever loosened, a non-canonical token simply misses the `status_by_id` lookup
    # below and lands in `unresolved_canonical` — the identical outcome, one branch later.
    # `test_the_canonical_regex_only_ever_yields_canonical_uuids` pins the invariant instead.
    for ref_id in refs[ "canonical" ]:
        if ref_id not in status_by_id:
            unresolved_canonical += 1
            continue

        status = status_by_id[ ref_id ]
        if status is not None and status not in TERMINAL_STATUSES:
            resolved_live += 1
            continue

        # Terminal or absent — the wait can never be satisfied. Suppress only when a typed
        # edge already carries it, so the two instruments do not both count one strand.
        resolved_terminal += 1
        if ref_id in edge_ids:
            edge_covered += 1
            continue
        findings.append( {
            "id"     : ref_id,
            "status" : status,
            "reason" : "terminal" if status is not None else "absent"
        } )

    return {
        "findings"               : findings,
        "resolved_live"          : resolved_live,
        "resolved_terminal"      : resolved_terminal,
        "unresolved_canonical"   : unresolved_canonical,
        "unresolved_abbreviated" : len( refs[ "abbreviated" ] ),
        "stamps_excluded"        : refs[ "stamps_excluded" ],
        "edge_covered"           : edge_covered
    }


def scope_disclosure( bodies_scanned, counts ):
    """
    Return the text stating what a scan could not see.

    The disclosure is mandatory output. A clean (A) result that omits the unscanned (B) arm
    reads as "no dangling preconditions" while the larger, unscannable half was never
    examined. A caller reports a verdict together with its reach.

    Requires:
        - bodies_scanned is an int
        - counts is a dict shaped like `aggregate_counts`'s return

    Ensures:
        - returns a multi-line str naming: the bodies scanned, the three buckets, the
          amendment-stamp exclusion, and both blind spots (the (B) premise arm and the
          low-confidence 8-hex tier)
        - the text is emitted whether the scan was clean or not
        - never raises
    """
    return (
        f"SCOPE OF THIS SCAN — read before believing the verdict\n"
        f"  scanned            : {bodies_scanned} non-terminal bodies for ID-SHAPED citations\n"
        f"  resolved live      : {counts[ 'resolved_live' ]}\n"
        f"  resolved terminal  : {counts[ 'resolved_terminal' ]} "
        f"({counts[ 'edge_covered' ]} already carried by a blocked_by edge, reported by blocker_terminal)\n"
        f"  UNRESOLVED         : {counts[ 'unresolved_canonical' ]} canonical + "
        f"{counts[ 'unresolved_abbreviated' ]} abbreviated 8-hex (NOT resolved by tier — "
        f"holds commit shas, session ids AND any genuinely dead id, indistinguishably)\n"
        f"  stamps excluded    : {counts[ 'stamps_excluded' ]} amendment header session-ids "
        f"removed before counting\n"
        f"  NOT COVERED (A)    : the low-confidence 8-hex tier is never resolved; a dead id "
        f"spelled as a prefix is invisible to this check\n"
        f"  NOT COVERED (B)    : rows citing a PREMISE with no id — \"until the demos ship\", "
        f"\"pending Rick's ruling\" — have no token to resolve and are NOT covered by this "
        f"check at all. A clean result above says nothing about them."
    )


def aggregate_counts( per_row ):
    """
    Sum the bucket counts across per-row classifications.

    Requires:
        - per_row is an iterable of dicts returned by `classify_prose_refs`

    Ensures:
        - returns a dict with the six count keys, all ints, zeroed for an empty input
        - `findings` is not summed here, because the caller keeps the rows, not just the number
        - never raises
    """
    keys   = ( "resolved_live", "resolved_terminal", "unresolved_canonical",
               "unresolved_abbreviated", "stamps_excluded", "edge_covered" )
    totals = { key: 0 for key in keys }
    for row in per_row:
        for key in keys: totals[ key ] += row[ key ]
    return totals


def scan_rows( rows, status_by_id ):
    """
    Run the (A) scan across a set of rows and build the reportable result.

    Requires:
        - rows is an iterable of dicts carrying at least `id`, `body`, `blocked_by`
        - status_by_id maps id -> status str or None, per `classify_prose_refs`

    Ensures:
        - returns { "findings": [...], "counts": {...}, "bodies_scanned": int,
                    "scope": str }
        - each finding carries the citing row's id and title alongside the cited ref, so
          the report names a row a human can open
        - `scope` is always populated — a caller cannot obtain counts without it
        - never raises
    """
    per_row  = [ ]
    findings = [ ]

    for row in rows:
        result = classify_prose_refs( row.get( "body" ), row.get( "blocked_by" ), status_by_id )
        per_row.append( result )
        for finding in result[ "findings" ]:
            findings.append( {
                "row_id"     : row.get( "id" ),
                "row_title"  : row.get( "title" ),
                "row_status" : row.get( "status" ),
                "cited_id"   : finding[ "id" ],
                "cited_state": finding[ "status" ],
                "reason"     : finding[ "reason" ]
            } )

    counts = aggregate_counts( per_row )
    return {
        "findings"       : findings,
        "counts"         : counts,
        "bodies_scanned" : len( per_row ),
        "scope"          : scope_disclosure( len( per_row ), counts )
    }


def candidate_ref_ids( rows ):
    """
    Return every canonical id cited in prose across `rows`, for one batch status lookup.

    The function returns only canonical ids. A caller cannot resolve the abbreviated bucket
    through it, so the prefix resolve that manufactures false findings has no entry point.

    Requires:
        - rows is an iterable of dicts carrying `body`

    Ensures:
        - returns a de-duplicated list of lowercase canonical UUID strings
        - abbreviated 8-hex tokens are never included
        - never raises
    """
    seen = [ ]
    for row in rows:
        for ref_id in extract_prose_refs( row.get( "body" ) )[ "canonical" ]:
            if ref_id not in seen: seen.append( ref_id )
    return seen


def quick_smoke_test():
    """Exercise the scanner on a synthetic board, including its negative control."""
    import cosa.utils.util as du

    du.print_banner( "task_store_prose_refs quick smoke test", prepend_nl=True )

    live_id     = "11111111-1111-4111-8111-111111111111"
    dead_id     = "22222222-2222-4222-8222-222222222222"
    rows        = [
        { "id": "r1", "title": "cites a dropped precondition", "status": "queued",
          "body": f"blocked on {dead_id} until it lands\n[amendment · mr radio 43ff094e · ts]",
          "blocked_by": [ ] },
        { "id": "r2", "title": "cites a live one", "status": "queued",
          "body": f"waiting on {live_id}", "blocked_by": [ ] },
        { "id": "r3", "title": "premise only — the (B) arm", "status": "queued",
          "body": "blocked until the demos ship", "blocked_by": [ ] },
    ]
    status_by_id = { live_id: "queued", dead_id: "dropped" }

    report = scan_rows( rows, status_by_id )
    print( f"✓ findings          : {len( report[ 'findings' ] )} (expected 1)" )
    print( f"✓ resolved live     : {report[ 'counts' ][ 'resolved_live' ]} (expected 1)" )
    print( f"✓ stamps excluded   : {report[ 'counts' ][ 'stamps_excluded' ]} (expected 1)" )
    print( f"✓ (B) row invisible : r3 produced no finding and no count — by construction" )
    print()
    print( report[ "scope" ] )


if __name__ == "__main__":
    quick_smoke_test()
