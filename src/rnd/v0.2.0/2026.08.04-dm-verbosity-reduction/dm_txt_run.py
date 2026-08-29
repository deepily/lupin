"""
The dm.txt experiment, now running through the real `DmTutorAgent`.

    export LUPIN_ROOT=/mnt/DATA01/include/www.deepily.ai/projects/lupin
    cd $LUPIN_ROOT
    python src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/dm_txt_run.py

    --n-per-band N   how many messages per band (default 1 — the original run)
    --both           run every message through BOTH sentinel arms and compare
    --no-pause       do not wait for ENTER between messages

WHAT CHANGED ON 2026-08-11 NIGHT, AND WHY IT MATTERS TO THE NUMBERS.

This harness used to call the LLM client directly and pull the slots out with
`re.search`. It now constructs `DmTutorAgent` and takes what the agent delivers.
That is not a refactor — it moves the run onto a materially different footing,
in TWO ways, and both were discovered by running it rather than by reading it:

1. **The stop sentinel.** The earlier run had none: `dm.txt` never asked for
   `</stop>` and this file substituted its XML example bare. `AgentBase` appends
   the sentinel by construction (`prompt_template_processor.py:130`). Measured
   separately at 3,004 words / 56.2s → 114 / 3.2s on a 250+ message.

2. **Strict XML instead of regex.** `re.search` shrugs at a literal `<file>`
   sitting in the model's prose; `xmltodict` does not — it reads it as an
   unclosed tag and the whole response fails. The first live call through the
   agent died exactly this way, on a `thoughts` block containing
   `git show HEAD:<file>`. The fix follows the sibling arm's established
   practice (`dm-compression.txt:34`): the prompt now instructs CDATA, so the
   payload is copied literally and nothing inside it needs escaping.

So the earlier "4 of 4 clean" and any number this file prints now are NOT
measurements of the same thing. `--both` exists so the sentinel half of that
difference can be priced instead of assumed.

No gate, no ask detector, no P.S., no attachments, no freeze protocol. The
prompt is the design; the agent is the delivery path the fleet will actually
call.
"""

import json
import pathlib
import sys
import time

sys.path.insert( 0, "src" )

from cosa.agents.dm_tutor.agent import DmTutorAgent

SNAPSHOT = "src/tmp/arm4/dm_traffic_snapshot_2026.08.07.jsonl"
OUT_PATH = pathlib.Path( f"/tmp/dm-txt-{time.strftime('%Y.%m.%d-%H%M')}.md" )


def _arg( flag, default ):
    """
    Read `--flag value` from argv.

    Requires:
        - flag is the full flag string including its leading dashes

    Ensures:
        - returns the following argv entry when the flag is present
        - returns default otherwise

    Raises:
        - nothing
    """
    return sys.argv[ sys.argv.index( flag ) + 1 ] if flag in sys.argv else default


N_PER_BAND = int( _arg( "--n-per-band", 1 ) )
BOTH_ARMS  = "--both" in sys.argv

# Pause between messages so each can be read before the next one runs. Off with
# --no-pause, off automatically when stdout is not a terminal — a script that
# blocks on input it can never receive is a hang, not a pause — and off
# automatically for a multi-message run, where 200 ENTER presses is not a review.
PAUSE = ( "--no-pause" not in sys.argv and sys.stdin.isatty() and N_PER_BAND == 1 )

# Smallest to largest — Rick's ask.
BANDS = [ "<80", "80-150", "150-250", "250+" ]

# Two bands carry an injected path, two do not, so one run shows both the slot
# filled and the slot correctly left empty. The corpus predates the workflow rule
# that tells agents to send a path instead of pasting a stack trace, so these are
# INJECTED, and every injected message is labelled as such in the output.
#
# ⚠️ With --n-per-band > 1 the injection applies to the FIRST message of each of
# those bands ONLY. Injecting into all 50 would turn a demonstration into a
# contaminated sample, and the un-injected majority is what tells us how often
# the model finds a path the message really had.
BANDS_WITH_PATH = [ "<80", "250+" ]

INJECTED_PATH = {
    "<80"  : "src/cosa/agents/dm_tutor/tutor.py:412",
    "250+" : "http://localhost:7999/app/docs?path=lupin/src/rnd/"
             "v0.2.0/2026.08.04-dm-verbosity-reduction/live-runs/unfrozen-control-50per-band.jsonl",
}

# How each one is worded into the message, the way an agent would actually write
# it. Held BARE of the "Stack trace:" lead-in when checked, because the lead-in is
# sentence scaffolding the model is right to drop — comparing against the
# labelled line scored a correct extraction as "altered" on the first run.
INJECTED_LINE = {
    "<80"  : "\n\nStack trace: " + INJECTED_PATH[ "<80" ],
    "250+" : "\n\nFull run: "    + INJECTED_PATH[ "250+" ],
}


