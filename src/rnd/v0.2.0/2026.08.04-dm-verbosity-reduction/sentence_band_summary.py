#!/usr/bin/env python3
"""
Read the re-measured rows and answer Rick's fourth question with data instead of a forecast.

    export LUPIN_ROOT=/mnt/DATA01/include/www.deepily.ai/projects/lupin
    cd $LUPIN_ROOT
    python src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/sentence_band_summary.py

`sentence_band_analysis.py` prices the ">4 sentences" trigger by applying each word
band's MEASURED compression ratio to every message in it. That forecast has one soft
spot, named there and closed here: those ratios were measured across a whole word
band, INCLUDING the short-claim messages the new policy would skip. If the messages
a band keeps compress differently from the ones it drops, the forecast is off.

This file recomputes the same economics from per-message input/output pairs, cut by
SENTENCE band, so the trigger is priced on the set it actually fires on.

It also answers the half of Rick's question no forecast can reach: how many sentences
and words come BACK, per band — and therefore whether the tutor's output actually
lands inside the three-sentence bar the mandate would state.
"""

import json
import pathlib
import statistics
import sys

ROWS = pathlib.Path(
    "src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/live-runs/"
    "sentence-band-outputs-2026.08.12.jsonl" )

SENTENCE_BANDS = [ "1-2", "3-4", "5-8", "9-15", "16+" ]
WORD_BANDS     = [ "<80", "80-150", "150-250", "250+" ]

REWRITE_ABOVE = 4
STATED_LIMIT  = 3


def load():
    """
    Read the per-message rows.

    Requires:
        - ROWS is a readable JSONL file written by sentence_band_outputs.py

    Ensures:
        - returns every row, delivered or not, so the failure rate stays visible

    Raises:
        - SystemExit when the file is missing, because a silent empty table is worse
    """
    if not ROWS.exists():
        sys.exit( f"no rows at {ROWS} — run sentence_band_outputs.py first" )

    return [ json.loads( line ) for line in open( ROWS ) if line.strip() ]


