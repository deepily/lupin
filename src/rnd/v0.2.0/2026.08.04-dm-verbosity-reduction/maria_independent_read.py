"""
Independent re-derivation of the unfrozen-control comparison. (María 🌸, 2026-08-11)

Reads ONLY the JSONL rows. It does not import `unfrozen_control.py`, does not
share a helper with it, and does not call a model. The point of a second read is
that it can disagree — if it re-used his tooling it could only reproduce his
arithmetic, which is not a check on anything.

    python maria_independent_read.py [live-runs/unfrozen-control-50per-band.jsonl]

WHY THIS EXISTS. §5.2 of the findings doc is both of us arguing from the wrong
column with the right one printed on screen, from a tool that was correct. A
correct tool nobody reads independently is not a safeguard.

WHAT THIS ADDS BEYOND HIS REPORT — the checks a second reader owes:

1. **Integrity of the sample itself.** Duplicate `body_sha` would mean a message
   entered the mean twice; a band label disagreeing with its own `words` count
   would mean the strata are not what they say. Both are asserted here, because
   neither is visible in a table of means.
2. **The order effect, measured rather than assumed.** He alternates arms on
   `pair_id` parity at my request. That de-confounds order only if the delta is
   actually the same in both halves — so the delta is split by `first_arm` and
   printed. If those two disagree materially, position is doing work and the
   headline is not a clean read of the arm.
3. **Whether the mean is a mean.** A whole-sample delta can be carried by three
   messages. A 10% trimmed mean and the count of messages that individually
   favour each arm say whether the headline describes the population.
4. **The damage-adjusted read, computed my own way.** His clean subset requires
   neither arm to have lost a literal. Mine additionally reports the delta with
   damaged rows' gains recomputed as zero — a harsher accounting that treats a
   destructive rewrite as having compressed nothing rather than dropping it.

TOKENIZER. Every row carries its own stamp. If rows disagree, or any row says
`chars/4 HEURISTIC`, that is printed as a caveat rather than quietly averaged —
the two units are not interchangeable.
"""

import json
import statistics
import sys

BANDS          = [ "<80", "80-150", "150-250", "250+" ]
FLAT_THRESHOLD = 0.06   # pre-registered before any rows existed
MIN_CLEAN_N    = 20     # below this, a subset delta is not reported as a number

DEFAULT_ROWS = "live-runs/unfrozen-control-50per-band.jsonl"


def band_of( words ):
    """
    Classify a message by word count, re-derived rather than trusted.

    Requires:
        - words is a non-negative integer

    Ensures:
        - returns one of the four band labels in BANDS

    Raises:
        - nothing
    """
    if words <  80: return "<80"
    if words < 150: return "80-150"
    if words < 250: return "150-250"
    return "250+"


def load( path ):
    """
    Read the run's rows.

    Requires:
        - path names a JSONL file of row dicts written by unfrozen_control.py

    Ensures:
        - returns a list of dicts, one per non-blank line
        - malformed lines are counted and reported, never silently dropped

    Raises:
        - SystemExit if the file cannot be opened
    """
    rows, bad = [], 0
    try:
        handle = open( path )
    except OSError as e:
        sys.exit( f"cannot read {path}: {e}" )

    with handle:
        for line in handle:
            line = line.strip()
            if not line: continue
            try: rows.append( json.loads( line ) )
            except Exception: bad += 1

    if bad: print( f"⚠️  {bad} unparseable line(s) — reported, not dropped silently" )
    return rows


def integrity( rows ):
    """
    Check the sample before believing any mean computed over it.

    Requires:
        - rows is a list of row dicts

    Ensures:
        - prints one line per check with an explicit pass/fail marker
        - returns True only if every check passed

    Raises:
        - nothing
    """
    ok = True

    shas   = [ r[ "body_sha" ] for r in rows if "body_sha" in r ]
    unique = len( set( shas ) )
    if unique != len( shas ):
        print( f"🔴 duplicate messages: {len(shas)} rows carry {unique} distinct body_sha "
               f"— a repeated message enters the mean more than once" )
        ok = False
    else:
        print( f"✓ {unique} distinct messages, no duplicates" )

    mislabelled = [ r for r in rows
                    if "words" in r and "band" in r and band_of( r[ "words" ] ) != r[ "band" ] ]
    if mislabelled:
        print( f"🔴 {len(mislabelled)} row(s) whose band disagrees with their own word count" )
        ok = False
    else:
        print( "✓ every band label agrees with its own word count" )

    stamps = { r.get( "tokenizer" ) for r in rows }
    if len( stamps ) > 1:
        print( f"🔴 mixed tokenizers in one run: {stamps} — these units are not interchangeable" )
        ok = False
    elif stamps and "chars/4 HEURISTIC" in stamps:
        print( "⚠️  rows are in a chars/4 ESTIMATE, not real tokens — every figure below inherits that" )
    else:
        print( f"✓ single tokenizer throughout: {stamps.pop() if stamps else 'unstamped'}" )

    firsts = {}
    for r in rows:
        if "first_arm" in r: firsts[ r[ "first_arm" ] ] = firsts.get( r[ "first_arm" ], 0 ) + 1
    if firsts: print( f"✓ call order alternated: {firsts}" )

    return ok


