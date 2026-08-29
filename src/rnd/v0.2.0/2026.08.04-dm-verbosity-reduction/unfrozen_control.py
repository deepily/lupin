"""
The unfrozen control — the one experiment §7 of the findings doc left open.

    Does the model compress BETTER when the placeholders are gone?

Arm 4 was ruled a failed experiment on 2026-08-07 after 600 live compressions
returned 3.0% where the economics needed 38%. Three causes were excluded: the
model, the prompt's ratio instruction, and placeholders-as-*the*-cause. What was
never tested is the hypothesis underneath all of it:

    Freezing is what makes a rewrite SAFE. It may also be what makes a rewrite
    IMPOSSIBLE. A placeholder carries zero semantic content, and a model asked
    what is redundant cannot judge redundancy across spans it cannot read.

⚠️ WHY THIS RE-RUNS BOTH ARMS INSTEAD OF READING THE COMMITTED A′ ROWS

The obvious cheap design is: run unfrozen once, compare against the frozen
numbers already on disk. It does not work, and the reason is worth stating so
nobody re-proposes it.

`live_corpus_run.py` records the ratio of the DELIVERED text — and on a failed
message the delivered text is the original, byte for byte. 76-78% of messages
failed, so for three messages in four the recorded ratio is 0.0 and the model's
actual output length was never written down anywhere. You cannot recover "how
much did the model shorten it" from a column that means "how much shorter was
what we shipped."

So both arms run here, fresh, and both measure a thing neither previous run
measured: **the raw model output against its own input, before any validation.**

    frozen arm    : model output vs frozen_text
    unfrozen arm  : model output vs the original body

FAIRNESS RULES, each one a way this could have been rigged by accident:

1. **Same messages.** The sampling stride is copied from live_corpus_run.py, so
   at the same PER_BAND this is the identical message set as the committed runs.
   Each row carries sha256[:16] of its body so the pairing can be verified from
   the JSONL by someone who did not run it.
2. **Same bypass population.** freeze() decides which messages are not worth
   sending to a model. That decision is computed for BOTH arms and skips both,
   so the unfrozen arm cannot look better by quietly compressing a different,
   easier set of messages.
3. **Same prompt, same model, same call.** The unfrozen arm passes the raw body
   through the identical DmCompressionAgent. It is not a fairer prompt; it is
   the same prompt with nothing frozen in the text.
4. **Paired, interleaved, one process.** Each message runs both arms back to
   back, so a warming GPU or a mid-run vLLM hiccup hits both arms equally
   instead of landing on whichever ran second.
5. **A message that errors in EITHER arm is dropped from BOTH.** The two means
   are then over an identical message set. This is the attempted basis with the
   survivor bias removed by construction rather than by discipline — §5.2 of the
   findings doc is both of us arguing from the wrong column with the right one
   printed on screen.

🔑 TWO MEASURES, AND THE RATIO IS THE BIASED ONE (María, 2026-08-11)

Placeholders make the frozen input about 26% smaller than the raw body — 57,195
tokens against 77,205 on the literals they replace. The compressible PROSE is
identical in both arms, so removing the same N tokens prints a HIGHER ratio on
the frozen arm's smaller denominator. The ratio is therefore handicapped in the
frozen arm's favour.

So every row also records **absolute tokens removed**, which has no denominator
and is the number that actually answers the question. The ratio is kept because
it is what the targets and every prior document are stated in.

The bias cuts in a useful direction: if frozen is flat and unfrozen jumps, the
jump is real *despite* the handicap. It only matters if the two land close —
and if they do, read the absolute column, not the ratio.

FIDELITY IS OBSERVED, NEVER ENFORCED (María's point 3). With freezing off there
is no delivery gate to run, so the verify tier runs as a pure observer on both
arms: it records what the rewrite damaged and blocks nothing.

⚠️ The unfrozen arm's fidelity check is STRICTER IN COVERAGE than the frozen
arm's, not laxer. It counts every literal in the raw body — including the ones
freezing would have substituted away and therefore never had to check. Measured
over an 80-message spread of the corpus: 500 verify-tier literals in the raw
bodies against 430 in the frozen texts, differing on 24 of the 80. So the
unfrozen arm is graded against about 16% more literals than the frozen arm.

That is the honest measure of damage, and it means the two fidelity columns are
NOT comparable to each other. Only the compression columns are.

🔴 COMPRESSION AND DAMAGE ARE THE SAME QUANTITY (María, 2026-08-11)

`*_removed` counts tokens that are gone, and a deleted line number is a token
that is gone. Nothing protects the unfrozen arm's literals, so **it can post a
JUMP by vandalising rather than by compressing** — and the headline number
cannot tell the two apart.

That is why the fidelity observers are not decoration. The report prints the
paired delta a second time over the **undamaged subset** — the messages where
neither arm lost a verify-tier literal — and that is the number a JUMP has to
survive. Same for the frozen arm's full validator.

🔴 WHAT A FLAT RESULT DOES AND DOES NOT LICENSE (María, 2026-08-11)

The prompt is placeholder-saturated: an entire paragraph plus Requirements 28-30
are about `[[Lnn]]`, and the unfrozen arm receives all of them with no
placeholders in its input. More to the point, **Requirement 31 applies to both
arms** — "keep every number, percentage, port, and section reference exactly as
written". The unfrozen arm is therefore NOT an unconstrained rewriter. It is the
same rewriter told to preserve the same literals in prose instead of in brackets.

So a flat result licenses:

    the ceiling is the material UNDER THESE PRESERVATION REQUIREMENTS

and NOT the stronger, unqualified "the ceiling is the material". Separating the
mechanism from the instructions needs a third arm with the placeholder
paragraphs stripped. Not run here — this arm isolates the placeholders, which is
exactly the question §7 left open, and widening it would answer neither cleanly.

NOTHING DELIVERS. Offline against the pinned corpus, no DM path, so a lossy
rewrite has nowhere to go.

PRE-REGISTERED, before any rows exist: on the paired ratio delta, **under 6
points is flat.** A and A′ reproduced at 3.0% twice, so anything inside that
neighbourhood is the same answer arriving again.

Usage:  python unfrozen_control.py [PER_BAND]     # default 10 per band
"""

