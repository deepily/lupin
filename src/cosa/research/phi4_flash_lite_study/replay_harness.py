"""
The paired replay harness for the Phi-4 vs Flash-Lite study (handoff §7 item 2).

WHAT IT DOES. Reads the FROZEN snapshot, and for each body calls the production
`_apply_dm_tutor` once per arm, recording the returned `meta` dict VERBATIM.
Nothing in the tutor changes: the arm is swapped by handing `_apply_dm_tutor` a
per-arm `rewrite_fn`, a seam the function already exposes at `dm.py:1121`.

⚠️ WHY NOT JUST REPOINT THE INI. The one-line way to run the Flash-Lite arm is to
change `llm spec key for dm tutor rewrite` at `src/conf/lupin-app.ini:303`. Do not.
That swaps the model for EVERY DM the whole fleet sends while the arm runs, spends
on a paid endpoint outside the experiment, and writes those rows into the very
corpus under study (~5 rows/min). The injection seam costs one function and touches
no shared state. (Reviewer finding F4.)

⚠️ THREE WAYS THIS HARNESS CAN REPORT A CLEAN RUN THAT MEASURED NOTHING, and what
stops each. All three exist because `_apply_dm_tutor` is contractually incapable of
raising — every failure it meets becomes a recorded `meta` field, and a field is
not an alarm.

  1. THE TUTOR WAS OFF. `get_dm_tutor_config()` is fail-closed: without
     `LUPIN_CONFIG_MGR_CLI_ARGS` in the environment it returns `enabled: False`,
     prints one line to stdout, and every row comes back `tutor_outcome:
     "disabled"`. Both arms then agree perfectly and mean nothing.
     ⇒ `assert_row_is_measurable` ABORTS on the first row whose `tutor_enabled` or
     `tutor_fired` is not True. (Reviewer finding F2.)
  2. THE ARM WAS BROKEN. Missing ADC, a dead region, an expired credential — each
     returns `tutor_outcome: "model_failed"` per row and the run completes. That is
     the same shape as a model that occasionally refuses.
     ⇒ a PRE-STATED `model_failed` ceiling, checked on a pre-flight prefix BEFORE
     the full replay is paid for, and again at the end. (Reviewer finding F3.)
  3. THE DENOMINATOR WAS GUESSED. The fabrication rate's denominator (narrow vs
     wide) is an OPEN DECISION owned by Rick, row `76755526`.
     ⇒ `FABRICATION_DENOMINATOR` is UNSET here and `fabrication_rate` raises until
     someone passes a real one. A plausible-looking default would close Rick's
     decision by implementation. (Reviewer finding F1.)

Run:
    python -m cosa.research.phi4_flash_lite_study.replay_harness \
        --snapshot-dir <frozen dir> --out <results.jsonl> \
        --max-model-failed-rate 0.05 --preflight 25 [--limit N] [--arm phi_4|flash_lite]
"""

import os
import sys
import json
import time
import argparse
import datetime

from cosa.research.phi4_flash_lite_study import freeze_corpus
from cosa.research.phi4_flash_lite_study.arm_markers import ArmNotVerified, check_arm_markers


# The two arms, named by the INI spec key each one routes to. These keys are read
# by the FACTORY, not written by this harness — `dm_tutor/phi_4` and
# `dm_tutor/flash_lite` both already exist at `src/conf/lupin-app.ini:227,232`.
ARM_PHI4       = "phi_4"
ARM_FLASH_LITE = "flash_lite"

ARM_SPEC_KEYS = {
    ARM_PHI4       : "dm_tutor/phi_4",
    ARM_FLASH_LITE : "dm_tutor/flash_lite",
}

# 🔴 UNSET ON PURPOSE — reviewer finding F1. The fabrication rate's denominator is
# an OPEN DECISION owned by Rick (row `76755526`); the input plan carries the
# literal placeholder `DENOMINATOR-TBD` so that anyone wiring the metric has to go
# find the decision rather than pick a plausible formula. Wiring a default here
# would close Rick's decision by implementation, which is exactly what the
# placeholder exists to prevent.
#
#   "narrow" -> fabrication_blocked / ( fabrication_blocked + rewritten )
#   "wide"   -> fabrication_blocked / ( every row where the tutor FIRED )
#
# The two differ by whether the other refusals (rescope_blocked, label_blocked,
# gate_rejected, model_failed) belong under the line. Same choice both arms.
FABRICATION_DENOMINATOR = None

