"""
The flip-rate measure for the reuse tools.

A flip is a need whose answer differs between any two repeats of the same question.
The plan asks for at least 30 needs, each asked at least 5 times, and passes at 5% or less.
Two things make a repeat real here.
Its cache key holds the repeat number, and its receipt is not stored.
Without the first, repeat two reads repeat one's answer from the cache.
Without the second, repeat two reads repeat one's receipt, which is immutable once written.
Either way every flip rate would be zero.
This module sends nothing itself; the driver that spends tokens is separate.
"""
import copy

from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt

MIN_NEEDS   = 30
MIN_REPEATS = 5
PASS_LIMIT  = 0.05
ROUTES      = ( "full", "candidates" )
QUESTIONS   = ( "choice", "provides" )                 # the old question and the new one, by the name run_question takes


def _sweeper_factory( key_mode, kind=None ):
    """
    Build the factory behind the four public sweeper builders.

    Requires:
        - key_mode is "stage1" or "replay"
        - kind is None (the old question) or "pair" (the new question)
    Ensures:
        - returns factory( size, workers, run_index, breaker=None ) that checks its arguments, then returns a function with sweep's signature
        - the function sweeps in key_mode with the given run_index; it passes kind to sweep_packed only when kind is not None
    Raises:
        - ValueError from the factory for a size, worker count or run_index out of range, before anything is sent
    """
    check_args = () if kind is None else ( kind, )
    sweep_args = {} if kind is None else { "kind": kind }

    def factory( size, workers, run_index, breaker=None ):
        rp._check_sweep_args( size, workers, key_mode, run_index, *check_args )

        def sweeper( ctx, need, entries, frozen=False, template=None, model=None, gaps=None ):
            return rp.sweep_packed( ctx, need, entries, size, workers=workers, key_mode=key_mode, run_index=run_index, template=template, model=model,
                                    frozen=frozen, gaps=gaps, breaker=breaker, **sweep_args )

        return sweeper

    return factory


# The four public builders are kept as names because reuse_tools and the flip driver call them.
# Each caches answers under keys that hold run_index, so a repeat never reads another repeat's answers
# or the production answers; replay builders use replay keys, apart from the measurement arms.
repeat_sweeper       = _sweeper_factory( "stage1" )
repeat_pair_sweeper  = _sweeper_factory( "stage1", "pair" )
replay_sweeper       = _sweeper_factory( "replay" )
replay_pair_sweeper  = _sweeper_factory( "replay", "pair" )


def ask_repeat( ctx, need, member, run_index, workers=rp.WORKERS_DEFAULT, route="full", question="choice" ):
    """
    Ask one need once, as repeat number run_index, with the member left out.

    Requires:
        - ctx is a packed context: it has a sweeper and a pack size
        - need is a non-empty description; member is None or a symbol id of the index
        - route is "full" (every entry is asked) or "candidates" (the candidate stage: the shortlist's entries only, on a context that holds a candidate stage)
        - question is "choice" (the old question) or "provides" (the new one); the new question has no candidate stage, so it takes route "full" only
    Ensures:
        - returns the public result of that route, as sweep_need_impl does
        - the page questions carry the repeat number as the entry questions do
        - no receipt is written, so repeat two cannot be handed repeat one's receipt
        - the caller's context is not changed
    Raises:
        - ValueError for a context that is not packed, a route that is neither full nor candidates, a question that is neither choice nor provides,
          the new question by the candidates route, or a run_index out of range
    """
    if route not in ROUTES: raise ValueError( f"route must be one of {ROUTES}, got {route!r}" )
    if question not in QUESTIONS: raise ValueError( f"question must be one of {QUESTIONS}, got {question!r}" )
    if question == "provides" and route != "full": raise ValueError( f"the provides question has no candidate stage, got route {route!r}" )
    if ctx.sweeper is None or ctx.pack_size is None: raise ValueError( "a repeat is asked on a packed context only" )
    repeat         = copy.copy( ctx )
    repeat.sweeper = repeat_sweeper( ctx.pack_size, workers, run_index )
    if question == "provides": repeat.pair_sweeper = repeat_pair_sweeper( ctx.pack_size, workers, run_index )
    return rt.unstored_need_impl( need, member, repeat, candidates=route == "candidates", question=question, language="all" )


def signature( result ):
    """Ensures: returns the verdict and the sorted shortlist ids that must agree."""
    return result[ "verdict" ], tuple( sorted( s[ "id" ] for s in result[ "shortlist" ] ) )


def flip_rate( repeats_by_need ):
    """
    Work out how many needs changed answer between repeats.

    Requires:
        - repeats_by_need maps a need id to the list of its repeats' public results, each with status ok
    Ensures:
        - a need flips when any two of its repeats differ in signature, and counts once however often it changes
        - returns { needs, repeats_min, flips, flipped, rate, interval, upper, state }
        - flipped lists the flipping need ids in order; interval is the 95% Wilson interval of flips in needs; upper is its high end
        - state is "inconclusive" under MIN_NEEDS needs or MIN_REPEATS repeats of any need
        - otherwise state is "pass" at a rate of PASS_LIMIT or less, and "fail" above it
    Raises:
        - ValueError for no needs, a need with fewer than two repeats, or a repeat that is not a complete result
    """
    if not repeats_by_need: raise ValueError( "no needs to measure" )
    flipped, fewest = [], None
    for need in sorted( repeats_by_need ):
        runs = repeats_by_need[ need ]
        if len( runs ) < 2: raise ValueError( f"need {need!r} has {len( runs )} repeat(s); a flip needs at least two" )
        if any( r[ "status" ] != "ok" for r in runs ): raise ValueError( f"every repeat must be a complete result; need {need!r} has one that is not" )
        if len( { signature( r ) for r in runs } ) > 1: flipped.append( need )
        fewest = len( runs ) if fewest is None else min( fewest, len( runs ) )
    needs    = len( repeats_by_need )
    rate     = len( flipped ) / needs
    interval = e2e.wilson( len( flipped ), needs )
    state    = "inconclusive" if needs < MIN_NEEDS or fewest < MIN_REPEATS else ( "pass" if rate <= PASS_LIMIT else "fail" )
    return { "needs": needs, "repeats_min": fewest, "flips": len( flipped ), "flipped": flipped, "rate": rate, "interval": interval,
             "upper": interval[ 1 ], "state": state }