import hashlib
import json
import pathlib
import statistics
import sys
import time

sys.path.insert( 0, "src" )

from cosa.agents.dm_compression.freeze import freeze, validate, count_verify_literals
from cosa.agents.dm_compression.compressor import DmCompressionAgent

SNAPSHOT = "src/tmp/arm4/dm_traffic_snapshot_2026.08.07.jsonl"
_ARGS    = [ a for a in sys.argv[ 1: ] if not a.startswith( "--" ) ]
PER_BAND = int( _ARGS[ 0 ] ) if _ARGS and "--report-only" not in sys.argv else 10

# The pin from CORPUS-MANIFEST.md. Checked at startup, before a single model
# call — every defect family in this workstream last week was some version of
# "the file I think I am reading".
CORPUS_SHA256 = "94b1c192bf777e03ac84e4599d30a34204289aa1d44e1548b1dc93db3d185d1d"

# Pre-registered before the run. See the module docstring.
FLAT_THRESHOLD = 0.06

# The undamaged subset is the number a JUMP has to survive, and it may be thin:
# frozen validation failed ~76% last time, and nothing protects the unfrozen
# arm's literals. Below this many clean messages the report REFUSES to quote a
# delta and prints UNCONFIRMED instead.
#
# This is a gate rather than a note because the alternative is remembering to be
# careful while looking at a number that confirms what you hoped. A confirmatory
# delta on n=6 is worse than an honest "not enough rows". (María, 2026-08-11,
# pre-registered before any of these rows existed.)
MIN_CLEAN_N = 20

