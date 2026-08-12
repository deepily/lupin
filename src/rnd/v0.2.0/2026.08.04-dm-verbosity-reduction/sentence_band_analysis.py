#!/usr/bin/env python3
"""
Re-cut the DM corpus by SENTENCES instead of words, and price the ">4 sentences" trigger.

    export LUPIN_ROOT=/mnt/DATA01/include/www.deepily.ai/projects/lupin
    cd $LUPIN_ROOT
    python src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/sentence_band_analysis.py

Rick's ask, 2026-08-12: the pilot stratified by WORD count, but the mandate he wants
to state is a SENTENCE limit — three sentences stated, rewrite only what exceeds four.
So four questions, in his order:

    1. the 200 sampled DMs, summarised by sentence count, clustered into 4-5 bands
    2. anticipated savings if only DMs over 4 sentences are rewritten
    3. what "4 sentences" translates to in words
    4. average sentences and words per band, input AND output

This file answers 1-3 and the INPUT half of 4 with no model in the loop. The OUTPUT
half needs delivered text, which last night's run wrote to /tmp and the nightly sweep
removed — `sentence_band_outputs.py` regenerates it and persists inside the repo.

WHICH COUNTER — the question María raised before this ran, and she was right to.
Lupin has TWO sentence counters and they do not agree:

    dm.py:_count_sentences              splits on . ! ? — counts table rows,
                                        headings and bullets as sentences.
                                        THIS is what the corpus rows have stored.
    dm_tutor/sentences.count_sentences  counts only units that carry a CLAIM;
                                        structure contributes nothing.
                                        THIS is what the tutor's trigger calls.

Every band here is cut on the TUTOR counter, because a policy must be priced with the
counter that will actually fire on it. The naive count is carried alongside so the
divergence is a measured number rather than a caveat — and it should be widest in the
250+ band, where 42% of DMs carry a list or a table.

TWO POPULATIONS, AND THEY DISAGREE ON PURPOSE:

    the 200-message SAMPLE   50 per word-band — what was actually run last night
    the 2,951-body CORPUS    real traffic — what the policy would actually meet

The sample is stratified, so it over-represents long DMs by construction. Savings
computed on it answer "what did we see", not "what will we save". Both are printed;
the corpus number is the one that forecasts.
"""

import json
import pathlib
import re
import statistics
import sys

sys.path.insert( 0, "src" )

from cosa.agents.dm_tutor.sentences import count_sentences

SNAPSHOT = "src/tmp/arm4/dm_traffic_snapshot_2026.08.07.jsonl"
OUT_DIR  = pathlib.Path( "src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/live-runs" )
OUT_JSON = OUT_DIR / "sentence-bands-2026.08.12.json"

# The naive counter, copied verbatim from dm.py:249 rather than imported, because
# importing that router drags the whole FastAPI app in for one regex.
_NAIVE_SPLIT = re.compile( r"[.!?]+(?:\s+|$)" )

# The word bands every arm-4 run has used. Kept so the new cut can be laid over the
# old one rather than replacing it silently.
WORD_BANDS = [ "<80", "80-150", "150-250", "250+" ]

# The sentence bands. Chosen so the policy boundary Rick named — "over 4" — falls ON
# a band edge and not inside one, otherwise no band can be quoted as "the rewritten
# set" and every number needs a footnote.
SENTENCE_BANDS = [
    ( "1-2",   1,  2 ),
    ( "3-4",   3,  4 ),
    ( "5-8",   5,  8 ),
    ( "9-15",  9, 15 ),
    ( "16+",  16, 10 ** 9 ),
]

# Measured last night, 200 messages x 2 arms, sentinel arm. The delivered/in word
# ratio per WORD band. Used here only to forecast; the re-run replaces it with
# per-message data cut by SENTENCE band.
MEASURED_RATIO = { "<80" : 0.76, "80-150" : 0.41, "150-250" : 0.30, "250+" : 0.17 }

REWRITE_ABOVE = 4        # Rick's trigger: rewrite only DMs of MORE than 4 sentences
STATED_LIMIT  = 3        # the mandate the tutor writes toward