VALID_DENOMINATORS = ( "narrow", "wide" )

# Outcomes `_apply_dm_tutor` can record once it has FIRED. Kept as a named set so a
# new tutor outcome shows up as an unknown-outcome abort rather than being silently
# dropped out of every denominator.
FIRED_OUTCOMES = (
    "rewritten", "fabrication_blocked", "rescope_blocked",
    "label_blocked", "gate_rejected", "model_failed", "error",
)


class UnmeasurableRow( RuntimeError ):
    """The tutor did not actually run on this row — the arm would be vacuous."""


class ArmBroken( RuntimeError ):
    """The arm's model_failed rate cleared a pre-stated ceiling; stop paying for it."""


class DenominatorUnset( RuntimeError ):
    """Someone asked for a fabrication rate without saying which denominator."""


def verify_arm_surface( arm, factory=None ):
    """
    Prove the arm is on the model it claims BEFORE a single row is recorded.

    Delegates to `arm_markers.check_arm_markers` — Sam's four markers, read off the
    SDK object the call would ride, kept in ONE place so the harness and the tests
    cannot drift about what "this arm reached Vertex" means.

    ⚠️ A green here means the arm is WIRED to Vertex, not that flash-lite answered:
    M2 reads `client.model_name`, which is the descriptor we handed the factory. The
    genuine read-back is `response.model_version`, which exists only after a paid
    call. See `arm_markers` for the full note.

    Requires:
        - arm is one of ARM_SPEC_KEYS

    Ensures:
        - returns the observed marker dict for the Flash-Lite arm, None for phi_4
        - makes NO network call and resolves no credentials — construction only

    Raises:
        - ArmNotVerified when a marker does not hold, or when the arms are crossed
    """
    return check_arm_markers( ARM_SPEC_KEYS[ arm ], expect_vertex=( arm == ARM_FLASH_LITE ),
                              factory=factory )


# ─────────────────────────────────────────────────────────────────────────────
# LOADING THE FROZEN SET (never the live corpus — the freezer's guard enforces it)
# ─────────────────────────────────────────────────────────────────────────────

def load_frozen_rows( snapshot_dir, freezer=None ):
    """
    Read the pinned replay set, refusing the live corpus and a drifted snapshot.

    Requires:
        - snapshot_dir holds dm_replay_frozen.jsonl and manifest.json

    Ensures:
        - returns ( rows, manifest )
        - RAISES rather than reading the live append-only corpus, which would
          unpair the arms
        - RAISES when the snapshot's checksum no longer matches its manifest, so a
          replay never silently runs on an edited set

    Raises:
        - LivePathRefused if snapshot_dir IS the live corpus's directory, or if the
          snapshot file within it resolves onto the live corpus file
        - RuntimeError if the snapshot does not verify against its manifest
    """
    fz            = freezer if freezer is not None else freeze_corpus
    snapshot_path = os.path.join( snapshot_dir, fz.SNAPSHOT_FILENAME )
    manifest_path = os.path.join( snapshot_dir, fz.MANIFEST_FILENAME )

    fz.assert_dir_is_not_live_corpus_dir( snapshot_dir )
    fz.assert_snapshot_is_not_live( snapshot_path )

    ok, detail = fz.verify_snapshot( snapshot_path, manifest_path )
    if not ok:
        raise RuntimeError( f"frozen snapshot does not match its manifest: {detail}" )

    rows, _ = fz.read_corpus_rows( snapshot_path )
    with open( manifest_path, "r", encoding="utf-8" ) as handle:
        manifest = json.load( handle )
    return rows, manifest


# ─────────────────────────────────────────────────────────────────────────────
# THE ARM SEAM — swap the model without touching the tutor or the shared INI
# ─────────────────────────────────────────────────────────────────────────────