BANDS       = [ "<80", "80-150", "150-250", "250+" ]
BAND_TARGET = { "<80": 0.15, "80-150": 0.30, "150-250": 0.45, "250+": 0.60 }

try:
    import tiktoken
    _ENC = tiktoken.get_encoding( "o200k_base" )
    def ntok( s ): return len( _ENC.encode( s ) )
    TOKENIZER = "o200k_base"
except Exception:
    # ⚠️ Stamped on EVERY row, not just printed once at the top. A row that does
    # not carry its units cannot tell a later reader whether it is in real
    # tokens or in a chars/4 estimate, and the two are not interchangeable.
    def ntok( s ): return max( 1, round( len( s ) / 4 ) )
    TOKENIZER = "chars/4 HEURISTIC"


def band_of( words ):
    if words <  80: return "<80"
    if words < 150: return "80-150"
    if words < 250: return "150-250"
    return "250+"


def call_model( text ):
    """
    Send one body to the compressor and return ( raw_output, error, latency ).

    Requires:
        - text is a non-empty string

    Ensures:
        - returns ( str|None, str|None, float ); exactly one of the first two is None
        - never raises — a model failure comes back as an error string

    Raises:
        - nothing
    """
    started = time.time()
    try:
        agent    = DmCompressionAgent( frozen_text=text )
        response = agent.run_prompt()
    except Exception as e:
        return None, f"{type( e ).__name__}: {e}", time.time() - started

    out = response.get( "compressed" ) if isinstance( response, dict ) else None
    if not out: return None, "model returned no compressed body", time.time() - started
    return out, None, time.time() - started


def literal_damage( before, after, namespace="" ):
    """
    Count verify-tier literals the rewrite lost or altered. Observer only.

    Requires:
        - before and after are strings
        - namespace is the FrozenMessage namespace, or "" when nothing is frozen

    Ensures:
        - returns ( n_missing, n_expected ) as a multiset difference
        - n_missing counts occurrences, not distinct literals, so dropping one
          of three "8000"s registers
        - gates nothing and raises nothing

    Raises:
        - nothing
    """
    want = count_verify_literals( before, namespace )
    got  = count_verify_literals( after,  namespace )
    missing = sum( max( 0, n - got.get( lit, 0 ) ) for lit, n in want.items() )
    return missing, sum( want.values() )


def script_sha():
    """
    sha256[:16] of this file, stamped onto every row it writes.

    Requires:
        - __file__ is readable

    Ensures:
        - returns a 16-char hex digest of the script's own bytes
        - the rows can therefore name the code that produced them, which a
          later reader cannot otherwise recover — the script is editable and
          the rows are not dated by it

    Raises:
        - nothing
    """
    return hashlib.sha256( pathlib.Path( __file__ ).read_bytes() ).hexdigest()[ :16 ]


def check_corpus():
    """
    Refuse to run against a corpus that is not the pinned one.

    Requires:
        - SNAPSHOT names a readable file

    Ensures:
        - returns the file's sha256 when it matches CORPUS_SHA256
        - exits non-zero, before any model call, on a mismatch or a missing file

    Raises:
        - nothing; a bad corpus exits rather than raising
    """
    path = pathlib.Path( SNAPSHOT )
    if not path.exists():
        sys.exit( f"corpus missing: {SNAPSHOT}\nsee CORPUS-MANIFEST.md — the corpus is deliberately not in git" )

    digest = hashlib.sha256()
    with open( path, "rb" ) as handle:
        for chunk in iter( lambda: handle.read( 1 << 20 ), b"" ): digest.update( chunk )
    actual = digest.hexdigest()

    if actual != CORPUS_SHA256:
        sys.exit( f"corpus sha256 MISMATCH\n  expected {CORPUS_SHA256}\n  actual   {actual}\n"
                  f"A different digest means a different corpus. Every arm-4 ratio would have to "
                  f"be re-derived rather than compared across it — see CORPUS-MANIFEST.md." )

    return actual