def naive_sentences( text ):
    """
    The stored corpus count — structure included, claims not distinguished.

    Requires:
        - text is a string

    Ensures:
        - returns the number of non-empty chunks after splitting on . ! ?

    Raises:
        - nothing
    """
    return len( [ c for c in _NAIVE_SPLIT.split( text ) if c.strip() ] )


def word_band_of( words ):
    """
    The arm-4 word band for a message.

    Requires:
        - words is a non-negative integer

    Ensures:
        - returns one of WORD_BANDS

    Raises:
        - nothing
    """
    if words <  80: return "<80"
    if words < 150: return "80-150"
    if words < 250: return "150-250"
    return "250+"


def sentence_band_of( sentences ):
    """
    The sentence band for a message.

    Requires:
        - sentences is a non-negative integer

    Ensures:
        - returns the label of the first band whose range contains `sentences`
        - returns "0" for a body that carries no claim at all

    Raises:
        - nothing
    """
    for label, low, high in SENTENCE_BANDS:
        if low <= sentences <= high: return label
    return "0"


def load_corpus():
    """
    Every corpus body, measured by BOTH counters.

    Requires:
        - SNAPSHOT is a readable JSONL file whose rows carry a "body"

    Ensures:
        - returns a list of dicts with body, words, both sentence counts, both bands
        - corpus order preserved, because the sample selection strides over it

    Raises:
        - FileNotFoundError when the snapshot is missing
    """
    rows = []

    for line in open( SNAPSHOT ):
        line = line.strip()
        if not line: continue
        try: record = json.loads( line )
        except Exception: continue

        body = record.get( "body" )
        if not body: continue

        words     = len( body.split() )
        sentences = count_sentences( body )

        rows.append( {
            "body"          : body,
            "words"         : words,
            "sentences"     : sentences,
            "naive"         : naive_sentences( body ),
            "word_band"     : word_band_of( words ),
            "sentence_band" : sentence_band_of( sentences ),
        } )

    return rows