def summarize( label, rows, key_f="frozen_gain", key_u="unfrozen_gain" ):
    """
    Print one comparison block for a subset of paired rows.

    Requires:
        - rows is a list of rows each carrying both gain keys
        - label names the subset in one short phrase

    Ensures:
        - prints nothing but a refusal when the subset is smaller than MIN_CLEAN_N
        - returns the delta, or None when it was refused

    Raises:
        - nothing
    """
    if len( rows ) < MIN_CLEAN_N:
        print( f"{label}: n={len(rows)} — under {MIN_CLEAN_N}, no delta computed" )
        return None

    f     = statistics.mean( r[ key_f ] for r in rows )
    u     = statistics.mean( r[ key_u ] for r in rows )
    delta = u - f
    print( f"{label}: n={len(rows)}  frozen {f:.1%}  unfrozen {u:.1%}  delta {delta:+.1%}" )
    return delta


def main():
    path = sys.argv[ 1 ] if len( sys.argv ) > 1 else DEFAULT_ROWS
    rows = load( path )
    print( f"read {len(rows)} rows from {path}\n" )

    print( "── integrity ─────────────────────────────────────────────────────────" )
    integrity( rows )
    print()

    live     = [ r for r in rows if not r.get( "bypassed" ) ]
    paired   = [ r for r in live if "frozen_gain" in r and "unfrozen_gain" in r ]
    print( f"sampled {len(rows)} · bypassed {len(rows) - len(live)} · "
           f"paired {len(paired)}\n" )

    if not paired:
        print( "no paired rows — nothing to re-derive" )
        return

    print( "── headline, re-derived ──────────────────────────────────────────────" )
    delta = summarize( "all paired", paired )
    abs_delta = statistics.mean( r[ "unfrozen_removed" ] - r[ "frozen_removed" ] for r in paired )
    print( f"absolute: {abs_delta:+.1f} tokens/message removed (no denominator)\n" )

    print( "── is the mean a mean? ───────────────────────────────────────────────" )
    deltas = sorted( r[ "unfrozen_gain" ] - r[ "frozen_gain" ] for r in paired )
    cut    = max( 1, len( deltas ) // 10 )
    print( f"10% trimmed mean {statistics.mean( deltas[ cut : -cut ] ):+.1%} "
           f"vs untrimmed {statistics.mean( deltas ):+.1%}" )
    print( f"unfrozen ahead on {sum( 1 for d in deltas if d > 0 )}/{len(deltas)} messages, "
           f"behind on {sum( 1 for d in deltas if d < 0 )}\n" )

    print( "── order effect (the parity alternation, verified) ───────────────────" )
    for arm in [ "frozen", "unfrozen" ]:
        half = [ r for r in paired if r.get( "first_arm" ) == arm ]
        if half: summarize( f"  pairs where {arm} called first", half )
    print()

    print( "── damage-adjusted ───────────────────────────────────────────────────" )
    clean = [ r for r in paired
              if not r.get( "frozen_lit_missing" ) and not r.get( "unfrozen_lit_missing" ) ]
    summarize( "  undamaged only (neither arm lost a literal)", clean )

    # Harsher accounting: a rewrite that destroyed a literal compressed nothing.
    zeroed = [ { **r,
                 "frozen_gain"   : 0.0 if r.get( "frozen_lit_missing" )   else r[ "frozen_gain" ],
                 "unfrozen_gain" : 0.0 if r.get( "unfrozen_lit_missing" ) else r[ "unfrozen_gain" ] }
               for r in paired ]
    summarize( "  damage scored as zero compression", zeroed )
    print()

    for arm in [ "frozen", "unfrozen" ]:
        graded = [ r for r in paired if r.get( f"{arm}_lit_total" ) ]
        if not graded: continue
        miss  = sum( r[ f"{arm}_lit_missing" ] for r in graded )
        total = sum( r[ f"{arm}_lit_total" ]   for r in graded )
        hurt  = sum( 1 for r in graded if r[ f"{arm}_lit_missing" ] )
        print( f"damage · {arm:<8} {miss}/{total} literals lost ({miss/total:.1%}) "
               f"in {hurt}/{len(graded)} messages" )
    print()

    print( "── verdict ───────────────────────────────────────────────────────────" )
    if delta is None:
        print( "no headline delta was computable" )
    elif delta >= FLAT_THRESHOLD:
        print( f"JUMP {delta:+.1%} against the pre-registered {FLAT_THRESHOLD:.0%} line." )
    else:
        print( f"FLAT {delta:+.1%} against the pre-registered {FLAT_THRESHOLD:.0%} line —" )
        print( "the ceiling is the material UNDER THESE PRESERVATION REQUIREMENTS." )
        print( "Requirement 31 of the prompt binds BOTH arms to keep every number, port" )
        print( "and reference exactly as written, so this does not license the broader" )
        print( "claim that the material is incompressible. A third arm separates them." )


if __name__ == "__main__":
    main()
