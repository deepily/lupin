"""
Task-store PROSE-REF scanner — the (A) arm of store row 00a6bde2, item 4.

WHAT THIS IS FOR
----------------
`blocker_terminal` (task_store_owed.blocker_is_terminal) catches a stranded row whose
dependency was written as a TYPED `blocked_by` edge. It is blind to the far commoner
shape: a row that names its precondition ONLY IN PROSE. Row 31f6d447 sat blocked for
days on a precondition that had no row at all — the dependency existed as a sentence,
so it could never be scheduled, chased, or transitioned, and no edge-scanner could see it.

Row 00a6bde2's amendments split that prose arm in two, and ONLY ONE HALF IS DETECTABLE:

    (A) CITES AN ID IN PROSE  — "blocked on 97c12d68". Scannable: extract the token,
        resolve it, flag a citation of a TERMINAL id that has no matching edge.
    (B) CITES A PREMISE       — "until the demos ship", "pending Rick's ruling". NO TOKEN
        TO RESOLVE. Not a detection problem, an AUTHORING one: no oracle can follow a
        dependency that was never written as anything a machine can follow.

This module implements (A) and NOTHING ELSE. Everything below exists to make that
boundary impossible to miss.

🔴 THE FALSE-GREEN THIS MODULE MUST NOT PRODUCE (María 🌸, `fae1bbc4`, 2026-07-25 — the
load-bearing warning on the row). A scanner over (A) that reports CLEAN reads as "no
dangling preconditions" while the entire unscannable (B) half sits underneath it. That
is the SAME SHAPE as the defect this whole class is made of: an instrument answering a
narrower question than the one its reader believes it answered.

⇒ `scope_disclosure()` is therefore a REQUIRED part of the output, not a courtesy line.
   A clean result that does not say what it could not see is a defect, not a pass. The
   CLI prints it on every run, green or red, and `scan_board` returns it in the report.

WHY THE COUNTS ARE NEVER COLLAPSED TO ONE
-----------------------------------------
An 8-hex token is not necessarily a task id, and no regex separates the populations:

    · TASK IDS      — our own abbreviation of a 36-char UUID
    · COMMIT SHAs   — identical shape; dense throughout these bodies
    · SESSION IDS   — the LARGEST population, and SYSTEMATICALLY GENERATED: every
                      amendment header this store writes is stamped `<persona> <8-hex>`,
                      so the stamp format is an 8-hex generator firing once per amendment,
                      forever. A builder who sizes the bucket expecting stray noise will
                      conclude the scanner is broken; one who watches it grow will conclude
                      the class is spreading. Neither is true.

Two failure directions, and the second is the dangerous one:

    · FALSE POSITIVE — a sha resolves to nothing and is reported broken. Noisy, VISIBLE.
    · FALSE NEGATIVE — the scanner treats every unresolvable token as "not a task id,
                       skip", and a genuinely deleted or mistyped id vanishes into the
                       same silent bucket as the shas. THE REAL HAZARD.

⇒ So the report carries the UNRESOLVED bucket as a first-class number, split by
  confidence tier, and reports the amendment-stamp exclusion as its own count. AN
  EXCLUSION THAT IS APPLIED BUT NOT REPORTED IS INDISTINGUISHABLE FROM A SCANNER THAT
  NEVER SAW THOSE TOKENS. A bucket reported as empty when it is merely unexamined is the
  exact false-green this module exists to prevent.

THE TIER, AND WHY IT IS BUILDABLE TODAY
---------------------------------------
Store ids are 36-char dashed UUIDs. The 8-hex form is OUR ABBREVIATION, not the id. A
full dashed UUID cannot collide with a git sha (40 hex, no dashes), so:

    · FULL-UUID citation -> HIGH confidence. Resolve it against the task store.
    · 8-HEX citation     -> LOW confidence. Lands in UNRESOLVED **by default**, never
                            guessed at, never resolved by prefix. A prefix resolve is how
                            an amendment stamp becomes a "finding".

Both forms are already in the data — 31f6d447's edge carries a full UUID while the GCP
rows cite `97c12d68` abbreviated — so the tier is implementable against what exists, not
a rewrite proposal.

⚠️ A RESOLVE IS NOT AN IDENTITY PROOF. Session ids and task ids share the UUID space.
The check is "resolved AGAINST THE TASK STORE SPECIFICALLY", never "is UUID-shaped,
therefore is a task id". The tier buys collision-freedom with SHAs; it buys nothing
against every other UUID this fleet writes. That is why `status_by_id` is injected by the
caller from a task-store lookup and this module never invents a resolver of its own.

THE LONG-RUN FIX IS AUTHORING, NOT CODE
---------------------------------------
Every body that cites a FULL id shrinks the unresolved bucket. Same shape as the (B)
remedy — mint the dependency as a row instead of describing it. Tiering makes the bucket
SMALLER, NEVER ZERO.
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
    Remove amendment header stamps from a body and say how many were removed.

    THE COUNT IS THE POINT, not the strip. An exclusion applied silently is
    indistinguishable from a scanner that never saw those tokens — and this particular
    exclusion is the largest population in the 8-hex bucket, growing once per amendment
    forever. A caller that cannot see the number cannot tell a shrinking bucket from a
    working filter.

    Requires:
        - body is any object (non-str yields ( "", 0 ))

    Ensures:
        - returns ( text_with_stamps_removed, n_stamps_removed )
        - n counts STAMPS, not distinct session ids — two amendments by one seat count 2,
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
        - `canonical` holds full 36-char dashed UUIDs, lowercased, DE-DUPLICATED and in
          first-appearance order — a body citing one id four times is one citation
        - `abbreviated` holds 8-hex tokens found AFTER canonical UUIDs and amendment
          stamps are removed, de-duplicated, order-preserved
        - a UUID's own first group NEVER lands in `abbreviated` (canonicals are excised
          from the text before the abbreviation pass)
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

    THE FINDING IS NARROW ON PURPOSE: a citation of a TERMINAL id that has NO matching
    `blocked_by` edge. A citation that DOES have an edge is already covered by
    `blocker_is_terminal` on the read path — reporting it here would double-count the same
    stranded row under two instruments and inflate the finding count against a board that
    has not got worse.

    Requires:
        - body is the row's body (any type)
        - blocked_by is the row's blocked_by value (any type)
        - status_by_id maps id -> status str, or -> None for looked-up-and-absent; an id
          NOT PRESENT as a key was never looked up, which is a different fact

    Ensures:
        - returns dict with keys: findings, resolved_live, resolved_terminal,
          unresolved_canonical, unresolved_abbreviated, stamps_excluded, edge_covered
        - `findings` is a list of { "id", "status", "reason" } — the actionable half
        - an abbreviated 8-hex token is NEVER resolved and NEVER a finding; it counts
          into `unresolved_abbreviated` by tier, because a prefix resolve is how a commit
          sha or an amendment session id becomes a false finding
        - a canonical id never looked up counts as `unresolved_canonical`, NOT as a
          finding — absence from the map is a fact about the lookup, not about the row
        - a canonical id looked-up-and-absent IS a finding ("absent"), because the typed
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
    The mandatory statement of what this scan COULD NOT SEE.

    REQUIRED OUTPUT, NOT A COURTESY LINE (row 00a6bde2, María's mandate). A clean (A)
    result that does not name the unscanned (B) arm reads as "no dangling preconditions"
    across a board where the larger, unscannable half was never examined. This function
    exists so a caller cannot report a verdict without also reporting its reach.

    Requires:
        - bodies_scanned is an int
        - counts is a dict shaped like `aggregate_counts`'s return

    Ensures:
        - returns a multi-line str naming: the bodies scanned, the three buckets, the
          amendment-stamp exclusion, and BOTH blind spots (the (B) premise arm and the
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
        - `findings` is NOT summed here — the caller keeps the rows, not just the number
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
        - each finding carries the CITING row's id and title alongside the cited ref, so
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
    Every canonical id cited in prose across `rows`, for ONE batch status lookup.

    THE ONLY ids this returns are canonical. That is the tier, expressed as an API: a
    caller physically cannot resolve the abbreviated bucket through this function, so the
    prefix-resolve that would manufacture false findings has no seam to enter through.

    Requires:
        - rows is an iterable of dicts carrying `body`

    Ensures:
        - returns a de-duplicated list of lowercase canonical UUID strings
        - abbreviated 8-hex tokens are NEVER included
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