def band_of( words ):
    """
    The same four bands every arm-4 run has used.

    Requires:
        - words is a non-negative integer

    Ensures:
        - returns one of "<80", "80-150", "150-250", "250+"

    Raises:
        - nothing
    """
    if words <  80: return "<80"
    if words < 150: return "80-150"
    if words < 250: return "150-250"
    return "250+"


def words( text ):
    """
    Whitespace word count.

    Requires:
        - text is a string or None

    Ensures:
        - returns 0 for None or empty, else the number of whitespace tokens

    Raises:
        - nothing
    """
    return len( text.split() ) if text else 0


def select( pools ):
    """
    Pick the sample by STRIDE, never by hand.

    A set chosen for good examples measures the chooser, not the tutor. At
    N_PER_BAND=1 this reduces to the middle member of each pool, which is what
    the original run used — neither the shortest nor the longest, picked by
    position and never by content.

    Requires:
        - pools maps band name to a list of message bodies

    Ensures:
        - returns a list of ( band, body, injected ) triples
        - at most N_PER_BAND entries per band, in BANDS order
        - injection happens AFTER selection, so which message is chosen never
          depends on whether it already had a path

    Raises:
        - nothing
    """
    sample = []

    for band in BANDS:
        pool = pools.get( band, [] )
        if not pool: continue

        if N_PER_BAND == 1:
            chosen = [ pool[ len( pool ) // 2 ] ]
        else:
            stride = max( 1, len( pool ) // N_PER_BAND )
            chosen = pool[ ::stride ][ :N_PER_BAND ]

        for index, body in enumerate( chosen ):
            inject = band in BANDS_WITH_PATH and index == 0
            sample.append( ( band, body + INJECTED_LINE[ band ] if inject else body, inject ) )

    return sample


def check_pointer( body, pointer, injected, band ):
    """
    Judge the path slot: real extraction, invention, or correctly empty.

    Two mechanical checks. FIRST, applying to every band: a returned pointer must
    appear VERBATIM in the message — that is the only way to tell a real
    extraction from an invention, and the un-injected bands are not required to
    come back empty, because a real DM may carry its own path. SECOND, for the
    two injected messages, the pointer must be the one that was added.

    Requires:
        - body is the message as sent, pointer is the slot's value ("" if none)

    Ensures:
        - returns ( note, ok ) where ok is False only for a dropped or invented
          pointer — a correctly-empty slot is a pass

    Raises:
        - nothing
    """
    if not pointer:
        return ( "🔴 dropped", False ) if injected else ( "✅ empty", True )

    if pointer not in body:
        return f"🔴 NOT IN DM: {pointer[ :50 ]}", False

    if injected:
        if pointer == INJECTED_PATH[ band ]: return "✅ exact", True
        return f"⚠️ verbatim, but not the injected one: {pointer[ :40 ]}", True

    return f"✅ found its own: {pointer[ :45 ]}", True


def run_one( body, include_stop_sentinel ):
    """
    One message through one arm.

    Requires:
        - body is a non-empty message

    Ensures:
        - returns a dict carrying delivered text, pointer, latency, error
        - never raises — the agent's own contract is fail-closed, and a
          construction failure is caught here so one bad message cannot end a
          200-message run

    Raises:
        - nothing
    """
    started = time.time()

    try:
        agent     = DmTutorAgent( dm_body=body, include_stop_sentinel=include_stop_sentinel )
        delivered = agent.rewrite()
        pointer   = agent.response.pointer if agent.response else ""
        thoughts  = agent.response.thoughts if agent.response else ""
        error     = agent.error
    except Exception as e:
        delivered, pointer, thoughts, error = None, "", "", f"{type( e ).__name__}: {e}"

    return {
        "delivered" : delivered,
        "pointer"   : pointer,
        "thoughts"  : thoughts,
        "error"     : error,
        "latency"   : time.time() - started,
    }


def load_pools():
    """
    Read the corpus and bucket every body by band.

    Requires:
        - SNAPSHOT is a readable JSONL file with a "body" field per row

    Ensures:
        - returns a dict of band name → list of bodies, corpus order preserved

    Raises:
        - FileNotFoundError when the snapshot is missing
    """
    pools = {}

    for line in open( SNAPSHOT ):
        line = line.strip()
        if not line: continue
        try: record = json.loads( line )
        except Exception: continue
        body = record.get( "body" )
        if body: pools.setdefault( band_of( len( body.split() ) ), [] ).append( body )

    return pools


def main():
    arms   = [ True, False ] if BOTH_ARMS else [ True ]
    sample = select( load_pools() )

    print( "=" * 78 )
    print( f"dm.txt through DmTutorAgent · {len( sample )} messages"
           f" · {N_PER_BAND}/band · {'BOTH arms' if BOTH_ARMS else 'sentinel ON'}" )
    print( "=" * 78 + "\n", flush=True )

    out  = [ f"# dm.txt through DmTutorAgent — {time.strftime('%Y-%m-%d %H:%M')}", "",
             f"{len( sample )} messages, {N_PER_BAND} per band."
             f"{' Both sentinel arms.' if BOTH_ARMS else ''}", "" ]
    rows = []

    for index, ( band, body, injected ) in enumerate( sample ):
        if PAUSE and index > 0:
            try:
                input( f"\n[ENTER for the next message — {len( sample ) - index} left, Ctrl-C to stop] " )
            except ( EOFError, KeyboardInterrupt ):
                print( "\nstopped." )
                break

        for sentinel in arms:
            result    = run_one( body, sentinel )
            delivered = result[ "delivered" ]
            note, ok  = check_pointer( body, result[ "pointer" ], injected, band )

            in_w  = words( body )
            del_w = words( delivered )
            arm   = "sentinel" if sentinel else "control "

            rows.append( {
                "band" : band, "arm" : arm, "in" : in_w, "delivered" : del_w,
                "secs" : result[ "latency" ], "ok" : delivered is not None,
                "path_ok" : ok, "note" : note, "error" : result[ "error" ],
            } )

            if N_PER_BAND == 1 or not delivered:
                print( "=" * 78, flush=True )
                print( f"BAND {band} · {arm} · {result['latency']:.1f}s · "
                       f"path {'INJECTED' if injected else 'none'} → {note}", flush=True )
                print( f"WORDS  in {in_w} → delivered {del_w}"
                       + ( f"  ({del_w/in_w:.0%})" if in_w else "" ), flush=True )
                print( "=" * 78, flush=True )

                if N_PER_BAND == 1:
                    print( "\n--- ORIGINAL " + "-" * 64, flush=True )
                    print( body, flush=True )

                print( f"\n--- delivered · {del_w} words " + "-" * 44, flush=True )
                print( delivered if delivered
                       else f"🔴 no output — {result['error']}", flush=True )
                print( flush=True )
            else:
                print( f"  {band:<9} {arm} {in_w:>4}w → {del_w:>4}w  "
                       f"{result['latency']:>5.1f}s  {'✓' if delivered else '🔴'}  {note}",
                       flush=True )

        # Only the first arm's output goes in the document — the second is a
        # control for the summary table, not a second thing to read.
        first = rows[ -len( arms ) ]
        out += [ f"## {band} · {words( body )} words · "
                 f"path {'injected' if injected else 'none'} → {first['note']}", "",
                 "**Original**", "", "```", body, "```", "" ]

    OUT_PATH.write_text( "\n".join( out ) )

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print( "=" * 78 )
    print( "SUMMARY" )
    print( "=" * 78 )
    print( f"{'band':<10}{'arm':<10}{'n':>4}{'ok':>5}{'deliv/in':>10}{'p50 secs':>10}{'path ok':>9}" )

    for band in BANDS:
        for arm in ( "sentinel", "control " ):
            group = [ r for r in rows if r[ "band" ] == band and r[ "arm" ] == arm ]
            if not group: continue

            good  = [ r for r in group if r[ "ok" ] ]
            secs  = sorted( r[ "secs" ] for r in group )
            ratio = ( sum( r[ "delivered" ] for r in good ) / sum( r[ "in" ] for r in good )
                      if good else 0 )

            print( f"{band:<10}{arm:<10}{len( group ):>4}{len( good ):>5}"
                   f"{ratio:>9.0%}{secs[ len( secs ) // 2 ]:>10.1f}"
                   f"{sum( 1 for r in group if r[ 'path_ok' ] ):>9}" )

    total = [ r for r in rows if r[ "ok" ] ]
    print()
    print( f"delivered {len( total )}/{len( rows )} calls"
           f" · {sum( r[ 'secs' ] for r in rows ):.0f}s total model time" )

    failures = [ r for r in rows if not r[ "ok" ] ]
    if failures:
        print()
        print( "FAILURES — kept, because a discarded reason is an unanswerable question:" )
        for r in failures[ :20 ]:
            print( f"  {r['band']:<9} {r['arm']} {r['error']}" )
        if len( failures ) > 20: print( f"  … and {len( failures ) - 20} more" )

    print( f"\nalso written to {OUT_PATH}" )


if __name__ == "__main__":
    main()
