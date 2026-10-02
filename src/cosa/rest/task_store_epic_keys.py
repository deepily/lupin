"""
Epic-key drift detector: finds rows whose correlation_key does not carry an epic.

The epic layer answers "where is the work going" without reading every live body.
It lives in `TaskItem.correlation_key` as an `epic:<slug>` value, and nothing enforces it at creation.
This module reports the drift. It does not prevent it.

A creation-time check is not used, because the field has three tenants and only one is an epic key:

    - `epic:<slug>` is the epic layer.
    - `cc-task:<sid>:g<gen>:<harness_id>` is the harness mirror's idempotency upsert key,
      probed on read via GET /api/tasks?correlation_key=...
    - `cascade-quick-ask` (no prefix) is a free-text run tag typed through the MCP door.

A non-empty check passes all three, so it would report compliance on rows it cannot group.

Reach:
    - It reads rows, not creation doors. A row from the MCP verb, the hook lane, a raw POST,
      a direct repo call or hand-written SQL is equally visible.
    - It does not prevent drift. Between two runs the board can be wrong and nobody is told.
    - It cannot say whether a mirror row should have an epic. The `cc-task:` key feeds the
      idempotency probe, so re-stamping it with `epic:` would break the upsert. Those rows
      get their own bucket and are never a finding. A separate epic column is a schema change.
    - It sees only the rows the caller hands it. A caller that pages a subset gets a verdict
      about that subset, and must report truncation. `reach_disclosure` names the count seen.
    - An unknown `epic:` slug is a finding. A key like `epic:not-a-real-thing` satisfies the
      prefix but renders as a de-slugged name with no story text, so it gets its own bucket.

Pure: no DB, no HTTP, no clock. The caller is `src/scripts/scan-epic-key-drift.py`.
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
        - None, "", and whitespace-only all return BUCKET_BLANK, because a key of spaces is
          absent for every purpose the board cares about, and treating it as present would
          report a row the board cannot group
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
        - BUCKET_MIRROR rows are counted and never reported as findings, because their key
          feeds the mirror's idempotency probe and cannot be re-stamped
        - when known_epic_keys is None the unknown-slug check is skipped and
          known_keys_checked is False, so "not checked" cannot read as "checked and clean"
        - counts always carries all four bucket keys plus "unknown_epic", even at zero,
          because an absent bucket looks the same as one that was never examined
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


def reach_disclosure( report, known_epic_keys=None, include_terminal=None, truncated=None ):
    """
    Return the text stating what a scan covered and what it could not see.

    The disclosure is mandatory: a clean verdict that omits the mirror bucket reads as "fully grouped".
    The row-status frame is part of the reach. `audit_rows` sees only rows, so the fetch's
    terminal-row filter and row cap arrive as arguments. None means "not stated".

    Requires:
        - report is an `audit_rows` return dict
        - known_epic_keys is the same iterable passed to audit_rows, or None

    Requires:
        - report is an `audit_rows` return dict
        - known_epic_keys is the same iterable passed to audit_rows, or None
        - include_terminal / truncated are True, False, or None for "not stated"

    Ensures:
        - returns a multi-line str naming the rows seen, all four buckets, whether the
          unknown-slug check ran, and both blind spots (the mirror tenant and the fact
          that a detector prevents nothing)
        - always names the row-status frame: terminal rows included, excluded, or not stated
          by the caller, and is never silent about it
        - always names whether the fetch was truncated, including when unknown
        - the text is emitted whether the scan was clean or not
        - never raises
    """
    counts     = report[ "counts" ]

    # None is NOT "no". An unstated frame prints as unstated: a default that silently
    # read as "terminal excluded" would re-create the omission this is fixing.
    if include_terminal is None:
        terminal_note = ( "NOT STATED BY THE CALLER — this scan may or may not have seen "
                          "done/dropped rows, so the counts cover an UNKNOWN slice of the board." )
    elif include_terminal:
        terminal_note = "included — done/dropped rows were in frame"
    else:
        terminal_note = ( "EXCLUDED — done/dropped rows were never fetched. A key that drifted on "
                          "a row since closed is invisible here." )

    if truncated is None:
        truncated_note = ( "NOT STATED BY THE CALLER — this verdict may describe a subset of the "
                           "board." )
    elif truncated:
        truncated_note = ( "YES — the fetch hit its row cap. This verdict describes a SUBSET; "
                           "unseen rows may carry drift." )
    else:
        truncated_note = "no — the fetch reached the end of the board"

    known_note = (
        f"{len( set( known_epic_keys ) )} known epic keys"
        if report[ "known_keys_checked" ] and known_epic_keys is not None
        else "SKIPPED — no key list was supplied, so an invented epic: slug was NOT checked"
    )

    return (
        f"REACH OF THIS SCAN — read before believing the verdict\n"
        f"  rows examined      : {report[ 'rows_seen' ]}\n"
        f"  row-status frame   : {terminal_note}\n"
        f"  fetch truncated    : {truncated_note}\n"
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
        f"  SEES ONLY          : the rows handed to it — the two frame lines above say which "
        f"rows those were. It no longer asks the CALLER to disclose that separately: a mandatory "
        f"discloser that outsources half its disclosure is how the terminal-row omission survived "
        f"review in the first place."
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
