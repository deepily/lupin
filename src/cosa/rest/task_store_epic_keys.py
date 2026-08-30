"""
Epic-key drift detector — the pure half. Store row `5246bb67`.

WHAT THIS IS FOR
----------------
The epic layer is the only thing that answers "where is the work going" without reading
every live body. It lives in `TaskItem.correlation_key` as an `epic:<slug>` value, and
NOTHING ENFORCES IT AT CREATION — so it drifts, and it has been rebuilt by hand twice in
eleven days. This module finds the drift. It does not prevent it.

🔴 WHY A DETECTOR AND NOT A CREATION-TIME CHECK — READ THIS BEFORE PROPOSING ONE
--------------------------------------------------------------------------------
The obvious fix is to reject a create with no `correlation_key`. Measured on the live
board 2026-08-30, that check would be a NON-EMPTY-STRING ASSERTION WEARING ENFORCEMENT'S
CLOTHES, because the field has THREE TENANTS and only one of them is an epic key:

    epic:<slug>                          191 rows   the epic layer
    cc-task:<sid>:g<gen>:<harness_id>     52 rows   the harness mirror's IDEMPOTENCY
                                                    UPSERT KEY, probed on read via
                                                    GET /api/tasks?correlation_key=...
    cascade-quick-ask  (no prefix)       289 rows   a free-text run tag agents typed
                                                    through the ordinary MCP door

A blank-check is satisfied by all three. It would pass every mirrored row and every
hand-typed tag while the board still cannot group them — reporting full compliance on
rows it never actually covered. That is the failure the row was raised to prevent, one
level in.

REACH — WHAT THIS DETECTOR COVERS, AND WHAT IT DOES NOT
--------------------------------------------------------
✅ COVERS EVERY CREATION PATH, including ones nobody enumerated. It reads the ROWS, not
   the doors. A row minted through the MCP verb, the hook lane, a raw POST, a future
   direct-repo call, or hand-written SQL is equally visible here, because all of them
   end up as a row. This is the whole reason to prefer it over a guard at one entrance:
   a check installed at `POST /api/tasks` covers the three doors that exist today and
   silently covers nothing minted any other way, while still reading as "enforced".

❌ DOES NOT PREVENT DRIFT. It makes drift impossible to miss; it does not make it
   impossible. Between two runs the board can be wrong and nobody is told.

❌ CANNOT SAY WHETHER A MIRROR ROW *SHOULD* HAVE AN EPIC. A `cc-task:` row's key is load-
   bearing for idempotency — re-stamping it with `epic:` would break the upsert probe.
   So those rows are reported in their own bucket and are NEVER a finding. If the mirror
   lane ever runs again, those rows are ungroupable AND unfixable-by-re-stamping, and
   that is a schema problem (give the epic its own column), not something a scan can fix.

❌ ONLY SEES ROWS THAT EXIST WHEN IT RUNS, and only the population the caller hands it.
   A caller that pages a subset of the board gets a verdict about that subset. The caller
   is responsible for reporting truncation; `reach_disclosure` names the count it saw.

⚠️ AN UNKNOWN `epic:` SLUG IS A FINDING, NOT A PASS. A key like `epic:not-a-real-thing`
   satisfies the prefix and renders on the board as a de-slugged name with no story text.
   It is the near-miss that a prefix check alone would wave through, so it gets its own
   bucket rather than being folded into the healthy count.

Pure — no DB, no HTTP, no clock. The caller is `src/scripts/scan-epic-key-drift.py`;
a detector with no caller is still silence (`task_store_prose_refs` learned that first).
"""

EPIC_PREFIX   = "epic:"
MIRROR_PREFIX = "cc-task:"

# The four buckets a correlation_key can land in. Named here rather than as bare strings
# at the call sites so a reader can enumerate the space without reading classify_key.
BUCKET_EPIC    = "epic"       # epic:<slug> — groupable
BUCKET_MIRROR  = "mirror"     # cc-task:... — a DIFFERENT tenant, never a finding
BUCKET_FOREIGN = "foreign"    # a non-empty key that is neither — LOOKS keyed, is not
BUCKET_BLANK   = "blank"      # absent / empty / whitespace


