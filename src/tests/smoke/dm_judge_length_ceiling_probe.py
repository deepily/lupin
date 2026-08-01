#!/usr/bin/env python3
"""
Is the DM judge's qualitative word ceiling still real? Measure it, don't inherit it.

WHY THIS EXISTS. `QUALITATIVE_WORD_LIMIT = 150` (judge.py) skips the qualitative half
entirely on any body past 150 words. That number was measured in July 2026 on the
Mistral-Small-24B checkpoint, through /v1/completions, with NO chat template applied —
the model stopped judging past ~150-200 words and started COPYING, either echoing the
prompt's worked example or regurgitating the DM back as a "grade" (bug 2a41e141).

Every part of that setup has since changed. The served checkpoint is Phi-4, and judge
v2 goes through /v1/chat/completions so vLLM applies the tokenizer's own chat template.
A ceiling is a claim about a model on a path; replace either and the claim is unproven,
not inherited. This is the instrument that re-tests it.

FIRST RESULT (2026-08-01, Phi-4 via chat, ceiling lifted): directness held its exact
short-length grade at 200 / 300 / 500 words on all four bodies — 48 calls, zero
non-answers, zero parroting. The 150 is unsupported for DIRECTNESS on the current
setup. It remains UNMEASURED for tone; see the caveat below.

THE DESIGN, AND THE ONE THING IT DELIBERATELY CANNOT ANSWER
-----------------------------------------------------------
Each of the discrimination probe's four 2x2 bodies is padded to a series of target
lengths with filler narration APPENDED AFTER the body — never inserted. That choice is
what makes the directness result attributable:

    - the verdict's sentence INDEX never moves, so the correct directness answer at
      500 words is the SAME answer as at 45 words. Any drift is the length, not the
      body;
    - the filler carries no outcome, decision, request, blocker or risk, so it can
      never become the "first payload" and change a BURIED body's correct answer.

🔴 THIS EXPERIMENT CANNOT SPEAK FOR TONE, and must not be quoted as if it does. Tone
   grades HOW THE PROSE READS, and padding changes exactly that: appending 450 words of
   rambling narration to a crisp body legitimately makes it read worse. Measured
   2026-08-01, DIRECT_PLAIN's tone went +2 → −1 purely from the filler. That is tone
   working, not tone failing — but it means this design holds directness's input fixed
   while confounding tone's. Answering the tone half needs long bodies that are
   NATIVELY plain or jargon-heavy, not padded ones. Nobody has run that.

WHAT WOULD SHOW THE CEILING IS REAL
    - a directness grade that departs from the same body's short-length grade, or
    - refusals / non-answers appearing as word count rises.
Both are reported per cell, and either fails the run.

VENUE. Touches NEITHER :7999 nor :8000 — it drives the local vLLM box directly and
mutates no persistent state. But it is SLOW: default 4 bodies x 4 lengths x 3 runs =
48 model calls, several minutes. It is an on-demand instrument, not part of any gate;
do not wire it into a suite that is expected to finish quickly.

Usage:  python dm_judge_length_ceiling_probe.py [runs] [--lengths 200,300,500]
Exit:   0 = directness held everywhere · 1 = it departed (or a cell measured nothing)
        2 = judge unavailable / nothing measured anywhere
"""
import os
import sys
from unittest.mock import patch

sys.path.insert( 0, os.path.join( os.environ[ "LUPIN_ROOT" ], "src" ) )
sys.path.insert( 0, os.path.dirname( os.path.abspath( __file__ ) ) )

from dm_judge_discrimination_probe import BODIES, nonanswer_kind
from cosa.agents.dm_quality_judge import get_dm_quality_judge

# Filler that is deliberately INERT: pure process narration with no outcome, decision,
# request, blocker or risk anywhere in it. If any sentence here qualified as a payload
# it could become the "first payload" of a BURIED body and silently change that body's
# correct answer — the padding would then be measuring itself.
FILLER = (
    "I went back through the notes from earlier in the week to see if anything lined up. "
    "There was a thread about it somewhere that I could not find again. "
    "I remember thinking at the time that it would probably come up later. "
    "The morning went by faster than I expected once I got going. "
    "I made a coffee and came back to it after a while. "
    "It reminded me of something similar from a while ago that I never followed up on. "
    "There were a few tabs open that I have since lost track of. "
    "Anyway that is roughly how the time went. "
)

DEFAULT_LENGTHS = [ 200, 300, 500 ]

# The directness grade each body earns at its natural (short) length, from the green
# 2x2. This is the BASELINE the padded runs are compared against — and every run
# re-measures it as its own control row rather than trusting this table, so a change in
# short-length behaviour shows up as a failure here instead of silently shifting the
# reference. The numbers are the expectation; the control row is the evidence.
EXPECTED_DIRECTNESS = {
    "DIRECT_PLAIN"  :  2,
    "DIRECT_JARGON" :  2,
    "BURIED_PLAIN"  : -1,
    "BURIED_JARGON" : -1,
}

DEFAULT_RUNS = 3


def pad_to( body, target_words ):
    """
    Append inert filler until the body reaches target_words.

    Requires:
        - body is a non-empty string
        - target_words is None, or a positive int

    Ensures:
        - target_words None returns the body unchanged (the control row)
        - otherwise returns exactly target_words words, the ORIGINAL body first and
          filler only after it — the verdict's sentence index is never disturbed
        - a target SHORTER than the body truncates; callers should not do that, and
          the caller below never does
    """
    if target_words is None: return body
    out = body
    while len( out.split() ) < target_words:
        out = out + " " + FILLER
    return " ".join( out.split()[ : target_words ] )


