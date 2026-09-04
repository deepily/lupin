"""
memento_slot_audit.py — compare a memento's DECLARED slot against its ACTUAL placement.

WHY THIS EXISTS (row b0f60712)
------------------------------
A memento header carries a `slot=` token. Measured 2026-09-04, it is WRITE-ONLY on
both sides:

    · the writer stamps it verbatim from a parameter and never checks it against
      where the file is about to land (memento_io.py, the header compose site);
    · no reader ever indexes it — `reap_memento.parse_memento_header` parses it into
      a dict, and the only keys any consumer pulls off that dict are `session_id`
      and `written_at`.

Both authoritative slot answers in the fleet are derived from PLACEMENT
(`respin_wake_check.classify_memento_slot`, and the reap's own
`verify_seat_memento_at_any_readable_slot`). So the header records the writer's
DECLARED INTENT and placement records the OUTCOME. They coincide exactly when the
writer files the record where its own argument said — which is what P0 6c64d2f5
broke and cd1c67d restores.

⇒ A divergence is therefore a CANDIDATE SIGNAL for that class of defect. This module
  computes it.

🔴 WHAT THIS MODULE DELIBERATELY DOES NOT DO — AND WHY (Pocholo 📣's ruling)
---------------------------------------------------------------------------
IT NEVER RETURNS A DEFECT COUNT AND IT IS NEVER A GATE.

A raw path-vs-header disagreement has at least four causes that print identically:

    (a) a real writer defect          — the 6c64d2f5 class
    (b) a hand-writer's typo          — the fleet hand-writes mementos today
    (c) `slot=tmp`                    — a design decision; tmp writes OUTSIDE the repo
    (d) legacy schema drift           — `slot=persona` / `slot=canonical`, dead vocabulary

Only (c) and (d) are separable mechanically, and this module separates them. (a) and
(b) are NOT separable from the artifact at all: a file with header `slot=X` sitting at
placement `Y` is byte-identical whichever produced it, because the header records
nothing identifying its writer. So the honest output is a NAMED, PER-FILE verdict the
reader can investigate — never an integer summing a bug, a typo, a design decision and
a dead schema.

🔴 THE TWO VOCABULARIES ARE NOT THE SAME WORDS, AND THAT BRIDGE LIVES HERE ONLY
------------------------------------------------------------------------------
    DECLARED (memento_slot.py) : "io"      "root"    (+ "tmp", from the p-is-p writer)
    ACTUAL   (respin_wake_check): "repo_io" "root"    "mirror"  "none"  "unknown"

`io` and `repo_io` are THE SAME SLOT UNDER TWO NAMES. A naive `declared == actual`
comparison reports every correctly-filed io record as a mismatch. `_DECLARED_TO_ACTUAL`
below is the single place that knowledge is written down.

WHAT IS STILL UNMEASURED, so nobody promotes it by reading this file
--------------------------------------------------------------------
· No `slot=tmp` file has EVER been observed in the wild. Cause (c) is reasoned from the
  writer's own in-line comment, not seen. `EXEMPT_TMP` is built on that comment.
"""

from cosa.agents.heartbeat_arbiter.respin_wake_check import (
    SLOT_ROOT    as ACTUAL_ROOT,
    SLOT_REPO_IO as ACTUAL_REPO_IO,
    SLOT_MIRROR  as ACTUAL_MIRROR,
    SLOT_NONE    as ACTUAL_NONE,
)
from lupin_mcp.memento_slot import SLOT_IO as DECLARED_IO, SLOT_ROOT as DECLARED_ROOT

# The p-is-p writer accepts a third slot that lupin defines no constant for: `slot=tmp`
# writes the memento OUTSIDE the repo, under a boot-wiped temp directory. Declared and
# actual can therefore NEVER match for tmp, by construction rather than by defect.
DECLARED_TMP = "tmp"

# ── The one place the two vocabularies are bridged ───────────────────────────
_DECLARED_TO_ACTUAL = {
    DECLARED_IO   : ACTUAL_REPO_IO,   # "io"   -> "repo_io"  — SAME SLOT, TWO NAMES
    DECLARED_ROOT : ACTUAL_ROOT,      # "root" -> "root"
}

# ── Verdicts. Each names a DIFFERENT remedy, which is the whole point ────────
AGREE                   = "agree"                    # nothing to do
MISMATCH                = "mismatch"                 # INVESTIGATE — (a) or (b), unseparable
EXEMPT_TMP              = "exempt_tmp"               # by construction, not a defect
EXEMPT_MIRROR           = "exempt_mirror"            # a mirror copy is a legitimate placement
UNRECOGNISED_VOCABULARY = "unrecognised_vocabulary"  # dead schema — wants a MIGRATION
NO_DECLARATION          = "no_declaration"           # header-less or slot-less
UNRESOLVED              = "unresolved"               # no path resolved to classify

#: Verdicts a reader should act on. Everything else is explanatory.
ACTIONABLE = frozenset( [ MISMATCH, UNRECOGNISED_VOCABULARY ] )