def classify_key( correlation_key ):
    """
    Bucket one row's correlation_key by which tenant of the field it belongs to.

    Requires:
        - correlation_key is a str or None (any other type is coerced via str())

    Ensures:
        - returns exactly one of BUCKET_EPIC / BUCKET_MIRROR / BUCKET_FOREIGN / BUCKET_BLANK
        - None, "", and whitespace-only all return BUCKET_BLANK — a key of spaces is
          absent for every purpose the board cares about, and treating it as present is
          how a blank-check reports a row it cannot group
        - never raises
    """
    if correlation_key is None: return BUCKET_BLANK

    text = str( correlation_key ).strip()
    if not text:                          return BUCKET_BLANK
    if text.startswith( EPIC_PREFIX ):    return BUCKET_EPIC
    if text.startswith( MIRROR_PREFIX ):  return BUCKET_MIRROR
    return BUCKET_FOREIGN


def audit_rows( rows, known_epic_keys=None ):
    """
    Classify every row and return the findings plus the full bucket counts.

    Requires:
        - rows is an iterable of dicts carrying at least "id"; "correlation_key",
          "status", "title" and "project" are read when present
        - known_epic_keys is an iterable of `epic:<slug>` strings (the keys
          `GET /api/epic-stories` serves) or None to skip the unknown-slug check

    Ensures:
        - returns { "findings": [...], "counts": {...}, "rows_seen": int,
                    "known_keys_checked": bool }
        - a finding is a dict { id, title, status, project, correlation_key, bucket,
          reason } where reason is one of "blank" / "foreign" / "unknown_epic"
        - BUCKET_MIRROR rows are counted and NEVER reported as findings — see the module
          docstring; their key is load-bearing elsewhere and cannot be re-stamped
        - when known_epic_keys is None the unknown-slug check is SKIPPED and
          known_keys_checked is False, so a caller cannot mistake "not checked" for
          "checked and clean"
        - counts always carries all four bucket keys plus "unknown_epic", even at zero —
          a bucket that is absent from a report is indistinguishable from one that was
          never examined
        - never raises on a malformed row; a row with no "id" is still classified
    """
    known    = set( known_epic_keys ) if known_epic_keys is not None else None
    counts   = { BUCKET_EPIC: 0, BUCKET_MIRROR: 0, BUCKET_FOREIGN: 0, BUCKET_BLANK: 0,
                 "unknown_epic": 0 }
    findings = [ ]
    seen     = 0

    for row in rows:
        seen  += 1
        key    = row.get( "correlation_key" )
        bucket = classify_key( key )
        counts[ bucket ] += 1

        reason = None
        if bucket == BUCKET_BLANK:
            reason = "blank"
        elif bucket == BUCKET_FOREIGN:
            reason = "foreign"
        elif bucket == BUCKET_EPIC and known is not None and str( key ).strip() not in known:
            reason = "unknown_epic"
            counts[ "unknown_epic" ] += 1

        if reason is not None:
            findings.append( {
                "id"              : row.get( "id" ),
                "title"           : row.get( "title" ),
                "status"          : row.get( "status" ),
                "project"         : row.get( "project" ),
                "correlation_key" : key,
                "bucket"          : bucket,
                "reason"          : reason,
            } )

    return {
        "findings"           : findings,
        "counts"             : counts,
        "rows_seen"          : seen,
        "known_keys_checked" : known is not None,
    }