def band_table( rows, key, labels, title ):
    """
    Input vs output, per band, on delivered messages only.

    Requires:
        - rows carry in_words, in_sentences, out_words, out_sentences, ok and `key`
        - labels is the ordered list of band names for `key`

    Ensures:
        - prints one row per band plus a total; failures are counted, not averaged
        - returns the per-band dicts

    Raises:
        - nothing
    """
    print( f"\n{title}" )
    print( "-" * 112 )
    print( f"{'band':<8}{'n':>5}{'ok':>4}{'in sent':>9}{'out sent':>10}"
           f"{'in words':>10}{'out words':>11}{'words kept':>12}"
           f"{'sent kept':>11}{'<=3 out':>9}{'p50 secs':>10}" )
    print( "-" * 112 )

    out = []
    for label in labels:
        group = [ r for r in rows if r[ key ] == label ]
        if not group: continue

        good = [ r for r in group if r[ "ok" ] ]
        if not good: continue

        in_w  = sum( r[ "in_words"      ] for r in good )
        out_w = sum( r[ "out_words"     ] for r in good )
        in_s  = sum( r[ "in_sentences"  ] for r in good )
        out_s = sum( r[ "out_sentences" ] for r in good )
        secs  = sorted( r[ "latency" ] for r in group )

        entry = {
            "band"           : label,
            "n"              : len( group ),
            "ok"             : len( good ),
            "avg_in_sent"    : statistics.mean( r[ "in_sentences"  ] for r in good ),
            "avg_out_sent"   : statistics.mean( r[ "out_sentences" ] for r in good ),
            "avg_in_words"   : statistics.mean( r[ "in_words"      ] for r in good ),
            "avg_out_words"  : statistics.mean( r[ "out_words"     ] for r in good ),
            "words_kept"     : out_w / in_w,
            "sentences_kept" : out_s / in_s,
            "within_limit"   : sum( 1 for r in good if r[ "out_sentences" ] <= STATED_LIMIT ),
            "p50_secs"       : secs[ len( secs ) // 2 ],
        }
        out.append( entry )

        print( f"{label:<8}{entry['n']:>5}{entry['ok']:>4}"
               f"{entry['avg_in_sent']:>9.1f}{entry['avg_out_sent']:>10.1f}"
               f"{entry['avg_in_words']:>10.0f}{entry['avg_out_words']:>11.0f}"
               f"{entry['words_kept']:>11.0%}{entry['sentences_kept']:>11.0%}"
               f"{entry['within_limit']:>6}/{entry['ok']:<3}{entry['p50_secs']:>10.1f}" )

    good = [ r for r in rows if r[ "ok" ] ]
    print( "-" * 112 )
    print( f"{'ALL':<8}{len( rows ):>5}{len( good ):>4}"
           f"{statistics.mean( r['in_sentences']  for r in good ):>9.1f}"
           f"{statistics.mean( r['out_sentences'] for r in good ):>10.1f}"
           f"{statistics.mean( r['in_words']      for r in good ):>10.0f}"
           f"{statistics.mean( r['out_words']     for r in good ):>11.0f}"
           f"{sum( r['out_words'] for r in good ) / sum( r['in_words'] for r in good ):>11.0%}"
           f"{sum( r['out_sentences'] for r in good ) / sum( r['in_sentences'] for r in good ):>11.0%}"
           f"{sum( 1 for r in good if r['out_sentences'] <= STATED_LIMIT ):>6}/{len( good ):<3}" )

    return out


def price_from_measurement( rows ):
    """
    The trigger's economics, computed from measured pairs rather than band averages.

    Requires:
        - rows carry in_words, out_words, in_sentences and ok

    Ensures:
        - prints saved words for the >4 trigger against rewrite-everything
        - a failed rewrite saves NOTHING and is counted that way, because fail-closed
          means the original was sent

    Raises:
        - nothing
    """
    good = [ r for r in rows if r[ "ok" ] ]

    total_in  = sum( r[ "in_words" ] for r in rows )
    triggered = [ r for r in rows if r[ "in_sentences" ] >  REWRITE_ABOVE ]
    skipped   = [ r for r in rows if r[ "in_sentences" ] <= REWRITE_ABOVE ]

    def saved( subset ):
        # Only a DELIVERED rewrite saves anything. A fail-closed message sent its
        # original, so it contributes zero — never a negative, never a phantom win.
        return sum( r[ "in_words" ] - r[ "out_words" ] for r in subset if r[ "ok" ] )

    saved_trigger = saved( triggered )
    saved_all     = saved( rows ) or 1

    print( f"\nTHE '>{REWRITE_ABOVE} SENTENCES' TRIGGER, PRICED ON MEASURED PAIRS" )
    print( "-" * 112 )
    print( f"  messages {len( rows )} · delivered {len( good )}"
           f" ({100.0 * len( good ) / len( rows ):.1f}%)" )
    print( f"  rewritten (>{REWRITE_ABOVE} claims) {len( triggered ):>4}"
           f"  ({100.0 * len( triggered ) / len( rows ):.1f}%)"
           f"   skipped {len( skipped ):>4} ({100.0 * len( skipped ) / len( rows ):.1f}%)" )
    print()
    print( f"  total input words        {total_in:>8,}" )
    print( f"  saved, trigger at >{REWRITE_ABOVE}     {saved_trigger:>8,}"
           f"  = {100.0 * saved_trigger / total_in:.1f}% of all DM words" )
    print( f"  saved, rewrite EVERY DM  {saved_all:>8,}"
           f"  = {100.0 * saved_all / total_in:.1f}% of all DM words" )
    print( f"  => the trigger keeps {100.0 * saved_trigger / saved_all:.1f}% of the"
           f" achievable saving" )
    print()
    print( f"  forgone by skipping      {saved_all - saved_trigger:>8,} words"
           f"  across {len( skipped )} messages"
           f"  ({( saved_all - saved_trigger ) / max( 1, len( skipped ) ):.0f} words each)" )
    print( f"  model time avoided       {sum( r['latency'] for r in skipped ):>8.0f}s"
           f"  ({100.0 * len( skipped ) / len( rows ):.0f}% of calls)" )

    return {
        "messages" : len( rows ), "delivered" : len( good ),
        "triggered" : len( triggered ), "skipped" : len( skipped ),
        "total_in_words" : total_in,
        "saved_trigger" : saved_trigger, "saved_all" : saved_all,
        "pct_saved_trigger" : 100.0 * saved_trigger / total_in,
        "pct_saved_all"     : 100.0 * saved_all / total_in,
    }


def does_the_output_obey_the_bar( rows ):
    """
    The question the mandate rests on: does a rewrite actually land at or under three?

    Requires:
        - rows carry out_sentences and ok

    Ensures:
        - prints the distribution of delivered sentence counts against STATED_LIMIT

    Raises:
        - nothing
    """
    good = [ r for r in rows if r[ "ok" ] ]
    if not good: return

    counts = sorted( r[ "out_sentences" ] for r in good )
    within = sum( 1 for c in counts if c <= STATED_LIMIT )

    print( f"\nDOES THE REWRITE LAND INSIDE THE {STATED_LIMIT}-SENTENCE BAR?" )
    print( "-" * 112 )
    print( f"  delivered rewrites            {len( good )}" )
    print( f"  at or under {STATED_LIMIT} claims          {within}"
           f"  ({100.0 * within / len( good ):.1f}%)" )
    print( f"  median delivered claims       {statistics.median( counts ):.0f}" )
    print( f"  p90 / max delivered claims    {counts[ int( 0.9 * ( len( counts ) - 1 ) ) ]}"
           f" / {counts[ -1 ]}" )
    print()

    histogram = {}
    for c in counts: histogram[ c ] = histogram.get( c, 0 ) + 1
    for claims in sorted( histogram ):
        bar = "#" * max( 1, int( 60 * histogram[ claims ] / len( counts ) ) )
        flag = "" if claims <= STATED_LIMIT else "  ← over the bar"
        print( f"  {claims:>3} claims {histogram[ claims ]:>4}  {bar}{flag}" )


def main():
    rows = load()

    print( "=" * 112 )
    print( f"TUTOR OUTPUT, RE-MEASURED — {len( rows )} messages, sentinel arm" )
    print(  "counter: cosa.agents.dm_tutor.sentences.count_sentences (claim rule)" )
    print( "=" * 112 )

    band_table( rows, "sentence_band", SENTENCE_BANDS,
                "BY SENTENCE BAND — the cut Rick asked for" )
    band_table( rows, "word_band", WORD_BANDS,
                "BY WORD BAND — the old cut, for comparison against last night" )

    price_from_measurement( rows )
    does_the_output_obey_the_bar( rows )


if __name__ == "__main__":
    main()
