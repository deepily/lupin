"""
The stage runner for the first 1,000 model calls of Set B (plan section 11.4).

Four stages run in order under one shared call cap, and each has a call budget of its own: attribution, yield, control, remainder. The control is built elsewhere and handed in.
The runner makes no call of its own. It never builds a packet, takes a person's ruling or writes a label file.
"""
from cosa.repo.doc_lint import harness_report, model_transport
from cosa.repo.labelling import run_check
from lupin_mcp.reuse_needset import call_cap, hardness, loss_trace
from lupin_mcp.reuse_needset import errors as er

ATTRIBUTION   = "attribution"
YIELD         = "yield"
CONTROL       = "control"
REMAINDER     = "remainder"
ORDER         = ( ATTRIBUTION, YIELD, CONTROL, REMAINDER )
# The budgets of 1 November 2026 (Rick raised the run to 1,314 calls): yield is the sample of about 100 random seeds at about 6 calls a seed with room to spare,
# control is two passes of the 20 planted pairs at about 5 calls a pair, remainder makes no call, so its budget is none. 164 calls stay unallocated, held for Rick.
PLANNED_CALLS = { ATTRIBUTION: 300, YIELD: 600, CONTROL: 250 }
STAGE_BUDGETS = { **PLANNED_CALLS, REMAINDER: 0 }
YIELD_SEEDS   = 100
LOST_STAGES   = ( loss_trace.NOT_RETRIEVED, loss_trace.NOT_RATED_RELEVANT, loss_trace.NOT_READ, loss_trace.NOT_RULED_SAME_JOB )
DRIFTED       = "drifted"
UNSURE        = "unsure"
DONE          = "done"
STOPPED       = "stopped"
CAP_REACHED   = "cap_reached"
BUDGET_REACHED = "budget_reached"
FAILED        = "failed"
NOT_RUN       = "not_run"


def attribution_report( records ):
    """
    Say whether the trace named a losing stage for any key member.

    Requires:
        - records come from loss_trace.trace_all and hold at least one matched need

    Ensures:
        - returns { members, lost, found, by_lost_at, can_name_a_stage, stop, summary }
        - lost counts the members that failed at one of the four stages
        - can_name_a_stage is True when at least one member was lost at a named stage
        - stop is True when none was, because a run in which nothing is lost shows nothing about naming the stage that lost it
        - summary is loss_trace.summarize_members over the records
    """
    summary = loss_trace.summarize_members( records )
    lost    = sum( n for k, n in summary[ "by_lost_at" ].items() if k in LOST_STAGES )
    return { "members": summary[ "members" ], "lost": lost, "found": summary[ "by_lost_at" ].get( loss_trace.FOUND, 0 ), "by_lost_at": summary[ "by_lost_at" ],
             "can_name_a_stage": lost > 0, "stop": lost == 0, "summary": summary }


async def run_yield( seed_ids, prepare_fn, index, k=hardness.BM25_K ):
    """
    Draw a need and its partners for each seed, then count how many a word search misses.

    Requires:
        - prepare_fn is an async function taking a seed id and returning { seed, need, targets, lang }, or None for a seed with no partner
        - index is a hardness index; each prepare_fn call may make model calls, which the shared cap counts

    Ensures:
        - seeds run one at a time in the order given, so the calls fall in a fixed order
        - returns { k, seeds, skipped, hard, by_lang, intervals, stop, short, budget_reached }
        - when the running stage's own call budget ends the walk, the seeds done so far are reported, budget_reached is True and budget_detail names the stop; seeds_left counts the seeds never started
        - by_lang and hard come from hardness.yield_report over the seeds that had a partner
        - intervals maps each language to the two-sided 95 percent interval of its hard share
        - stop is True when a language with at least YIELD_SEEDS seeds has no hard row
        - short lists the languages that had fewer seeds than YIELD_SEEDS, which is a warning and not a stop
    """
    rows, skipped, detail, left = [], 0, None, 0
    for n, seed_id in enumerate( seed_ids ):
        try:
            row = await prepare_fn( seed_id )
        except er.NeedsetError as error:
            if error.code != er.STAGE_BUDGET_REACHED: raise
            detail, left = error.detail, len( seed_ids ) - n
            break
        if row is None: skipped += 1
        else: rows.append( row )
    report = hardness.yield_report( hardness.source_hard( rows, index, k ), k )
    by_lang = report[ "by_lang" ]
    return { **report, "skipped": skipped, "budget_reached": detail is not None, "budget_detail": detail, "seeds_left": left,
             "intervals": { lang: harness_report.interval( v[ "hard" ], v[ "seeds" ] ) for lang, v in by_lang.items() },
             "stop": any( v[ "seeds" ] >= YIELD_SEEDS and v[ "hard" ] == 0 for v in by_lang.values() ),
             "short": sorted( lang for lang, v in by_lang.items() if v[ "seeds" ] < YIELD_SEEDS ) }