def verdict_for( declared, actual ):
    """
    Name what the relationship between a declared slot and an actual placement IS.

    Pure: no I/O, no filesystem, no clock. Every branch names a different remedy.

    Requires:
        - declared is the header's `slot=` value, or None when absent
        - actual is a placement verdict from `classify_memento_slot`, or None

    Ensures:
        - returns ( verdict, detail ) where verdict is one of this module's constants
          and detail is a human-readable sentence naming BOTH values
        - returns NO_DECLARATION when declared is None or blank — a header-less file
          is not a mismatch, it is a file with nothing to compare
        - returns UNRESOLVED when actual is None or ACTUAL_NONE
        - returns EXEMPT_TMP for declared == "tmp" REGARDLESS of actual, because a tmp
          record lands outside the repo by design and can never match
        - returns UNRECOGNISED_VOCABULARY when declared is outside {io, root, tmp} —
          a dead schema wants a migration, NOT an investigation, and conflating the two
          is what makes a defect count meaningless
        - returns EXEMPT_MIRROR when actual is the mirror root — a mirror copy is a
          legitimate placement, not a misfiled record
        - returns AGREE iff declared maps to actual through _DECLARED_TO_ACTUAL
        - returns MISMATCH otherwise — and MISMATCH alone means "go and look"
        - never raises
    """
    if declared is None or not str( declared ).strip():
        return NO_DECLARATION, "no slot declared in the header — nothing to compare"

    declared = str( declared ).strip()

    if declared == DECLARED_TMP:
        return EXEMPT_TMP, (
            f"declared={declared} is written outside the repo by construction, "
            f"so it can never match a placement (actual={actual})"
        )

    if declared not in _DECLARED_TO_ACTUAL:
        return UNRECOGNISED_VOCABULARY, (
            f"declared={declared} is not a slot name in today's vocabulary "
            f"{sorted( _DECLARED_TO_ACTUAL )} + [{DECLARED_TMP}] — this is schema drift, "
            f"and it wants a migration rather than an investigation"
        )

    if actual is None or actual == ACTUAL_NONE:
        return UNRESOLVED, f"declared={declared} but no placement resolved to compare it against"

    if actual == ACTUAL_MIRROR:
        return EXEMPT_MIRROR, f"declared={declared} sits under the mirror root — a legitimate copy"

    expected = _DECLARED_TO_ACTUAL[ declared ]
    if actual == expected:
        return AGREE, f"declared={declared} matches placement={actual}"

    return MISMATCH, (
        f"declared={declared} (expects placement={expected}) but the file sits at "
        f"placement={actual} — INVESTIGATE: this is either a writer filing to the wrong "
        f"tree or a hand-written stamp, and the artifact cannot tell you which"
    )


def audit_one( path, repo_root, read_text_fn, parse_header_fn, classify_fn ):
    """
    Classify ONE memento file by reading its header and its placement.

    The two readers are injected rather than imported here so a caller can drive this
    over a fixture corpus, and so a test can exercise every branch of `verdict_for`
    without building a filesystem for each one.

    Requires:
        - path is the memento's path
        - repo_root is the checkout the file is expected to live under, or None
        - read_text_fn( path ) returns the file's text, or None when unreadable
        - parse_header_fn( text ) returns the parsed header dict ({} when absent)
        - classify_fn( path, repo_root ) returns a placement verdict

    Ensures:
        - returns { path, declared, actual, verdict, detail, actionable }
        - an unreadable file yields NO_DECLARATION rather than raising — the audit
          reports on what it could read and says so, it never dies mid-corpus
        - `actionable` is True iff verdict is in ACTIONABLE
        - never raises
    """
    text = read_text_fn( path )
    if text is None:
        return {
            "path"       : path,
            "declared"   : None,
            "actual"     : None,
            "verdict"    : NO_DECLARATION,
            "detail"     : "file could not be read",
            "actionable" : False,
        }

    header   = parse_header_fn( text ) or {}
    declared = header.get( "slot" )
    actual   = classify_fn( path, repo_root )

    verdict, detail = verdict_for( declared, actual )
    return {
        "path"       : path,
        "declared"   : declared,
        "actual"     : actual,
        "verdict"    : verdict,
        "detail"     : detail,
        "actionable" : verdict in ACTIONABLE,
    }


def render_report( findings ):
    """
    Render an audit as lines a human can act on.

    🔴 THE HEADLINE IS NAMED FILES, NEVER A DEFECT COUNT. The per-verdict tally below
    the named files is a census of the corpus — it deliberately does NOT sum the
    verdicts into a single "defects" integer, because the causes are incommensurable.

    Requires:
        - findings is an iterable of dicts as returned by `audit_one`

    Ensures:
        - returns a list of strings
        - EVERY actionable finding is named individually, with its path and detail
        - states the corpus size, so an empty or truncated scan is visible rather than
          reading as a clean result
        - never raises
    """
    findings = list( findings )
    lines    = [ f"memento slot audit — {len( findings )} file(s) scanned" ]

    if not findings:
        lines.append( "  NOTHING SCANNED — this is not a clean result, it is an empty one" )
        return lines

    actionable = [ f for f in findings if f[ "actionable" ] ]
    if actionable:
        lines.append( f"  INVESTIGATE — {len( actionable )} file(s) named below:" )
        for f in actionable:
            lines.append( f"    [{f[ 'verdict' ]}] {f[ 'path' ]}" )
            lines.append( f"        {f[ 'detail' ]}" )
    else:
        lines.append( "  nothing to investigate" )

    tally = {}
    for f in findings:
        tally[ f[ "verdict" ] ] = tally.get( f[ "verdict" ], 0 ) + 1
    lines.append( "  census by verdict (NOT a defect count — these causes do not add up):" )
    for verdict in sorted( tally ):
        lines.append( f"    {tally[ verdict ]:5d}  {verdict}" )

    return lines