def measure_cell( judge, body, runs ):
    """
    Grade one body `runs` times with the ceiling lifted; split real grades from silences.

    Requires:
        - judge is a built judge with qualitative grading enabled
        - body is the (possibly padded) DM text

    Ensures:
        - returns {"directness": [weights], "tone": [weights], "nonanswers": [kinds]}
        - a non-answer NEVER appears as a weight — it is classified by its detail via
          the discrimination probe's own classifier (imported, never re-typed) and kept
          in its own list. A refusal counted as 0 would look like a real `meh` and could
          make a ceiling look absent when the model had actually stopped answering
    """
    out = { "directness": [ ], "tone": [ ], "nonanswers": [ ] }
    for _ in range( runs ):
        # The ceiling is the thing under test, so it is lifted HERE rather than edited
        # in the config — the probe must never leave the ceiling changed behind it.
        with patch( "cosa.agents.dm_quality_judge.judge_v2.QUALITATIVE_WORD_LIMIT", 100_000 ):
            result = judge.judge( body )
        for key in ( "directness", "tone" ):
            dim  = result[ key ]
            kind = nonanswer_kind( dim )
            if kind is None: out[ key ].append( dim[ "weight" ] )
            else:            out[ "nonanswers" ].append( f"{key}:{kind}" )
    return out


def main():
    argv    = list( sys.argv[ 1: ] )
    lengths = list( DEFAULT_LENGTHS )
    if "--lengths" in argv:
        i       = argv.index( "--lengths" )
        lengths = [ int( x ) for x in argv[ i + 1 ].split( "," ) ]
        del argv[ i : i + 2 ]
    # --model swaps the CHECKPOINT while holding everything else — same prompts, same
    # chat path, same bodies — so a difference is attributable to the model. Note the
    # spec key must name the checkpoint the server is ACTUALLY serving: the model name
    # rides in the request body and vLLM validates it, so pointing a Phi-4 key at a
    # server now serving the 24B 404s every call.
    spec_key = None
    if "--model" in argv:
        i        = argv.index( "--model" )
        spec_key = argv[ i + 1 ]
        del argv[ i : i + 2 ]
    runs = int( argv[ 0 ] ) if argv else DEFAULT_RUNS

    kwargs = { "llm_spec_key": spec_key } if spec_key else { }
    judge  = get_dm_quality_judge( version=2, qualitative_enabled=True, **kwargs )
    if not judge.available:
        print( "✗ judge LLM unavailable — probe cannot run" )
        return 2

    print( "── DM judge length-ceiling probe ─────────────────────────────────────" )
    print( "⚠ The word ceiling is LIFTED for this probe. Production still enforces it;" )
    print( "  this measures whether it is still NEEDED, not how the judge behaves live." )
    print( "⚠ Directness only. Padding changes how the prose reads, so the tone column" )
    print( "  below is NOT evidence about tone at length — see the module docstring." )
    print( f"  {runs} run(s) per cell · lengths {lengths} · ceiling lifted" )
    print( f"  model spec: {spec_key or 'default (dm_quality_judge_v2/phi_4)'}\n" )

    print( f"{'body':<15}{'words':<8}{'expect':<8}{'directness':<24}{'tone':<16}{'non-answers'}" )
    print( "-" * 88 )

    departures   = [ ]
    dead_cells   = [ ]
    total_real   = 0

    for name, body in BODIES:
        expected = EXPECTED_DIRECTNESS[ name ]
        for target in [ None ] + lengths:
            padded = pad_to( body, target )
            words  = len( padded.split() )
            cell   = measure_cell( judge, padded, runs )
            dws    = sorted( set( cell[ "directness" ] ) )
            tws    = sorted( set( cell[ "tone" ] ) )
            nas    = sorted( set( cell[ "nonanswers" ] ) )
            total_real += len( cell[ "directness" ] )

            if not cell[ "directness" ]:
                mark = "✗✗ "
                dead_cells.append( f"{name} @ {words}w produced NO real directness grade" )
            elif all( w == expected for w in cell[ "directness" ] ):
                mark = "ok  "
            else:
                mark = "✗   "
                tag  = "control row" if target is None else f"{words}w"
                departures.append( f"{name} @ {tag}: directness {dws}, expected {expected}" )

            print( f"{name:<15}{words:<8}{expected:<8}{mark}{str( dws or 'NONE' ):<20}"
                   f"{str( tws or 'NONE' ):<16}{','.join( nas ) or '-'}" )

    print( "\n" + "=" * 88 )

    # Measured-nothing fails HARDEST — it must never be mistakable for "no drift found".
    if total_real == 0:
        print( "✗ MEASURED NOTHING — every directness result was a non-answer. NOT a pass." )
        return 2

    for line in dead_cells:  print( f"  ✗ DEAD CELL: {line}" )
    for line in departures:  print( f"  ✗ DEPARTED:  {line}" )

    if dead_cells or departures:
        print( "\n✗ THE CEILING SHOWS ITSELF — directness did not survive at every length." )
        return 1

    print( f"✓ DIRECTNESS HELD its short-length grade at every tested length "
           f"({total_real} real grades, 0 non-answers)." )
    print( "  ⚠ Tone at length remains UNMEASURED — this design cannot answer it." )
    return 0


if __name__ == "__main__":
    raise SystemExit( main() )