def run_remainder( pairs, seed, check_fn=run_check.check_pair ):
    """
    Run Set A's synthetic pairs through the run-check and count what it catches and resolves.

    Requires:
        - pairs are { id, group, original, rewrite } mappings; group is drifted, unsure or another label
        - check_fn( original, rewrite, seed ) returns a verdict with a route, as run_check.check_pair does

    Ensures:
        - returns { pairs, drifted, unsure, routes, per_pair }
        - drifted and unsure hold { total, caught or resolved }: a drifted pair is caught on route reject, an unsure pair is resolved on accept or reject
        - routes counts every verdict route over all pairs
        - no model is contacted
    """
    per_pair, routes = [], {}
    for pair in pairs:
        verdict = check_fn( pair[ "original" ], pair[ "rewrite" ], seed )
        routes[ verdict[ "route" ] ] = routes.get( verdict[ "route" ], 0 ) + 1
        per_pair.append( { "id": pair[ "id" ], "group": pair[ "group" ], "route": verdict[ "route" ], "reason": verdict[ "reason" ] } )
    drifted = [ p for p in per_pair if p[ "group" ] == DRIFTED ]
    unsure  = [ p for p in per_pair if p[ "group" ] == UNSURE ]
    return { "pairs": len( per_pair ), "routes": dict( sorted( routes.items() ) ), "per_pair": per_pair,
             "drifted": { "total": len( drifted ), "caught": sum( 1 for p in drifted if p[ "route" ] == run_check.REJECT ) },
             "unsure": { "total": len( unsure ), "resolved": sum( 1 for p in unsure if p[ "route" ] in ( run_check.ACCEPT, run_check.REJECT ) ) } }


async def run_stages( cap, stages, on_raise=None ):
    """
    Run the four stages in order under one cap and report each.

    Requires:
        - cap is a call_cap.CallCap that is installed, so model_transport calls are charged to it; its stage_limits are the budgets the stages keep to
        - stages maps each of the four stage names to async functions taking no argument and returning a report dict
        - on_raise is None, or a function taking the report so far; it is called, then the error goes on, when a stage raises something that is not a NeedsetError
        - a report with stop true ends the run; a report may be built by attribution_report, run_yield, run_remainder or the control

    Ensures:
        - each stage runs inside call_cap.stage( its name ), so its calls carry the name
        - returns { used, limit, by_stage, over_plan, stages } with a status per stage: done, stopped, cap_reached, budget_reached, failed or not_run
        - a stage after a stop, a failure or the cap is not_run and never starts
        - a stage that spends its own budget ends as budget_reached with the code and detail, and the stages after it still run, because it took nothing from them
        - over_plan lists each stage that spent more than PLANNED_CALLS allows, which only a cap built without stage limits can show
        - a report that says budget_reached is kept whole and ends as budget_reached, and the stages after it still run
        - the cap, the stop and a named failure end the run with a report and no exception

    Raises:
        - NeedsetError CAP_NOT_INSTALLED when model_transport.CHARGE_HOOK is not this cap's charge, before any stage starts
        - ValueError when a stage is missing
        - whatever a stage raises that is not a NeedsetError, after on_raise has been given the finished stages' reports, the stage that raised as failed with the error's class and message, and the stages after it as not_run
    """
    if model_transport.CHARGE_HOOK != cap.charge: raise er.NeedsetError( er.CAP_NOT_INSTALLED, "run_stages needs the cap installed, or model calls would go uncounted" )
    missing = [ name for name in ORDER if name not in stages ]
    if missing: raise ValueError( f"stages missing: {missing}" )
    results, halted = {}, False

    def finished():
        """Ensures: returns the report of the stages so far."""
        spent = cap.by_stage()
        return { "used": cap.used(), "limit": cap.limit, "by_stage": spent, "stages": { **results, **{ n: { "status": NOT_RUN } for n in ORDER if n not in results } },
                 "over_plan": sorted( name for name, allowed in PLANNED_CALLS.items() if spent.get( name, 0 ) > allowed ) }

    for name in ORDER:
        if halted:
            results[ name ] = { "status": NOT_RUN }
            continue
        try:
            with call_cap.stage( name ):
                report = await stages[ name ]()
            results[ name ] = { "status": BUDGET_REACHED if report.get( "budget_reached" ) else STOPPED if report.get( "stop" ) else DONE, "report": report }
            halted          = bool( report.get( "stop" ) )
        except er.NeedsetError as error:
            budget          = error.code == er.STAGE_BUDGET_REACHED
            results[ name ] = { "status": BUDGET_REACHED if budget else CAP_REACHED if error.code == er.CALL_CAP_REACHED else FAILED, "code": error.code, "detail": error.detail }
            halted          = not budget
        except BaseException as error:
            results[ name ] = { "status": FAILED, "code": type( error ).__name__, "detail": str( error ) }
            if on_raise is not None: on_raise( finished() )
            raise
    return finished()