def main():
    corpus_sha = check_corpus()
    sha        = script_sha()
    print( f"corpus sha256 verified against CORPUS-MANIFEST: {corpus_sha[:16]}…", flush=True )
    print( f"script sha256[:16]: {sha} — stamped on every row", flush=True )

    bodies = []
    for line in open( SNAPSHOT ):
        line = line.strip()
        if not line: continue
        try: record = json.loads( line )
        except Exception: continue
        if record.get( "body" ): bodies.append( record[ "body" ] )

    by_band = { b: [] for b in BANDS }
    for body in bodies: by_band[ band_of( len( body.split() ) ) ].append( body )

    sample = []
    for b in BANDS:
        pool   = by_band[ b ]
        stride = max( 1, len( pool ) // PER_BAND )
        sample += [ ( b, body ) for body in pool[ ::stride ][ :PER_BAND ] ]

    print( f"corpus {len(bodies)} bodies · sampling {PER_BAND}/band · {len(sample)} total · "
           f"tokenizer {TOKENIZER} · PAIRED frozen-vs-unfrozen", flush=True )
    print( f"pre-registered: paired ratio delta under {FLAT_THRESHOLD:.0%} is FLAT", flush=True )
    print( flush=True )

    results     = []
    started_all = time.time()

    for i, ( b, body ) in enumerate( sample, 1 ):

        frozen = freeze( body )

        # A stable identity for the message itself, so the pairing can be
        # checked — and re-derived — by someone reading only the JSONL.
        base = {
            "pair_id"    : i,
            "body_sha"   : hashlib.sha256( body.encode( "utf-8" ) ).hexdigest()[ :16 ],
            "tokenizer"  : TOKENIZER,
            "script_sha" : sha,
            "band"       : b,
            "words"      : len( body.split() ),
        }

        # Rule 2: the bypass decision belongs to freeze() and applies to BOTH
        # arms. Letting the unfrozen arm run on messages the frozen arm skipped
        # would compare two different message populations.
        if frozen.should_bypass:
            results.append( { **base, "bypassed" : True, "bypass_reason" : frozen.bypass_reason } )
            print( f"  [{i:>3}/{len(sample)}] · {b:<8} bypass: {frozen.bypass_reason[:50]}", flush=True )
            continue

        # Interleaving equalises drift ACROSS pairs, but running frozen first
        # every time makes position WITHIN the pair a constant — order becomes
        # confounded with arm. Alternate on pair_id parity and stamp which arm
        # went first, so the confound can be tested from the rows.
        frozen_first = ( i % 2 == 1 )
        if frozen_first:
            frozen_out,   frozen_err,   frozen_lat   = call_model( frozen.frozen_text )
            unfrozen_out, unfrozen_err, unfrozen_lat = call_model( body )
        else:
            unfrozen_out, unfrozen_err, unfrozen_lat = call_model( body )
            frozen_out,   frozen_err,   frozen_lat   = call_model( frozen.frozen_text )

        row = {
            **base,
            "bypassed"          : False,
            "first_arm"         : "frozen" if frozen_first else "unfrozen",
            "frozen_char_ratio" : round( frozen.frozen_char_ratio, 4 ),
            "frozen_in_tok"     : ntok( frozen.frozen_text ),
            "unfrozen_in_tok"   : ntok( body ),
            "frozen_err"        : frozen_err,
            "unfrozen_err"      : unfrozen_err,
            "frozen_lat"        : round( frozen_lat, 2 ),
            "unfrozen_lat"      : round( unfrozen_lat, 2 ),
        }

        # Each arm against its OWN input. `*_removed` is the denominator-free
        # measure and is the one to read when the ratios land close — see the
        # module docstring.
        if frozen_out is not None:
            row[ "frozen_out_tok" ] = ntok( frozen_out )
            row[ "frozen_removed" ] = row[ "frozen_in_tok" ] - row[ "frozen_out_tok" ]
            row[ "frozen_gain" ]    = round( row[ "frozen_removed" ] / row[ "frozen_in_tok" ], 4 )
            # Observers. Neither gates anything.
            row[ "frozen_valid" ]   = validate( frozen_out, frozen ).ok
            miss, want              = literal_damage( frozen.frozen_text, frozen_out, frozen.namespace )
            row[ "frozen_lit_missing" ], row[ "frozen_lit_total" ] = miss, want

        if unfrozen_out is not None:
            row[ "unfrozen_out_tok" ] = ntok( unfrozen_out )
            row[ "unfrozen_removed" ] = row[ "unfrozen_in_tok" ] - row[ "unfrozen_out_tok" ]
            row[ "unfrozen_gain" ]    = round( row[ "unfrozen_removed" ] / row[ "unfrozen_in_tok" ], 4 )
            miss, want                = literal_damage( body, unfrozen_out )
            row[ "unfrozen_lit_missing" ], row[ "unfrozen_lit_total" ] = miss, want

        results.append( row )

        fg = f"{row['frozen_gain']:6.1%}"   if "frozen_gain"   in row else "  ERR "
        ug = f"{row['unfrozen_gain']:6.1%}" if "unfrozen_gain" in row else "  ERR "
        print( f"  [{i:>3}/{len(sample)}] {b:<8} frozen {fg}   unfrozen {ug}   "
               f"{frozen_lat + unfrozen_lat:5.1f}s", flush=True )

    elapsed = time.time() - started_all

    out_dir = pathlib.Path( __file__ ).parent / "live-runs"
    out_dir.mkdir( parents=True, exist_ok=True )
    out_path = out_dir / f"unfrozen-control-{PER_BAND}per-band.jsonl"
    with open( out_path, "w" ) as handle:
        for r in results: handle.write( json.dumps( r ) + "\n" )

    report( results, elapsed, out_path )


def banded_table( title, rows, frozen_of, unfrozen_of, fmt="pct", show_target=False ):
    """
    Print one frozen-vs-unfrozen table, per band and whole-sample.

    Every table in this report goes through here, deliberately. The per-band
    thinness marker existed on the ratio table and not on the clean/ITT tables
    for exactly as long as the two were written out separately — the same shape
    of gap this run keeps finding. One printer, one floor, no second place to
    forget it.

    Requires:
        - rows is a list of row dicts
        - frozen_of / unfrozen_of map a row to a number
        - fmt is "pct" or "abs"

    Ensures:
        - a band with fewer than MIN_CLEAN_N rows is marked "← thin"
        - the ALL line is marked the same way on the same rule
        - returns the whole-sample ( frozen_mean, unfrozen_mean, delta ), or
          None when there are no rows at all

    Raises:
        - nothing
    """
    if not rows:
        print( f"{title}\n  no rows" )
        return None

    def cell( v ): return f"{v:>10.1%}" if fmt == "pct" else f"{v:>10.1f}"
    def dcell( v ): return f"{v:>+9.1%}" if fmt == "pct" else f"{v:>+9.1f}"

    print( title )
    header = f"{'band':<9}{'n':>4}{'frozen':>10}{'unfrozen':>10}{'delta':>9}"
    print( header + ( f"{'target':>8}" if show_target else "" ) )

    for b in BANDS:
        band_rows = [ r for r in rows if r[ "band" ] == b ]
        if not band_rows: continue
        f_mean = statistics.mean( frozen_of( r )   for r in band_rows )
        u_mean = statistics.mean( unfrozen_of( r ) for r in band_rows )
        thin   = "  ← thin" if len( band_rows ) < MIN_CLEAN_N else ""
        target = f"{BAND_TARGET[b]:>8.0%}" if show_target else ""
        print( f"{b:<9}{len(band_rows):>4}{cell(f_mean)}{cell(u_mean)}"
               f"{dcell(u_mean - f_mean)}{target}{thin}" )

    f_all = statistics.mean( frozen_of( r )   for r in rows )
    u_all = statistics.mean( unfrozen_of( r ) for r in rows )
    thin  = "  ← thin" if len( rows ) < MIN_CLEAN_N else ""
    print( f"{'ALL':<9}{len(rows):>4}{cell(f_all)}{cell(u_all)}{dcell(u_all - f_all)}"
           f"{'':>8}{thin}" if show_target else
           f"{'ALL':<9}{len(rows):>4}{cell(f_all)}{cell(u_all)}{dcell(u_all - f_all)}{thin}" )
    print()

    return f_all, u_all, u_all - f_all


def report( results, elapsed, out_path ):
    """
    Print the paired comparison.

    Requires:
        - results is a list of row dicts as built by main()

    Ensures:
        - per-band and whole-sample means are computed on the PAIRED subset only
        - prints, and does not raise, on an empty or all-bypassed sample

    Raises:
        - nothing
    """
    print()
    print( "=" * 78 )
    print( f"wall clock {elapsed/60:.1f} min · rows → {out_path}" )
    print()

    live     = [ r for r in results if not r[ "bypassed" ] ]
    bypassed = len( results ) - len( live )
    paired   = [ r for r in live if "frozen_gain" in r and "unfrozen_gain" in r ]

    print( f"sampled {len(results)}  ·  bypassed {bypassed}  ·  called {len(live)}  ·  "
           f"paired (both arms returned) {len(paired)}" )
    if not paired:
        print( "no paired rows — nothing to compare" )
        return

    dropped = len( live ) - len( paired )
    if dropped:
        fz = sum( 1 for r in live if "frozen_gain"   not in r )
        uz = sum( 1 for r in live if "unfrozen_gain" not in r )
        print( f"  dropped {dropped} unpaired rows (frozen errors {fz}, unfrozen errors {uz})" )
    print()

    # ── The ratio table — handicapped toward frozen, kept because every prior
    #    document and every target is stated in these units.
    f_all, u_all, delta = banded_table(
        "RATIO — mean tokens removed as a fraction of each arm's OWN input",
        paired, lambda r: r[ "frozen_gain" ], lambda r: r[ "unfrozen_gain" ],
        fmt="pct", show_target=True )

    # ── The denominator-free table. Read THIS one when the ratios land close.
    f_abs_all, u_abs_all, _ = banded_table(
        "ABSOLUTE — mean tokens removed per message (no denominator, no handicap)",
        paired, lambda r: r[ "frozen_removed" ], lambda r: r[ "unfrozen_removed" ],
        fmt="abs" )

    # ── INTENTION TO TREAT ────────────────────────────────────────────────────
    # The paired tables above drop a message when EITHER arm failed to return.
    # That keeps the two means over identical messages, but it also deletes the
    # cases an arm choked on — and 4 of the first 5 failures were the unfrozen
    # arm, the one under test. Deleting the messages that beat an arm flatters
    # exactly that arm.
    #
    # So score a failed arm as 0% gain and keep the message. "Did not return"
    # is a way of not compressing, not a missing observation.
    #
    # 🔑 If this table and the paired table disagree, the DISAGREEMENT is the
    # finding — it means the result depends on how failures are counted, and
    # neither number should be quoted alone. (María, 2026-08-11.)
    itt = banded_table(
        "INTENTION TO TREAT — every called message kept, a failed arm scored 0%",
        live, lambda r: r.get( "frozen_gain", 0.0 ), lambda r: r.get( "unfrozen_gain", 0.0 ),
        fmt="pct" )
    if itt and abs( itt[ 2 ] - delta ) > 0.02:
        print( f"🔴 ITT DISAGREES with the paired delta ({itt[2]:+.1%} vs {delta:+.1%}). The "
               f"result depends on how failures are counted — quote both or neither." )
        print()

    # Failures, by arm and by kind. A 110s timeout and a malformed-XML parse
    # failure are different claims about the model and must not be pooled.
    for arm in [ "frozen", "unfrozen" ]:
        errs = {}
        for r in live:
            if r.get( f"{arm}_err" ):
                kind = r[ f"{arm}_err" ].split( ":" )[ 0 ]
                errs[ kind ] = errs.get( kind, 0 ) + 1
        total = sum( errs.values() )
        detail = ", ".join( f"{k} × {v}" for k, v in sorted( errs.items(), key=lambda kv: -kv[1] ) )
        print( f"failures · {arm:<8} {total}/{len(live)}" + ( f"  ({detail})" if detail else "" ) )
    print()

    # A mean can hide a split population — print the paired deltas themselves.
    deltas = sorted( r[ "unfrozen_gain" ] - r[ "frozen_gain" ] for r in paired )
    better = sum( 1 for d in deltas if d >  0.02 )
    worse  = sum( 1 for d in deltas if d < -0.02 )
    print( f"paired ratio delta (unfrozen − frozen):  p10 {deltas[int(len(deltas)*0.10)]:+.1%}  "
           f"p50 {statistics.median(deltas):+.1%}  p90 {deltas[int(len(deltas)*0.90)]:+.1%}" )
    print( f"unfrozen better by >2pts on {better}/{len(paired)} · worse on {worse}/{len(paired)} · "
           f"within ±2pts on {len(paired) - better - worse}" )
    print()

    # ── Observers ─────────────────────────────────────────────────────────────
    # ⚠️ These lines are NOT comparable to each other. See the module docstring:
    # the unfrozen check sees every literal in the raw body, the frozen check
    # only sees what survived substitution.
    valid = [ r for r in paired if "frozen_valid" in r ]
    if valid:
        print( f"observer · frozen arm passing the full validator: "
               f"{sum(1 for r in valid if r['frozen_valid'])}/{len(valid)}" )

    for arm in [ "frozen", "unfrozen" ]:
        rows = [ r for r in paired if f"{arm}_lit_total" in r and r[ f"{arm}_lit_total" ] ]
        if not rows: continue
        miss  = sum( r[ f"{arm}_lit_missing" ] for r in rows )
        total = sum( r[ f"{arm}_lit_total" ]   for r in rows )
        hurt  = sum( 1 for r in rows if r[ f"{arm}_lit_missing" ] )
        print( f"observer · {arm:<8} literals lost {miss}/{total} ({miss/total:.1%}) "
               f"across {hurt}/{len(rows)} messages" )
    print()

    # ── The number a JUMP has to survive ──────────────────────────────────────
    # Deleting a literal removes tokens, so damage and compression are the same
    # quantity and the headline cannot separate them. Re-run the comparison over
    # messages where NEITHER arm lost a verify-tier literal.
    clean = [ r for r in paired
              if r.get( "frozen_lit_missing", 0 ) == 0 and r.get( "unfrozen_lit_missing", 0 ) == 0 ]
    clean_delta = None
    if len( clean ) >= MIN_CLEAN_N:
        result = banded_table(
            f"UNDAMAGED SUBSET — neither arm lost a literal "
            f"({len(clean)}/{len(paired)} messages)",
            clean, lambda r: r[ "frozen_gain" ], lambda r: r[ "unfrozen_gain" ], fmt="pct" )
        clean_delta = result[ 2 ]
        ca = statistics.mean( r[ "unfrozen_removed" ] - r[ "frozen_removed" ] for r in clean )
        print( f"  absolute: {ca:+.1f} tokens/message" )
        print()
    else:
        # Deliberately does NOT compute the delta. Printing it "just for
        # information" is how an n=6 number ends up quoted in a document.
        print( f"UNDAMAGED SUBSET — neither arm lost a literal "
               f"({len(clean)}/{len(paired)} messages)" )
        print( f"  UNCONFIRMED — under the pre-registered floor of {MIN_CLEAN_N}. "
               f"No delta is quoted from {len(clean)} messages." )
        print( f"  The headline delta cannot be separated from literal damage on this run." )
        print()

    # Same idea for the frozen arm's own gate: a rewrite that fails the
    # validator is one this pipeline would never have shipped.
    shipped = [ r for r in paired if r.get( "frozen_valid" ) ]
    print( f"VALIDATOR-PASSING SUBSET — frozen rewrites that would actually have shipped "
           f"({len(shipped)}/{len(paired)})" )
    if len( shipped ) >= MIN_CLEAN_N:
        sf = statistics.mean( r[ "frozen_gain" ]   for r in shipped )
        su = statistics.mean( r[ "unfrozen_gain" ] for r in shipped )
        print( f"  frozen {sf:.1%} · unfrozen {su:.1%} · delta {su - sf:+.1%}" )
    else:
        # Same floor as the undamaged subset, and for the same reason. A rule
        # that guards one thin subset and not the one beside it is not a rule.
        print( f"  UNCONFIRMED — under the pre-registered floor of {MIN_CLEAN_N}." )
    print()

    lat = sorted( r[ "frozen_lat" ] + r[ "unfrozen_lat" ] for r in live )
    print( f"latency for the PAIR: p50 {statistics.median(lat):.1f}s  max {lat[-1]:.1f}s" )
    print()
    print( f"VERDICT against the pre-registered {FLAT_THRESHOLD:.0%} line — the question is "
           f"the delta, not either column:" )
    if delta >= FLAT_THRESHOLD:
        print( f"  → JUMP ({delta:+.1%}). The placeholders were the ceiling. What needs "
               f"rethinking is the safety mechanism, not the model." )
        if clean_delta is None:
            print( f"  🔴 UNCONFIRMED — fewer than {MIN_CLEAN_N} undamaged rows. This jump "
                   f"cannot be told apart from the unfrozen arm deleting literals." )
        elif clean_delta < FLAT_THRESHOLD:
            print( f"  🔴 DOES NOT SURVIVE the undamaged subset ({clean_delta:+.1%}). The jump "
                   f"is coming from damage, not from compression." )
        else:
            print( f"  ✓ survives the undamaged subset ({clean_delta:+.1%})." )
    else:
        print( f"  → FLAT ({delta:+.1%}). The ceiling is the material UNDER THESE "
               f"PRESERVATION REQUIREMENTS." )
        # ⚠️ The qualifier is load-bearing, not hedging. Requirement 31 of the
        # prompt — keep every number, percentage, port and section reference
        # exactly as written — is given to BOTH arms. The unfrozen arm is not an
        # unconstrained rewriter; it is the same rewriter preserving the same
        # literals in prose instead of in brackets. Dropping the qualifier
        # claims a result about the MATERIAL that only a third arm, with the
        # placeholder paragraphs stripped, could support.
        print( f"     NOT the unqualified claim: the prompt constrains both arms to preserve "
               f"every number, port and reference (Requirement 31)." )
        print( f"     Separating mechanism from instructions needs a third arm with the "
               f"placeholder paragraphs stripped. Not run here." )
    print( f"  ⚠️ ratios are handicapped toward frozen; if the two are close, "
           f"read the ABSOLUTE table ({u_abs_all - f_abs_all:+.1f} tokens/message)." )


def replay( path ):
    """
    Re-print the report from a committed JSONL, with no model calls.

    The rows ARE the experiment; the report is a view of them. Keeping the two
    separable means the analysis can be corrected after the fact without
    spending 400 model calls again — and it gives a second reader a path to the
    same tables that does not involve trusting the process that produced them.

    Requires:
        - path names a JSONL written by main()

    Ensures:
        - prints the same report main() prints, from rows alone
        - reports elapsed time as 0.0, since no run happened

    Raises:
        - nothing beyond the file not existing
    """
    rows = [ json.loads( line ) for line in open( path ) if line.strip() ]
    report( rows, 0.0, path )


if __name__ == "__main__":
    # `--report-only <path>` re-derives the tables from rows already on disk.
    if "--report-only" in sys.argv:
        replay( sys.argv[ sys.argv.index( "--report-only" ) + 1 ] )
    else:
        main()