def make_arm_rewrite_fn( arm, agent_cls=None ):
    """
    Build the per-arm `rewrite_fn` that `_apply_dm_tutor` will call.

    Constructs the SAME `DmTutorAgent` the production path constructs — same
    prompt template, same stop sentinel, same parser — then overrides only
    `model_name`, which `AgentBase.run_prompt` reads at call time
    (`agent_base.py:305`) to pick the client. That is the entire difference
    between the arms.

    Requires:
        - arm is one of ARM_SPEC_KEYS

    Ensures:
        - returns a callable taking one body and returning distilled text or None
        - the callable is FAIL-CLOSED exactly like production `rewrite_dm`: any
          construction or call failure returns None, which the tutor records as
          `model_failed` rather than raising into the replay
        - NOTHING in the tutor, the agent class, or lupin-app.ini is mutated

    Raises:
        - KeyError if arm is not a known arm
    """
    spec_key = ARM_SPEC_KEYS[ arm ]

    def rewrite_fn( dm_body ):
        cls = agent_cls
        if cls is None:
            from cosa.agents.dm_tutor.agent import DmTutorAgent
            cls = DmTutorAgent
        try:
            agent            = cls( dm_body=dm_body )
            agent.model_name = spec_key
        except Exception:
            return None
        return agent.rewrite()

    rewrite_fn.arm      = arm
    rewrite_fn.spec_key = spec_key
    return rewrite_fn


# ─────────────────────────────────────────────────────────────────────────────
# THE THREE GUARDS
# ─────────────────────────────────────────────────────────────────────────────

def assert_row_is_measurable( meta, row_index, arm ):
    """
    Refuse to record a row on which the tutor never actually ran. (F2.)

    A run where `LUPIN_CONFIG_MGR_CLI_ARGS` is unset comes back with every row
    `tutor_enabled: False`, `tutor_outcome: "disabled"`, both arms in perfect
    agreement and both empty. Nothing raises and nothing looks wrong.

    Requires:
        - meta is the dict `_apply_dm_tutor` returned

    Ensures:
        - returns None when the tutor was enabled AND fired on this row
        - names the row index, the arm, and the offending outcome in the message

    Raises:
        - UnmeasurableRow when tutor_enabled or tutor_fired is not True
    """
    if meta.get( "tutor_enabled" ) is not True:
        raise UnmeasurableRow(
            f"arm '{arm}' row {row_index}: tutor_enabled is {meta.get( 'tutor_enabled' )!r}, "
            f"outcome {meta.get( 'tutor_outcome' )!r}. The tutor did not run — every row of this "
            f"arm would be empty and both arms would agree perfectly. Is LUPIN_CONFIG_MGR_CLI_ARGS "
            f"exported in this process?"
        )
    if meta.get( "tutor_fired" ) is not True:
        raise UnmeasurableRow(
            f"arm '{arm}' row {row_index}: tutor_fired is {meta.get( 'tutor_fired' )!r}, "
            f"outcome {meta.get( 'tutor_outcome' )!r}. The frozen set should contain only "
            f"over-trigger bodies — a row that does not fire means the snapshot and the live "
            f"trigger config disagree."
        )


def model_failed_rate( metas ):
    """
    Share of fired rows the model failed to answer usefully.

    Requires:
        - metas is a list of meta dicts

    Ensures:
        - returns 0.0 for an empty list rather than raising
        - counts `model_failed` over ALL rows given, which are all fired rows by
          the time this is called

    Raises:
        - nothing
    """
    if not metas: return 0.0
    failed = sum( 1 for m in metas if m.get( "tutor_outcome" ) == "model_failed" )
    return failed / len( metas )


def assert_arm_is_alive( metas, ceiling, arm, phase ):
    """
    Stop an arm whose model is not answering, rather than buying 4,900 nulls. (F3.)

    Requires:
        - ceiling is a float in [0, 1], PRE-STATED before arm 1 — this function
          takes it as a parameter and has no default, so the number is always
          someone's stated decision rather than this file's opinion

    Ensures:
        - returns the measured rate when it is at or under the ceiling
        - the message names the phase (preflight or final) and both numbers

    Raises:
        - ArmBroken when the measured rate exceeds the ceiling
    """
    rate = model_failed_rate( metas )
    if rate > ceiling:
        raise ArmBroken(
            f"arm '{arm}' {phase}: model_failed rate {rate:.3f} over {len( metas )} rows exceeds the "
            f"pre-stated ceiling {ceiling:.3f}. A totally broken arm and an occasionally-refusing one "
            f"record identically; this is the line that tells them apart."
        )
    return rate