def reach_disclosure( report, known_epic_keys=None ):
    """
    The mandatory statement of what this scan covered and what it could not.

    REQUIRED OUTPUT, NOT A COURTESY LINE — the same mandate `task_store_prose_refs.
    scope_disclosure` carries, for the same reason. A clean epic-key verdict that does
    not name the mirror bucket reads as "the board is fully grouped" while a whole tenant
    of the field sits underneath it unexamined. This function exists so a caller cannot
    report a verdict without also reporting its reach.

    Requires:
        - report is an `audit_rows` return dict
        - known_epic_keys is the same iterable passed to audit_rows, or None

    Ensures:
        - returns a multi-line str naming the rows seen, all four buckets, whether the
          unknown-slug check ran, and BOTH blind spots (the mirror tenant and the fact
          that a detector prevents nothing)
        - the text is emitted whether the scan was clean or not
        - never raises
    """
    counts     = report[ "counts" ]
    known_note = (
        f"{len( set( known_epic_keys ) )} known epic keys"
        if report[ "known_keys_checked" ] and known_epic_keys is not None
        else "SKIPPED — no key list was supplied, so an invented epic: slug was NOT checked"
    )

    return (
        f"REACH OF THIS SCAN — read before believing the verdict\n"
        f"  rows examined      : {report[ 'rows_seen' ]}\n"
        f"  epic: keys         : {counts[ BUCKET_EPIC ]} "
        f"({counts[ 'unknown_epic' ]} carrying a slug with no story entry)\n"
        f"  blank              : {counts[ BUCKET_BLANK ]} (ungrouped — the drift this exists to find)\n"
        f"  foreign keys       : {counts[ BUCKET_FOREIGN ]} (a NON-BLANK key that is not an "
        f"epic — ungrouped, and it passes any blank-check)\n"
        f"  mirror keys        : {counts[ BUCKET_MIRROR ]} (cc-task:* — a DIFFERENT tenant of "
        f"this field; NOT a finding, and NOT re-stampable: the key is load-bearing for the "
        f"mirror's idempotency probe)\n"
        f"  slug check         : {known_note}\n"
        f"  COVERS             : every creation path, including ones nobody enumerated — this "
        f"reads the ROWS, not the doors. A guard at POST /api/tasks would cover the three "
        f"doors that exist today and silently cover nothing minted any other way.\n"
        f"  DOES NOT COVER     : prevention. Between two runs the board can be wrong and "
        f"nobody is told. It also cannot say whether a mirror row SHOULD have had an epic — "
        f"that needs the epic in its own column, not a scan.\n"
        f"  SEES ONLY          : the rows handed to it. A truncated fetch yields a verdict "
        f"about a subset; the caller must say so."
    )


def quick_smoke_test():
    """Exercise the detector on a hand-built board covering all four buckets."""
    import cosa.utils.util as du

    du.print_banner( "task_store_epic_keys smoke test", prepend_nl=True )

    rows = [
        { "id": "aaaa1111", "correlation_key": "epic:board-visibility", "status": "queued" },
        { "id": "bbbb2222", "correlation_key": "epic:invented-slug",    "status": "queued" },
        { "id": "cccc3333", "correlation_key": None,                    "status": "queued" },
        { "id": "dddd4444", "correlation_key": "cascade-quick-ask",     "status": "queued" },
        { "id": "eeee5555", "correlation_key": "cc-task:s1:g0:7",       "status": "queued" },
        { "id": "ffff6666", "correlation_key": "   ",                   "status": "queued" },
    ]
    known  = [ "epic:board-visibility", "epic:unassigned" ]
    report = audit_rows( rows, known_epic_keys=known )

    expected = { BUCKET_EPIC: 2, BUCKET_MIRROR: 1, BUCKET_FOREIGN: 1, BUCKET_BLANK: 2,
                 "unknown_epic": 1 }
    ok = report[ "counts" ] == expected and len( report[ "findings" ] ) == 4

    print( f"counts   : {report[ 'counts' ]}" )
    print( f"findings : {[ f[ 'reason' ] for f in report[ 'findings' ] ]}" )
    print()
    print( reach_disclosure( report, known ) )
    print()
    print( "✓ smoke test PASSED" if ok else "✗ smoke test FAILED" )


if __name__ == "__main__":
    quick_smoke_test()
