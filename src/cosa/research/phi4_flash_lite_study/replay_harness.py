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
        --max-model-failed-rate 0.05 --preflight 25 \
        [--sample-size N --seed S] [--arm phi_4|flash_lite]

⚠️ To bound a run's cost, use `--sample-size` (a seeded random draw), NOT `--limit`.
The frozen set is in corpus order, so the first N rows are a TIME-WINDOW sample —
whatever the fleet happened to be saying that afternoon — and that is a caveat every
number coming off the run has to carry.
"""

import os
import sys
import json
import math
import time
import random
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


# ⚠️ ONE DEFINITION FOR THE WHOLE PACKAGE. Sam 🎙️ and I independently implemented
# p90/p99 in different modules with DIFFERENT METHODS — nearest-rank in `report.py`,
# linear interpolation here. On the same 8 rows that gave flash_lite a p90 of 24.524
# from one and 14.225 from the other, which is two components disagreeing about the
# same data and would have cost the first reader an hour. `report.py` now imports
# this function, so there is one implementation and this constant is the only place
# the choice lives.
#
# NEAREST-RANK IS THE DEFAULT, and the reason is Sam's: every number printed is one
# a request actually took. Interpolation invents a value between two observations,
# and a study about a model inventing facts should not report a latency nothing
# measured. Linear matches numpy's default and is the better estimator at large n —
# it is one word away, below.
#
# 🔴 Mr. Radio's ruling stands above this line. Flipping it is a one-word change
# here, not a rewrite in two modules.
PERCENTILE_METHOD = "nearest_rank"        # or "linear"


def _percentile( sorted_values, q, method=None ):
    """
    The q-th percentile of an already-sorted list.

    ⚠️ A p99 OVER A SMALL SAMPLE IS NEARLY THE MAXIMUM. With n observations there are
    only n distinct values, so at n=8 the "p99" IS the slowest row. That is not wrong,
    but it is not a tail estimate either — say so rather than implying a resolution the
    sample does not have. The number is still reported, because hiding it would hide
    the very tail Rick asked to see.

    Requires:
        - sorted_values is sorted ascending
        - 0 <= q <= 1
        - method is "nearest_rank", "linear", or None to use PERCENTILE_METHOD

    Ensures:
        - returns None for an empty list rather than raising
        - "nearest_rank" returns a value that was ACTUALLY MEASURED — the element at
          ceil( q * n ), never an interpolated one
        - "linear" interpolates between neighbours, matching numpy's default

    Raises:
        - ValueError on an unknown method, rather than silently picking one
    """
    chosen = method if method is not None else PERCENTILE_METHOD
    if chosen not in ( "nearest_rank", "linear" ):
        raise ValueError( f"percentile method must be 'nearest_rank' or 'linear', got {chosen!r}" )

    n = len( sorted_values )
    if n == 0: return None
    if n == 1: return sorted_values[ 0 ]

    if chosen == "nearest_rank":
        return sorted_values[ max( 1, math.ceil( q * n ) ) - 1 ]

    position = q * ( n - 1 )
    lower    = int( position )
    upper    = min( lower + 1, n - 1 )
    fraction = position - lower
    return sorted_values[ lower ] + ( sorted_values[ upper ] - sorted_values[ lower ] ) * fraction


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
                verify_surface=True, snapshot_sha256=None ):
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
            # Where this row sits in the FROZEN SET, when the run sampled from it.
            # row_index is the position in the replayed list; on a seeded subset the
            # two differ, and only this one traces back to the snapshot.
            "frozen_index"   : row.get( "frozen_index", index ),
            # Which freeze these indices index into. Matching frozen indices across
            # two DIFFERENT snapshots is not a pairing; pair_records refuses that.
            "snapshot_sha256": snapshot_sha256,
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


def draw_seeded_subset( rows, sample_size, seed ):
    """
    Draw a reproducible random subset of the frozen set, keeping each row's origin.

    ⚠️ WHY `--limit` IS NOT THIS. `--limit N` takes the FIRST N rows, and the frozen
    set is in corpus order — so it is a TIME-WINDOW sample: whatever the fleet
    happened to be saying that afternoon, not a sample of the study's population.
    That is a caveat every number coming off it has to carry. A seeded draw does not
    need the caveat, and costs one line. (Sam 🎙️ raised this mid-run.)

    The official snapshot stays the one frozen set: this samples FROM it rather than
    re-freezing, so the manifest checksum still describes the population.

    Requires:
        - rows is the loaded frozen set
        - sample_size is a positive int
        - seed is an int, recorded by the caller alongside the results

    Ensures:
        - returns ( subset, drawn_indices ) with drawn_indices sorted ascending and
          indexing into the ORIGINAL frozen set
        - the subset is in frozen-set order, so both arms walk it identically
        - each returned row is a COPY carrying `frozen_index`, so a record can be
          traced back to its row in the snapshot rather than only to its position
          in the draw
        - same rows + same size + same seed gives the same draw on any machine
        - returns every row when sample_size >= len( rows )
        - never mutates the input rows

    Raises:
        - ValueError if sample_size is not positive
    """
    if sample_size <= 0:
        raise ValueError( f"sample_size must be positive, got {sample_size}" )

    if sample_size >= len( rows ):
        drawn = list( range( len( rows ) ) )
    else:
        drawn = sorted( random.Random( seed ).sample( range( len( rows ) ), sample_size ) )

    return [ dict( rows[ i ], frozen_index=i ) for i in drawn ], drawn


def pair_records( arm_a_records, arm_b_records ):
    """
    Join the two arms on FROZEN INDEX so every comparison is within one body.

    ⚠️ WHY NOT `row_index`. `row_index` is the position in the DRAW. Two different
    draws of the same size both produce 0..N-1, so joining on it makes the guard
    below pass while the function pairs DIFFERENT BODIES — the arms would look
    perfectly paired and every McNemar cell would compare two populations. That is
    the exact failure the freeze exists to prevent, and it is reachable without
    anyone doing anything odd: `--arm` runs one arm at a time, `--seed` has a
    default, and a re-freeze between two invocations changes the population.
    `frozen_index` indexes the SNAPSHOT, so it is the only key that means "the same
    body". (Tiffany 💍 found this by running it, not reading it.)

    ⚠️ THE SNAPSHOT CHECK IS THE OTHER HALF. Matching frozen indices across two
    DIFFERENT snapshots is still not a pairing — index 25 of one freeze is not
    index 25 of another. Each record carries the snapshot's sha256, and a mismatch
    is refused. The old docstring asked for "both lists came from the SAME frozen
    snapshot" as a precondition nothing checked; now it is enforced.

    Requires:
        - both lists came from `replay_arm`, so every record carries frozen_index
          and snapshot_sha256

    Ensures:
        - returns a list of { row_index, frozen_index, body, <arm_a>, <arm_b> } dicts
        - RAISES rather than silently truncating when the arms disagree about which
          rows they saw, or about which snapshot those rows came from — a zip()
          would hide both

    Raises:
        - ValueError when the arms' frozen indices differ, or when the two arms
          were replayed against different snapshots
    """
    a_snapshot = { r[ "snapshot_sha256" ] for r in arm_a_records }
    b_snapshot = { r[ "snapshot_sha256" ] for r in arm_b_records }
    if a_snapshot != b_snapshot:
        raise ValueError(
            f"the two arms were replayed against different frozen snapshots "
            f"({sorted( a_snapshot )} vs {sorted( b_snapshot )}). Row 25 of one freeze is not "
            f"row 25 of another, so matching indices would not mean matching bodies."
        )

    a_index = [ r[ "frozen_index" ] for r in arm_a_records ]
    b_index = [ r[ "frozen_index" ] for r in arm_b_records ]
    if a_index != b_index:
        raise ValueError(
            f"the two arms did not see the same rows: {len( a_index )} vs {len( b_index )} records, "
            f"frozen indices differ. They are not paired, so no per-body comparison is valid."
        )

    paired = []
    for rec_a, rec_b in zip( arm_a_records, arm_b_records ):
        # Belt to the index check's braces: the indices agreeing is the argument that
        # the bodies agree, so assert the conclusion rather than trusting the premise.
        if rec_a[ "body" ] != rec_b[ "body" ]:
            raise ValueError(
                f"frozen index {rec_a[ 'frozen_index' ]} holds different bodies in the two arms. "
                f"The join key agreed and the content did not, which means the records did not "
                f"come from the snapshot they claim."
            )
        paired.append( {
            "row_index"          : rec_a[ "row_index" ],
            "frozen_index"       : rec_a[ "frozen_index" ],
            "body"               : rec_a[ "body" ],
            rec_a[ "arm" ]       : rec_a,
            rec_b[ "arm" ]       : rec_b,
        } )
    return paired


def backfill_provenance( records, snapshot_sha256, drawn_frozen_indices=None ):
    """
    Stamp snapshot + frozen-index provenance onto records written before those fields existed.

    ⚠️ WHY THIS IS NARROW ON PURPOSE. `pair_records` refuses records that do not carry
    `snapshot_sha256` and `frozen_index`, and that refusal is the guard against joining
    two different draws. A backfill therefore weakens the guard by exactly as much as it
    is trusted, so it takes the provenance from the RUN HEADER — which the run itself
    wrote — and never invents it. Sam 🎙️'s 400-row run predates both fields; its header
    carries `snapshot_sha256` and the drawn indices, so nothing here is guessed.

    Requires:
        - records are one arm's rows, IN THE ORDER THE ARM REPLAYED THEM
        - snapshot_sha256 comes from the run's own header, not from a later freeze
        - drawn_frozen_indices, when given, is that run's header list and has exactly
          one entry per record

    Ensures:
        - returns NEW dicts; the caller's records are not mutated
        - a record that already carries a field keeps its own value — a backfill never
          overwrites real provenance with reconstructed provenance
        - without drawn_frozen_indices, frozen_index falls back to row_index, which is
          correct ONLY for an unsampled full-population run

    Raises:
        - ValueError when drawn_frozen_indices is given and its length does not match
          the record count, since a silent zip would misattribute every row
    """
    if drawn_frozen_indices is not None and len( drawn_frozen_indices ) != len( records ):
        raise ValueError(
            f"{len( drawn_frozen_indices )} drawn indices for {len( records )} records — these "
            f"cannot be the same run, and pairing them would misattribute every row."
        )

    filled = []
    for position, record in enumerate( records ):
        stamped = dict( record )
        stamped.setdefault( "snapshot_sha256", snapshot_sha256 )
        if "frozen_index" not in stamped:
            stamped[ "frozen_index" ] = ( drawn_frozen_indices[ position ]
                                          if drawn_frozen_indices is not None
                                          else stamped[ "row_index" ] )
        stamped[ "provenance_backfilled" ] = True
        filled.append( stamped )
    return filled


def latency_summary( records ):
    """
    Per-arm latency, split by whether the model actually answered.

    ⚠️ THE SPLIT IS THE POINT. `elapsed_seconds` times the WHOLE `_apply_dm_tutor`
    call, so a `model_failed` row is timed too — and its duration is a different
    KIND of thing: a fast 404 or a slow timeout, not "how long the model took to
    answer". Pooling those into one median makes the number mean something other
    than which model is faster, which is exactly what a tiebreaker must not do.

    `answered` is therefore the tiebreaker figure: rows where a rewrite came back
    and the tutor then judged it (delivered, or refused for fabricating/rescoping/
    mislabelling — all of which required an answer to judge). `all_fired` is
    reported beside it so a big gap between the two is visible rather than hidden.

    Requires:
        - records came from `replay_arm`, so each carries elapsed_seconds and meta

    Ensures:
        - returns { answered: {...}, all_fired: {...} }, each with n / median / mean
        - a median of None where no row qualifies, never a 0.0 that reads as "fast"

    Raises:
        - nothing
    """
    answered_outcomes = ( "rewritten", "fabrication_blocked", "rescope_blocked",
                          "label_blocked", "gate_rejected" )

    def stats( subset ):
        times = sorted( r[ "elapsed_seconds" ] for r in subset )
        return {
            "n"      : len( times ),
            "median" : _median( times ),
            "mean"   : ( sum( times ) / len( times ) ) if times else None,
            # Rick's condition: p90 AND p99. The internet leg is the variable one and
            # p99 is where it shows — a median hides exactly the tail that decides
            # whether a deployment is pleasant to use.
            "p90"    : _percentile( times, 0.90 ),
            "p99"    : _percentile( times, 0.99 ),
        }

    return {
        "answered"  : stats( [ r for r in records
                               if r[ "meta" ].get( "tutor_outcome" ) in answered_outcomes ] ),
        "all_fired" : stats( records ),
    }


def latency_ratio( arm_a_records, arm_b_records, arm_a="phi_4", arm_b="flash_lite" ):
    """
    The tiebreaker: how much slower arm A is than arm B.

    ⚠️ A TIEBREAKER ONLY APPLIES AFTER THE TEST COMES BACK TIED. Statistics are
    considered first; this decides nothing on its own, and a faster arm that is
    significantly less honest does not win on speed.

    Two figures, because they answer slightly different questions:
      · `ratio_of_medians` — the headline. What a reader means by "latency ratio".
      · `paired_median_ratio` — the median of per-row A/B ratios. The arms are
        paired, so this is available and is robust to one arm meeting a few very
        slow bodies. Report it beside the headline rather than instead of it.

    Requires:
        - both lists are PAIRED (same frozen indices, same order) — pass them
          through `pair_records` first if that is not already established

    Ensures:
        - returns per-arm summaries plus both ratios, and names which arm is faster
        - `> 1` means arm A took longer; `< 1` means arm B did
        - a ratio of None where it cannot be formed (no qualifying rows, or a zero
          denominator), never a fabricated number

    Raises:
        - nothing
    """
    a_summary = latency_summary( arm_a_records )
    b_summary = latency_summary( arm_b_records )

    a_median = a_summary[ "answered" ][ "median" ]
    b_median = b_summary[ "answered" ][ "median" ]

    ratio_of_medians = ( a_median / b_median ) if a_median is not None and b_median else None

    per_row = sorted(
        rec_a[ "elapsed_seconds" ] / rec_b[ "elapsed_seconds" ]
        for rec_a, rec_b in zip( arm_a_records, arm_b_records )
        if rec_b[ "elapsed_seconds" ]
    )

    faster = None
    if ratio_of_medians is not None:
        faster = arm_b if ratio_of_medians > 1 else arm_a if ratio_of_medians < 1 else "tie"

    return {
        # Rick's condition 1, in the PAYLOAD and not only in the doc — a caveat that
        # lives somewhere the number does not travel to is a caveat nobody reads.
        "comparison_kind"    : "DEPLOYMENT, not model speed",
        "what_this_measures" : (
            f"end-to-end time as each arm WOULD BE DEPLOYED: {arm_a} over the LAN hop to the "
            f"local vLLM host, {arm_b} over the internet round trip to Vertex. Both were "
            f"measured exactly as they would run in production, which is what makes the "
            f"comparison fair — and what makes it a statement about two deployments, NOT a "
            f"claim that one model is intrinsically faster than the other. Move either arm to "
            f"different infrastructure and this number no longer applies."
        ),
        "basis"              : "answered rows only — model_failed timings are a different kind of number",
        "tiebreaker_only"    : "applies ONLY after the statistical test comes back tied",
        arm_a                : a_summary,
        arm_b                : b_summary,
        "ratio_of_medians"   : ratio_of_medians,
        "ratio_meaning"      : f"{arm_a} median / {arm_b} median; > 1 means {arm_a} is slower",
        "paired_median_ratio": _median( per_row ),
        "faster_arm"         : faster,
        "tail_note"          : (
            "p99 over a small sample is close to the maximum, not a tail estimate. The "
            "internet leg is the variable one, so the p90/p99 gap between the arms is where "
            "a deployment difference shows."
        ),
    }


def discordant_counts( paired, arm_a, arm_b, outcome="fabrication_blocked" ):
    """
    The b / c cells McNemar's test reads, over paired rows.

    Requires:
        - paired came from pair_records
        - both arm names are keys in every paired entry

    ⚠️ RETURNS A SELF-DESCRIBING DICT, NOT A BARE ( b, c ) TUPLE. Sam 🎙️ and I label
    the two cells in OPPOSITE orders — my b=0, c=5 is his b=5, c=0 for the same data —
    so a bare tuple travels without the one fact that makes it readable, and the first
    person to quote it gets the direction backwards. The arm-named keys carry the
    meaning with the number; `b` and `c` remain for the arithmetic.

    Requires:
        - paired came from pair_records
        - both arm names are keys in every paired entry

    Ensures:
        - returns a dict whose keys NAME the arm each count belongs to
        - `b` = rows where ONLY arm_a hit the outcome; `c` = only arm_b — kept for
          McNemar, which needs an order, and spelled out in `b_means` / `c_means`
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

    return {
        "outcome"            : outcome,
        f"only_{arm_a}"      : b,
        f"only_{arm_b}"      : c,
        "b"                  : b,
        "c"                  : c,
        "b_means"            : f"rows where ONLY {arm_a} hit {outcome}",
        "c_means"            : f"rows where ONLY {arm_b} hit {outcome}",
        "n_discordant"       : b + c,
        "n_concordant"       : len( paired ) - b - c,
        "direction"          : ( f"favours {arm_b}" if c > b else
                                 f"favours {arm_a}" if b > c else "even" ),
    }


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
    parser.add_argument( "--sample-size",           type=int, default=None,
                         help="replay a SEEDED RANDOM subset of the frozen set — the "
                              "statistically defensible way to bound a run's cost" )
    parser.add_argument( "--seed",                  type=int, default=20260817,
                         help="seed for --sample-size; recorded in the run header" )
    parser.add_argument( "--limit",                 type=int, default=None,
                         help="take the FIRST N rows. The frozen set is in corpus order, so "
                              "this is a TIME-WINDOW sample, not a sample of the population — "
                              "fine for a smoke, a caveat on every number otherwise. Prefer "
                              "--sample-size" )
    parser.add_argument( "--arm",                   default=None, choices=[ ARM_PHI4, ARM_FLASH_LITE ],
                         help="run one arm only; omit to run both" )
    args = parser.parse_args( argv )

    run = runner if runner is not None else replay_arm

    if args.sample_size is not None and args.limit is not None:
        parser.error( "--sample-size and --limit both select rows; pass one. --sample-size draws "
                      "at random from the whole frozen set, --limit takes the first N in corpus "
                      "order (a time-window sample)." )

    rows, manifest = load_frozen_rows( args.snapshot_dir )
    population     = len( rows )
    selection      = { "mode": "all", "population": population }

    if args.sample_size is not None:
        rows, drawn = draw_seeded_subset( rows, args.sample_size, args.seed )
        selection   = { "mode": "seeded_random", "population": population, "sample_size": len( rows ),
                        "seed": args.seed, "drawn_frozen_indices": drawn }
    elif args.limit is not None:
        rows      = rows[ : args.limit ]
        selection = { "mode": "first_n_corpus_order", "population": population, "limit": args.limit,
                      "caveat": "TIME-WINDOW sample, not a sample of the population" }

    printer( f"[replay] {len( rows )} of {population} frozen rows from {manifest[ 'snapshot_path' ]}" )
    printer( f"[replay] snapshot sha256 {manifest[ 'snapshot_sha256' ]}" )
    printer( f"[replay] selection {selection[ 'mode' ]}" )

    arms    = [ args.arm ] if args.arm else [ ARM_PHI4, ARM_FLASH_LITE ]
    results = {}
    for arm in arms:
        printer( f"[replay] arm '{arm}' -> {ARM_SPEC_KEYS[ arm ]}" )
        results[ arm ] = run(
            rows, arm, max_model_failed_rate=args.max_model_failed_rate, preflight=args.preflight,
            snapshot_sha256=manifest[ "snapshot_sha256" ]
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
        "selection"      : selection,
        # Reported on EVERY run, unlike the per-arm summaries: latency needs neither
        # Rick's denominator nor his floor, so withholding it would withhold a number
        # nothing is waiting on. It is a TIEBREAKER — it decides nothing until the
        # statistical test comes back tied.
        "latency"        : ( latency_ratio( results[ ARM_PHI4 ], results[ ARM_FLASH_LITE ] )
                             if len( results ) == 2 else
                             { arm: latency_summary( recs ) for arm, recs in results.items() } |
                             { "note": "one arm only — no ratio; a tiebreaker needs both arms" } ),
        "arms"           : { arm: summarize_arm( [ r[ "meta" ] for r in recs ], denominator=args.denominator )
                             for arm, recs in results.items() } if args.denominator else
                           { arm: "summary withheld — --denominator unset (F1, Rick's row 76755526)"
                             for arm in results },
    }
    printer( json.dumps( report, indent=2, sort_keys=True, default=str ) )
    return 0


if __name__ == "__main__":                                                 # pragma: no cover
    sys.exit( main() )