def fabrication_rate( metas, denominator=None ):
    """
    fabrication_blocked over the denominator Rick chose. (F1.)

    Requires:
        - denominator is "narrow" or "wide" — there is NO default, deliberately

    Ensures:
        - "narrow" divides by ( fabrication_blocked + rewritten )
        - "wide"   divides by every fired row
        - returns None when the denominator is zero, which is honestly "no rate
          exists" rather than a zero that reads like a clean arm

    Raises:
        - DenominatorUnset when denominator is None (and the module constant is
          still unset), naming the open decision row
        - ValueError when denominator is not a recognised choice
    """
    choice = denominator if denominator is not None else FABRICATION_DENOMINATOR
    if choice is None:
        raise DenominatorUnset(
            "fabrication_rate needs a denominator and none was given. The narrow-vs-wide choice is "
            "an OPEN DECISION owned by Rick (row 76755526); the input plan carries the literal "
            "placeholder DENOMINATOR-TBD so that wiring the metric forces someone to go find the "
            "decision. Pass denominator='narrow' or 'wide' — the same one for BOTH arms — and record "
            "it in the report."
        )
    if choice not in VALID_DENOMINATORS:
        raise ValueError( f"denominator must be one of {VALID_DENOMINATORS}, got {choice!r}" )

    blocked = sum( 1 for m in metas if m.get( "tutor_outcome" ) == "fabrication_blocked" )
    if choice == "narrow":
        total = blocked + sum( 1 for m in metas if m.get( "tutor_outcome" ) == "rewritten" )
    else:
        total = sum( 1 for m in metas if m.get( "tutor_fired" ) is True )

    if total == 0: return None
    return blocked / total


def summarize_arm( metas, denominator=None ):
    """
    The per-arm counters §2.3 kept, after the pointer-survival metric was dropped.

    Requires:
        - metas is a list of meta dicts from one arm

    Ensures:
        - returns a dict of outcome counts, the model_failed coverage rate, the
          fabrication rate under the chosen denominator, and the claim/word medians
        - `unknown_outcomes` lists any outcome not in FIRED_OUTCOMES, so a new
          tutor outcome surfaces instead of vanishing from every denominator

    Raises:
        - DenominatorUnset when no denominator has been chosen
    """
    counts = {}
    for meta in metas:
        outcome           = meta.get( "tutor_outcome" )
        counts[ outcome ] = counts.get( outcome, 0 ) + 1

    claims_out = sorted( m[ "tutor_claims_out" ] for m in metas if m.get( "tutor_claims_out" ) is not None )
    words_out  = sorted( m[ "tutor_words_out" ]  for m in metas if m.get( "tutor_words_out" )  is not None )

    return {
        "rows"                : len( metas ),
        "outcome_counts"      : counts,
        "unknown_outcomes"    : sorted( o for o in counts if o not in FIRED_OUTCOMES ),
        "fabrication_blocked" : counts.get( "fabrication_blocked", 0 ),
        "rescope_blocked"     : counts.get( "rescope_blocked", 0 ),
        "label_blocked"       : counts.get( "label_blocked", 0 ),
        "rewritten"           : counts.get( "rewritten", 0 ),
        "model_failed"        : counts.get( "model_failed", 0 ),
        "model_failed_rate"   : model_failed_rate( metas ),
        "fabrication_rate"    : fabrication_rate( metas, denominator=denominator ),
        "denominator"         : denominator if denominator is not None else FABRICATION_DENOMINATOR,
        "median_claims_out"   : _median( claims_out ),
        "median_words_out"    : _median( words_out ),
    }


def _median( sorted_values ):
    """
    Median of an already-sorted list.

    Requires:
        - sorted_values is sorted ascending

    Ensures:
        - returns None for an empty list rather than raising
        - averages the middle pair for an even count

    Raises:
        - nothing
    """
    n = len( sorted_values )
    if n == 0: return None
    mid = n // 2
    if n % 2: return sorted_values[ mid ]
    return ( sorted_values[ mid - 1 ] + sorted_values[ mid ] ) / 2


