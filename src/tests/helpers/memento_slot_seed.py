"""
memento_slot_seed.py — write a real memento SLOT for a test seat (row 8068c65e).

WHY THIS IS A SHARED HELPER AND NOT A LOCAL FIXTURE IN EACH SUITE. Four suites drive
`perform_self_respin` against a real tmp-dir disk, and each had grown its own one-line
memento writer pointing at whatever path was convenient — `tiberius-memento.md`,
`memento.md`, `.claude-memento.md`. Those were all valid while the verb accepted any
path the caller named, which was the defect. Now that placement is checked, every one
of them has to write the same shape, and four copies of "what a slot looks like" is
four things to drift out of step with memento_io — which is the writer and the only
real authority on the layout.

WHAT IT WRITES — the pair memento_io produces, not an approximation of it:
    RECORD   <repo>/.claude-memento-<persona>-<sid8>.md   header + body
    POINTER  <repo>/.claude-memento.md                    pointer header + a COPY of
                                                          the record's bytes + the nonce

TWO TIMESTAMPS, DELIBERATELY SEPARATE, and conflating them silently rewrites what a
test measures:
  * `written_at` in the record header feeds the REAP's freshness window (~20 min) and
    is what the placement/proof gate reads. Peg it to the test's `now`.
  * the `SELF-RESPIN-NONCE` line feeds self_respin's own CYCLE window (~5 min). That
    is the one a test ages out when it wants to reach the cycle-freshness gate.
Age the header instead and the run aborts at the SLOT gate first, so a test named for
the nonce gate quietly stops exercising it and still passes.
"""

import datetime

from lupin_mcp.memento_slot     import SLOT_ROOT, slot_pointer_path, slot_record_path
from lupin_mcp.self_respin_core import build_nonce_line


# Over the REAP's 1000-byte completeness floor, which is the binding one — self_respin's
# own substance floor is 400. A body sized for the smaller floor passes placement and
# then fails the reap proof, which reads as a confusing slot error in an unrelated test.
_BODY_LINE = ( "board state: manager mr radio, venue :8000 idle, next act is the "
               "containment probe; this row is mid-flight.\n" )


def seed_root_slot( repo_root, persona, session_id, *, nonce_uuid=None, nonce_ts=None,
                    written_at=None, body=None, slot=SLOT_ROOT ):
    """
    Write a seat's slot (record + pointer) under `repo_root` and return the POINTER path.

    Requires:
        - repo_root is a real directory (a pytest tmp_path); persona / session_id
          identify the seat
        - nonce_uuid, when given, is stamped into the POINTER as this cycle's nonce
        - nonce_ts / written_at are AWARE datetimes; both default to now(UTC)

    Ensures:
        - the RECORD carries a memento-record header naming this persona + session and
          `written_at`, and is over the reap's 1000-byte floor
        - the POINTER carries the banner, a `current:` line naming the record, a COPY of
          the record's bytes, and the nonce line when a nonce was asked for
        - returns str( pointer_path ) — the path a seat hands `self_respin`
    """
    now        = datetime.datetime.now( datetime.timezone.utc )
    written_at = written_at if written_at is not None else now
    nonce_ts   = nonce_ts   if nonce_ts   is not None else written_at

    record = slot_record_path( repo_root, persona, session_id, slot )
    header = ( f"<!-- memento-record: persona={persona} session_id={session_id[ :8 ].lower()} "
               f"written_at={written_at.isoformat()} slot={slot} -->\n" )
    text   = header + f"# Memento — {persona}\n" + ( body if body is not None else _BODY_LINE * 10 )
    record.parent.mkdir( parents=True, exist_ok=True )
    record.write_text( text )

    pointer = slot_pointer_path( repo_root, persona, slot )
    tail    = ( "\n" + build_nonce_line( nonce_uuid, nonce_ts ) + "\n" ) if nonce_uuid else ""
    pointer.parent.mkdir( parents=True, exist_ok=True )
    pointer.write_text(
        "<!-- MEMENTO POINTER — NOT THE RECORD. Safe to overwrite; it destroys nothing. -->\n"
        f"<!-- current: {record.name} -->\n" + text + tail
    )
    return str( pointer )