def reconstruct_sample( rows, n_per_band=50 ):
    """
    Rebuild the exact 200 messages last night's run selected.

    This mirrors `dm_txt_run.select()` — stride sampling over the corpus-ordered
    pool of each word band — so the set is the same set, not a fresh draw. The
    injected paths are NOT re-applied: they add one line to two messages and would
    perturb a sentence count for no analytical gain.

    Requires:
        - rows is the corpus in file order
        - n_per_band is a positive integer

    Ensures:
        - returns at most n_per_band rows per word band, in WORD_BANDS order

    Raises:
        - nothing
    """
    pools  = {}
    for row in rows: pools.setdefault( row[ "word_band" ], [] ).append( row )

    sample = []
    for band in WORD_BANDS:
        pool = pools.get( band, [] )
        if not pool: continue
        stride = max( 1, len( pool ) // n_per_band )
        sample += pool[ ::stride ][ :n_per_band ]

    return sample


def describe( values ):
    """
    The five numbers worth quoting about a list.

    Requires:
        - values is a list of numbers

    Ensures:
        - returns a dict with n, mean, median, p10, p90; zeros for an empty list

    Raises:
        - nothing
    """
    if not values: return { "n" : 0, "mean" : 0.0, "median" : 0.0, "p10" : 0, "p90" : 0 }

    ordered = sorted( values )
    return {
        "n"      : len( values ),
        "mean"   : statistics.mean( values ),
        "median" : statistics.median( values ),
        "p10"    : ordered[ int( 0.10 * ( len( ordered ) - 1 ) ) ],
        "p90"    : ordered[ int( 0.90 * ( len( ordered ) - 1 ) ) ],
    }


def sentence_band_table( rows, title ):
    """
    Print the sentence-band summary and return it as data.

    Requires:
        - rows carry words, sentences, naive and sentence_band

    Ensures:
        - prints one line per band plus a total line
        - returns a list of per-band dicts

    Raises:
        - nothing
    """
    print( f"\n{title}" )
    print( "-" * 104 )
    print( f"{'band':<8}{'n':>6}{'% msgs':>9}{'% words':>9}"
           f"{'avg sent':>10}{'avg words':>11}{'words/sent':>12}{'med words':>11}"
           f"{'naive avg':>11}{'infl':>7}" )
    print( "-" * 104 )

    total_words = sum( r[ "words" ] for r in rows ) or 1
    out         = []

    for label, _, _ in SENTENCE_BANDS:
        group = [ r for r in rows if r[ "sentence_band" ] == label ]
        if not group: continue

        words      = [ r[ "words"     ] for r in group ]
        sentences  = [ r[ "sentences" ] for r in group ]
        naive      = [ r[ "naive"     ] for r in group ]
        band_words = sum( words )

        entry = {
            "band"          : label,
            "n"             : len( group ),
            "pct_messages"  : 100.0 * len( group ) / len( rows ),
            "pct_words"     : 100.0 * band_words / total_words,
            "avg_sentences" : statistics.mean( sentences ),
            "avg_naive"     : statistics.mean( naive ),
            "avg_words"     : statistics.mean( words ),
            "median_words"  : statistics.median( words ),
            "words_per_sentence" : band_words / sum( sentences ),
            "total_words"   : band_words,
        }
        entry[ "naive_inflation" ] = entry[ "avg_naive" ] / entry[ "avg_sentences" ]
        out.append( entry )

        print( f"{label:<8}{entry['n']:>6}{entry['pct_messages']:>8.1f}%"
               f"{entry['pct_words']:>8.1f}%{entry['avg_sentences']:>10.1f}"
               f"{entry['avg_words']:>11.0f}{entry['words_per_sentence']:>12.1f}"
               f"{entry['median_words']:>11.0f}{entry['avg_naive']:>11.1f}"
               f"{entry['naive_inflation']:>6.2f}x" )

    print( "-" * 104 )
    all_sentences = [ r[ "sentences" ] for r in rows ]
    all_naive     = [ r[ "naive"     ] for r in rows ]
    all_words     = [ r[ "words"     ] for r in rows ]
    print( f"{'ALL':<8}{len( rows ):>6}{100.0:>8.1f}%{100.0:>8.1f}%"
           f"{statistics.mean( all_sentences ):>10.1f}{statistics.mean( all_words ):>11.0f}"
           f"{sum( all_words ) / sum( all_sentences ):>12.1f}"
           f"{statistics.median( all_words ):>11.0f}{statistics.mean( all_naive ):>11.1f}"
           f"{statistics.mean( all_naive ) / statistics.mean( all_sentences ):>6.2f}x" )

    return out


def counter_divergence( rows ):
    """
    How far apart the two counters land, and where the trigger population differs.

    María's point, made measurable: if the stored naive count were used to trigger,
    the ">4" population would be a different set of messages, not merely a bigger
    number. What matters to the policy is how many messages FLIP.

    Requires:
        - rows carry words, sentences, naive and word_band

    Ensures:
        - prints per-word-band inflation and the flip count at the trigger boundary
        - returns a dict of the numbers

    Raises:
        - nothing
    """
    print( "\nTHE TWO COUNTERS — where they diverge (María's flag)" )
    print( "-" * 104 )
    print( f"{'word band':<12}{'n':>6}{'tutor avg':>12}{'naive avg':>12}"
           f"{'inflation':>12}{'naive says >4':>15}{'tutor says >4':>15}{'flips':>8}" )
    print( "-" * 104 )

    per_band = []
    for band in WORD_BANDS:
        group = [ r for r in rows if r[ "word_band" ] == band ]
        if not group: continue

        tutor = statistics.mean( r[ "sentences" ] for r in group )
        naive = statistics.mean( r[ "naive"     ] for r in group )
        n_hi  = sum( 1 for r in group if r[ "naive"     ] > REWRITE_ABOVE )
        t_hi  = sum( 1 for r in group if r[ "sentences" ] > REWRITE_ABOVE )
        flips = sum( 1 for r in group
                     if ( r[ "naive" ] > REWRITE_ABOVE ) != ( r[ "sentences" ] > REWRITE_ABOVE ) )

        per_band.append( { "word_band" : band, "n" : len( group ), "tutor_avg" : tutor,
                           "naive_avg" : naive, "inflation" : naive / tutor,
                           "naive_over" : n_hi, "tutor_over" : t_hi, "flips" : flips } )

        print( f"{band:<12}{len( group ):>6}{tutor:>12.1f}{naive:>12.1f}"
               f"{naive / tutor:>11.2f}x{n_hi:>15}{t_hi:>15}{flips:>8}" )

    total_flips = sum( b[ "flips" ] for b in per_band )
    print( "-" * 104 )
    print( f"  {total_flips} of {len( rows )} messages ({100.0 * total_flips / len( rows ):.1f}%)"
           f" land on OPPOSITE sides of the >{REWRITE_ABOVE} line depending on the counter." )
    print( f"  That is a different SET of messages, not a bigger number —"
           f" which is why the trigger must name its counter." )

    return { "per_band" : per_band, "total_flips" : total_flips }


def crosstab( rows ):
    """
    Lay the sentence cut over the word cut, so the two stratifications can be compared.

    Requires:
        - rows carry word_band and sentence_band

    Ensures:
        - prints a word-band x sentence-band count matrix

    Raises:
        - nothing
    """
    labels = [ label for label, _, _ in SENTENCE_BANDS ]

    print( "\nWORD BAND x SENTENCE BAND — message counts (tutor counter)" )
    print( "-" * 104 )
    print( f"{'word band':<12}" + "".join( f"{l:>8}" for l in labels )
           + f"{'n':>8}{'avg sent':>11}{'med sent':>10}" )
    print( "-" * 104 )

    for band in WORD_BANDS:
        group = [ r for r in rows if r[ "word_band" ] == band ]
        if not group: continue

        counts    = [ sum( 1 for r in group if r[ "sentence_band" ] == l ) for l in labels ]
        sentences = [ r[ "sentences" ] for r in group ]

        print( f"{band:<12}" + "".join( f"{c:>8}" for c in counts )
               + f"{len( group ):>8}{statistics.mean( sentences ):>11.1f}"
               + f"{statistics.median( sentences ):>10.0f}" )


def four_sentences_in_words( rows ):
    """
    Answer "what does 4 sentences translate to in words".

    Two readings, and they are not the same number:
      - the WIDTH reading: 4 x the corpus words-per-sentence
      - the MEMBERSHIP reading: the observed word range of messages that really do
        carry exactly 4 sentences, which is what a word-count proxy would have to
        separate if anyone tried to keep triggering on words

    Requires:
        - rows carry words and sentences

    Ensures:
        - prints both readings and the overlap that defeats a word-count proxy
        - returns a dict of the numbers

    Raises:
        - nothing
    """
    per_sentence = sum( r[ "words" ] for r in rows ) / sum( r[ "sentences" ] for r in rows )

    exactly_four = [ r[ "words" ] for r in rows if r[ "sentences" ] == 4 ]
    at_most_four = [ r[ "words" ] for r in rows if r[ "sentences" ] <= 4 ]
    over_four    = [ r[ "words" ] for r in rows if r[ "sentences" ] >  4 ]

    four  = describe( exactly_four )
    under = describe( at_most_four )
    over  = describe( over_four )

    print( "\nWHAT DOES '4 SENTENCES' MEAN IN WORDS?" )
    print( "-" * 104 )
    print( f"  corpus words per sentence           {per_sentence:.1f}" )
    print( f"  => 4 sentences, width reading       {4 * per_sentence:.0f} words" )
    print( f"  => 3 sentences (the stated limit)   {3 * per_sentence:.0f} words" )
    print()
    print( f"  messages carrying EXACTLY 4 claims  n={four['n']:<5} "
           f"median {four['median']:.0f}w · p10 {four['p10']}w · p90 {four['p90']}w" )
    print( f"  messages at or under 4 (no rewrite) n={under['n']:<5} "
           f"median {under['median']:.0f}w · p90 {under['p90']}w" )
    print( f"  messages over 4 (rewritten)         n={over['n']:<5} "
           f"median {over['median']:.0f}w · p10 {over['p10']}w" )
    print()

    # The overlap is the finding: if the two populations share a word range, no word
    # threshold can stand in for the sentence trigger.
    if under[ "n" ] and over[ "n" ]:
        misfired = sum( 1 for r in rows
                        if r[ "sentences" ] <= 4 and r[ "words" ] > over[ "p10" ] )
        missed   = sum( 1 for r in rows
                        if r[ "sentences" ] >  4 and r[ "words" ] < under[ "p90" ] )
        print(  "  OVERLAP — a word threshold cannot stand in for the sentence one:" )
        print( f"    under-4 messages LONGER than the p10 of the over-4 set   {misfired}" )
        print( f"    over-4  messages SHORTER than the p90 of the under-4 set {missed}" )

    return {
        "words_per_sentence" : per_sentence,
        "four_sentence_width_words"  : 4 * per_sentence,
        "three_sentence_width_words" : 3 * per_sentence,
        "exactly_four" : four, "at_most_four" : under, "over_four" : over,
    }


def price_the_trigger( rows, label ):
    """
    Anticipated savings when ONLY messages over `REWRITE_ABOVE` sentences are rewritten.

    The ratio applied to each message is the one MEASURED for its word band last
    night, because that is the only compression evidence that exists. Its weakness
    is named rather than hidden: those ratios were measured across a whole word
    band, including the short-claim messages this policy would now skip, so a band's
    rewritten subset may not compress at the band's average. The re-run replaces
    this forecast with per-message data.

    Requires:
        - rows carry words, sentences and word_band

    Ensures:
        - prints the coverage and savings for the >4 trigger and for rewrite-everything
        - returns a dict of both

    Raises:
        - nothing
    """
    total_words = sum( r[ "words" ] for r in rows )

    def saved( subset ):
        return sum( r[ "words" ] * ( 1 - MEASURED_RATIO[ r[ "word_band" ] ] ) for r in subset )

    triggered = [ r for r in rows if r[ "sentences" ] > REWRITE_ABOVE ]
    skipped   = [ r for r in rows if r[ "sentences" ] <= REWRITE_ABOVE ]

    saved_trigger = saved( triggered )
    saved_all     = saved( rows ) or 1

    print( f"\nPRICING THE '>{REWRITE_ABOVE} SENTENCES' TRIGGER — {label}" )
    print( "-" * 104 )
    print( f"  messages                {len( rows ):>7}" )
    print( f"  rewritten (>{REWRITE_ABOVE} claims)  {len( triggered ):>7}"
           f"  ({100.0 * len( triggered ) / len( rows ):.1f}% of messages)" )
    print( f"  skipped   (<={REWRITE_ABOVE} claims) {len( skipped ):>7}"
           f"  ({100.0 * len( skipped ) / len( rows ):.1f}% of messages)" )
    print()
    print( f"  total words             {total_words:>7,}" )
    print( f"  words in rewritten set  {sum( r['words'] for r in triggered ):>7,}"
           f"  ({100.0 * sum( r['words'] for r in triggered ) / total_words:.1f}% of all words)" )
    print()
    print( f"  saved, trigger at >{REWRITE_ABOVE}    {saved_trigger:>7,.0f} words"
           f"  = {100.0 * saved_trigger / total_words:.1f}% of all DM words" )
    print( f"  saved, rewrite EVERY DM {saved_all:>7,.0f} words"
           f"  = {100.0 * saved_all / total_words:.1f}% of all DM words" )
    print( f"  => the trigger keeps {100.0 * saved_trigger / saved_all:.1f}% of the"
           f" achievable saving while touching {100.0 * len( triggered ) / len( rows ):.1f}%"
           f" of messages" )

    # Model time is the cost side, and it is per CALL, not per word.
    print()
    print( f"  model calls avoided     {len( skipped ):>7}"
           f"  (~{3.4 * len( skipped ) / 60:.0f} min at the measured 3.4s median)" )

    return {
        "population"        : label,
        "messages"          : len( rows ),
        "triggered"         : len( triggered ),
        "skipped"           : len( skipped ),
        "total_words"       : total_words,
        "triggered_words"   : sum( r[ "words" ] for r in triggered ),
        "saved_trigger"     : saved_trigger,
        "saved_all"         : saved_all,
        "pct_saved_trigger" : 100.0 * saved_trigger / total_words,
        "pct_saved_all"     : 100.0 * saved_all / total_words,
    }


def per_band_trigger_share( rows ):
    """
    How much of each sentence band the trigger actually touches.

    Requires:
        - rows carry sentences, words and sentence_band

    Ensures:
        - prints the rewritten share and forecast saving per sentence band

    Raises:
        - nothing
    """
    print( "\nWHERE THE SAVING COMES FROM, BY SENTENCE BAND" )
    print( "-" * 104 )
    print( f"{'band':<8}{'n':>6}{'rewritten':>11}{'words':>10}"
           f"{'fcst saved':>12}{'% of total saving':>20}" )
    print( "-" * 104 )

    triggered_total = sum( r[ "words" ] * ( 1 - MEASURED_RATIO[ r[ "word_band" ] ] )
                           for r in rows if r[ "sentences" ] > REWRITE_ABOVE ) or 1

    for label, _, _ in SENTENCE_BANDS:
        group = [ r for r in rows if r[ "sentence_band" ] == label ]
        if not group: continue

        hit   = [ r for r in group if r[ "sentences" ] > REWRITE_ABOVE ]
        saved = sum( r[ "words" ] * ( 1 - MEASURED_RATIO[ r[ "word_band" ] ] ) for r in hit )

        print( f"{label:<8}{len( group ):>6}{len( hit ):>11}"
               f"{sum( r['words'] for r in group ):>10,}{saved:>12,.0f}"
               f"{100.0 * saved / triggered_total:>19.1f}%" )


def main():
    corpus = load_corpus()
    sample = reconstruct_sample( corpus )

    print( "=" * 104 )
    print( "DM CORPUS RE-CUT BY SENTENCES — 2026-08-12, Mr. Radio" )
    print(  "counter: cosa.agents.dm_tutor.sentences.count_sentences (claim rule)"
           f" · stated limit {STATED_LIMIT} · rewrite above {REWRITE_ABOVE}" )
    print( "=" * 104 )
    print( f"corpus {len( corpus ):,} bodies · reconstructed sample {len( sample )} messages" )

    sample_bands = sentence_band_table(
        sample, "THE 200 SAMPLED DMs — the set that ran last night" )
    corpus_bands = sentence_band_table(
        corpus, "THE FULL 2,951-BODY CORPUS — what the policy would actually meet" )

    divergence = counter_divergence( corpus )
    crosstab( sample )
    widths = four_sentences_in_words( corpus )

    sample_price = price_the_trigger( sample, "the 200 sampled DMs" )
    corpus_price = price_the_trigger( corpus, "the full corpus" )

    per_band_trigger_share( corpus )

    OUT_DIR.mkdir( parents=True, exist_ok=True )
    OUT_JSON.write_text( json.dumps( {
        "counter"       : "cosa.agents.dm_tutor.sentences.count_sentences",
        "rewrite_above" : REWRITE_ABOVE,
        "stated_limit"  : STATED_LIMIT,
        "measured_ratio_by_word_band" : MEASURED_RATIO,
        "sample_bands"  : sample_bands,
        "corpus_bands"  : corpus_bands,
        "divergence"    : divergence,
        "widths"        : widths,
        "sample_price"  : sample_price,
        "corpus_price"  : corpus_price,
        "per_message"   : [ { "words" : r[ "words" ], "sentences" : r[ "sentences" ],
                              "naive" : r[ "naive" ], "word_band" : r[ "word_band" ],
                              "sentence_band" : r[ "sentence_band" ] } for r in corpus ],
    }, indent=2, default=str ) )

    print( f"\nwritten → {OUT_JSON}" )


if __name__ == "__main__":
    main()