# ─────────────────────────────────────────────────────────────────────────────
# THE REPLAY
# ─────────────────────────────────────────────────────────────────────────────

def replay_arm( rows, arm, tutor_fn=None, rewrite_fn=None, config=None,
                max_model_failed_rate=None, preflight=25, on_row=None,
                verify_surface=True ):
    """
    Run every frozen body through one arm, recording each `meta` verbatim.

    Requires:
        - rows is the frozen replay set
        - max_model_failed_rate is a PRE-STATED float — no default, per F3

    Ensures:
        - returns a list of records, one per row, in frozen-set order, each holding
          the row's identity, the delivered text, and the tutor's `meta` UNCHANGED
        - PROVES the arm reached the surface it claims before recording row 0
        - aborts on the first unmeasurable row rather than recording it
        - checks the model_failed ceiling on the first `preflight` rows BEFORE
          paying for the rest, and again over the whole arm
        - never touches the tutor, the agent class, or lupin-app.ini

    Raises:
        - ValueError when max_model_failed_rate was not stated
        - ArmNotVerified / UnmeasurableRow / ArmBroken per the guards above
    """
    if max_model_failed_rate is None:
        raise ValueError(
            "max_model_failed_rate must be PRE-STATED before the arm runs (reviewer finding F3). "
            "A broken arm and an occasionally-refusing model record identically."
        )

    # Before row 0, not after the run: a fall-through arm answers well and would
    # otherwise produce a full set of plausible numbers for the wrong model.
    if verify_surface: verify_arm_surface( arm )

    if tutor_fn is None:
        from cosa.rest.routers.dm import _apply_dm_tutor
        tutor_fn = _apply_dm_tutor
    if rewrite_fn is None:
        rewrite_fn = make_arm_rewrite_fn( arm )

    records    = []
    metas      = []
    preflighted = False

    for index, row in enumerate( rows ):
        body     = row.get( "body" ) or ""
        started  = time.monotonic()
        delivered, meta = tutor_fn( body, config=config, rewrite_fn=rewrite_fn )
        elapsed  = time.monotonic() - started

        assert_row_is_measurable( meta, index, arm )

        record = {
            "row_index"      : index,
            "arm"            : arm,
            "spec_key"       : ARM_SPEC_KEYS[ arm ],
            "ts"             : row.get( "ts" ),
            "from"           : row.get( "from" ),
            "to"             : row.get( "to" ),
            "body"           : body,
            "delivered"      : delivered,
            "delivered_differs" : delivered != body,
            "elapsed_seconds": round( elapsed, 4 ),
            "meta"           : meta,                       # verbatim, per the work order
        }
        records.append( record )
        metas.append( meta )
        if on_row is not None: on_row( record )

        if not preflighted and len( metas ) >= preflight:
            assert_arm_is_alive( metas, max_model_failed_rate, arm, "preflight" )
            preflighted = True

    assert_arm_is_alive( metas, max_model_failed_rate, arm, "final" )
    return records


def pair_records( arm_a_records, arm_b_records ):
    """
    Join the two arms on row index so every comparison is within one body.

    Requires:
        - both lists came from the SAME frozen snapshot

    Ensures:
        - returns a list of { row_index, body, <arm_a>, <arm_b> } dicts
        - RAISES rather than silently truncating when the two arms disagree about
          which rows they saw — unpaired arms are the failure the freeze exists to
          prevent, and a zip() would hide it

    Raises:
        - ValueError when the arms' row indices do not match exactly
    """
    a_index = [ r[ "row_index" ] for r in arm_a_records ]
    b_index = [ r[ "row_index" ] for r in arm_b_records ]
    if a_index != b_index:
        raise ValueError(
            f"the two arms did not see the same rows: {len( a_index )} vs {len( b_index )} records. "
            f"They are not paired, so no per-body comparison is valid."
        )

    paired = []
    for rec_a, rec_b in zip( arm_a_records, arm_b_records ):
        paired.append( {
            "row_index"          : rec_a[ "row_index" ],
            "body"               : rec_a[ "body" ],
            rec_a[ "arm" ]       : rec_a,
            rec_b[ "arm" ]       : rec_b,
        } )
    return paired


def discordant_counts( paired, arm_a, arm_b, outcome="fabrication_blocked" ):
    """
    The b / c cells McNemar's test reads, over paired rows.

    Requires:
        - paired came from pair_records
        - both arm names are keys in every paired entry

    Ensures:
        - returns ( b, c ) where b = rows where ONLY arm_a hit the outcome and
          c = rows where ONLY arm_b did
        - concordant rows contribute to neither, which is McNemar's whole point

    Raises:
        - KeyError if an arm name is not present in a paired entry
    """
    b = 0
    c = 0
    for entry in paired:
        a_hit = entry[ arm_a ][ "meta" ].get( "tutor_outcome" ) == outcome
        b_hit = entry[ arm_b ][ "meta" ].get( "tutor_outcome" ) == outcome
        if a_hit and not b_hit: b += 1
        if b_hit and not a_hit: c += 1
    return b, c


def main( argv=None, printer=print, runner=None ):
    """
    Command-line entry point. Tested, not pragma'd.

    Requires:
        - argv is None (read sys.argv) or a list of arguments
        - runner is None (use replay_arm) or an injected replacement, so the CLI's
          own wiring can be asserted without calling a model

    Ensures:
        - returns 0 on a completed replay
        - writes one JSON record per row per arm to --out
        - WITHHOLDS the per-arm summary when --denominator is unset, rather than
          printing a rate under a denominator nobody chose (F1)

    Raises:
        - whatever load_frozen_rows / replay_arm raise — a live path, a drifted
          snapshot, an unmeasurable row or a dead arm are all hard stops
    """
    parser = argparse.ArgumentParser( description="Paired DM-tutor replay for the Phi-4 vs Flash-Lite study" )
    parser.add_argument( "--snapshot-dir",          required=True )
    parser.add_argument( "--out",                   required=True, help="results jsonl" )
    parser.add_argument( "--max-model-failed-rate", required=True, type=float,
                         help="PRE-STATED ceiling; no default on purpose (F3)" )
    parser.add_argument( "--denominator",           default=None, choices=list( VALID_DENOMINATORS ),
                         help="Rick's open decision (row 76755526); unset until he rules (F1)" )
    parser.add_argument( "--preflight",             type=int, default=25 )
    parser.add_argument( "--limit",                 type=int, default=None )
    parser.add_argument( "--arm",                   default=None, choices=[ ARM_PHI4, ARM_FLASH_LITE ],
                         help="run one arm only; omit to run both" )
    args = parser.parse_args( argv )

    run = runner if runner is not None else replay_arm

    rows, manifest = load_frozen_rows( args.snapshot_dir )
    if args.limit is not None: rows = rows[ : args.limit ]
    printer( f"[replay] {len( rows )} frozen rows from {manifest[ 'snapshot_path' ]}" )
    printer( f"[replay] snapshot sha256 {manifest[ 'snapshot_sha256' ]}" )

    arms    = [ args.arm ] if args.arm else [ ARM_PHI4, ARM_FLASH_LITE ]
    results = {}
    for arm in arms:
        printer( f"[replay] arm '{arm}' -> {ARM_SPEC_KEYS[ arm ]}" )
        results[ arm ] = run(
            rows, arm, max_model_failed_rate=args.max_model_failed_rate, preflight=args.preflight
        )

    with open( args.out, "w", encoding="utf-8" ) as handle:
        for arm, records in results.items():
            for record in records:
                handle.write( json.dumps( record, ensure_ascii=False ) + "\n" )

    report = {
        "study"          : "phi4-vs-flash-lite",
        "ran_at_utc"     : datetime.datetime.now( datetime.timezone.utc ).isoformat(),
        "snapshot_sha256": manifest[ "snapshot_sha256" ],
        "rows"           : len( rows ),
        "arms"           : { arm: summarize_arm( [ r[ "meta" ] for r in recs ], denominator=args.denominator )
                             for arm, recs in results.items() } if args.denominator else
                           { arm: "summary withheld — --denominator unset (F1, Rick's row 76755526)"
                             for arm in results },
    }
    printer( json.dumps( report, indent=2, sort_keys=True, default=str ) )
    return 0


if __name__ == "__main__":                                                 # pragma: no cover
    sys.exit( main() )
