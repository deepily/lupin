#!/usr/bin/env python3
"""
Regenerate EVERY stored embedding from its own logged text (row 5e848dd8).

WHY
---
The embedding model changed on 2026-05-16 without a data migration. Rows written
before that date hold OpenAI ``text-embedding-3-small`` vectors; rows written
after hold local ``nomic-ai`` vectors. Both emit 768 dimensions, so nothing ever
failed loudly — the table is shape-compatible and scale-incompatible at once.

Measured on the live table 2026-08-02 (read-only survey):

    input_and_output        288,777 rows   (norm 1.0: 79,318 / norm 17-24: 209,468)
    prediction_decisions        500 rows   (norm 1.0:     30 / norm 17-24:     469)

EVERY ROW IS REGENERATED — not only the normalized ones (Rick, 2026-08-02).

An earlier draft of this script regenerated only the 79,318 norm-1.0 rows, on the
theory that the rest were "already correct." That was wrong, for a reason worth
writing down: **a norm measures whether a vector was normalized, not which model
produced it.** The norm band separates OpenAI from local only because those two
happen to differ in normalization. It cannot see any boundary INSIDE the local
era, where a model version, a training set, a service endpoint, or a prose/code
engine choice could have changed without moving the norm at all. Calling those
209,468 rows correct asserted a provenance the measurement never established.

The invariant that actually matters is that the whole table live in ONE space,
produced by ONE model, in ONE pass. Similarity is only meaningful between vectors
drawn from the same embedding space; a table assembled from two or more spaces
yields comparisons that are arithmetic without being meaning. Partial
regeneration leaves exactly that — and leaves it undetectable, which is how the
original defect survived two and a half months.

So the selection predicate is "has source text", NOT "looks stale". Every row
still has its text (verified: zero blank ``input``, zero blank ``output_final``),
so regeneration is fully grounded across the whole table.

SAFETY MODEL — read this before running anything
------------------------------------------------
Three separate commands, each of which must be asked for by name. Nothing here
overwrites a live vector column as a side effect of anything else:

    plan      READ-ONLY. Counts what is in scope and what it would cost. Default.
    fill      Writes ONLY to shadow columns, never to a live vector column.
    swap      The single destructive step. Refuses unless verification passes.

``--table-prefix`` points every statement at a clone (e.g. a probe schema), so
the whole pipeline can be exercised end to end without the live table being
addressed at all.

Run (from repo root, PYTHONPATH=src):
    python -m cosa.rest.db.embedding_regeneration plan
    python -m cosa.rest.db.embedding_regeneration plan --table-prefix=regen_probe.
    python -m cosa.rest.db.embedding_regeneration fill --table-prefix=regen_probe. --limit=500
    python -m cosa.rest.db.embedding_regeneration verify --table-prefix=regen_probe.
    python -m cosa.rest.db.embedding_regeneration swap --table-prefix=regen_probe.

Design authority: Rick's ruling 2026-08-02 (regenerate from logged text, shadow
column then swap, batched/resumable/dry-run, off-peak, refuse-if-busy).

Created: 2026-08-02 (Cheech 🌿) · row 5e848dd8
"""
import os
import sys
import json
from typing import Any, Dict, List, NamedTuple, Optional, Sequence


# --------------------------------------------------------------------------- #
# Constants. The norm bands are the model fingerprint — see module docstring for
# the measurements they come from.
# --------------------------------------------------------------------------- #
EMBEDDING_DIM = 768

# An L2-normalized vector reads as exactly 1.0; float error keeps it under this.
NORMALIZED_NORM_CEILING = 1.01

# The current local model's measured norm band, widened for headroom. A fresh
# vector outside this band means the model moved again and the run must stop.
LOCAL_NORM_FLOOR   = 5.0
LOCAL_NORM_CEILING = 60.0

# Count ceiling. Kept, but it is no longer the only bound — see DEFAULT_CHAR_BUDGET.
DEFAULT_BATCH_SIZE = 256

# Total characters allowed in one batch. Grounded in the 2026-08-02 measurements:
# 256 typical texts totalling 17,850 chars embed in 0.42s, while ~100k chars of
# the longest texts CUDA-OOM the shared GPU. 40,000 sits above the typical batch
# with headroom and well under the failure point. It is deliberately conservative
# — embedding is ~16 min of the run either way, so buying margin costs nothing
# that matters, and the GPU is shared with the rest of Lupin.
DEFAULT_CHAR_BUDGET = 40_000

# The adaptive budget's travel limits. The floor is small enough to survive the
# crowded-GPU case measured on 2026-08-02 (23 MiB free); the ceiling exists so a
# freshly-emptied card cannot tempt the run into one enormous batch whose failure
# would cost a long split-retry to unwind. Neither is a measurement — they are
# guard rails around the value the run discovers for itself.
MIN_CHAR_BUDGET = 5_000
MAX_CHAR_BUDGET = 2_000_000

# The hour the off-peak window CLOSES (EDT). Midnight is always the open.
#
# WAS 9, then 11. Rick, 2026-08-17: "You can update the clock to run for as long as
# we need it to. I am the human at the console. Nothing else will run or interfere.
# Let's not be too official on this — update the clock/gate so it's permissive and
# runs at my discretion."
#
# 24 means every hour is inside the window, i.e. the clock no longer refuses anyone.
# That is deliberate and it costs nothing, because the clock was never the real gate:
# should_proceed() still asks the live server whether work is in flight and still
# refuses on a busy box AND on an unknown answer. A clock cannot tell you the box is
# free; only the box can. What the clock was actually protecting was Rick's own
# interactive hours — and when Rick is the one at the keyboard asking for the run,
# there is nobody left for it to protect.
#
# The boundary is still a parameter: is_off_peak( hour, end_hour=N ) lets any caller
# reimpose a tighter window without editing this module.
OFF_PEAK_END_HOUR = 24


class RegenSpec( NamedTuple ):
    """One (table, text column → vector column) regeneration target."""
    label:         str
    table:         str
    pk:            str
    text_column:   str
    vector_column: str
    shadow_column: str
    content_type:  str


# Only columns whose text source is present and whose vectors are actually read.
# solution_snapshots / canonical_synonyms / question_embeddings / embedding_cache
# are all EMPTY as of 2026-08-02 (survey) — a fresh-start cache has nothing in it
# to regenerate, so they are deliberately absent rather than listed with a zero.
REGEN_SPECS: List[RegenSpec] = [
    RegenSpec( "io_input",   "input_and_output",     "id", "input",
               "input_embedding",        "input_embedding_regen",        "prose" ),
    RegenSpec( "io_output",  "input_and_output",     "id", "output_final",
               "output_final_embedding", "output_final_embedding_regen", "prose" ),
    RegenSpec( "decisions",  "prediction_decisions", "id", "question",
               "question_embedding",     "question_embedding_regen",     "prose" ),
]

# Rows that exist to be wrong. `clamp-001` ("non-unit vector", norm exactly 3.0)
# is a test fixture asserting the out-of-range clamp; regenerating it into a real
# vector would silently disarm whatever asserts on it.
EXCLUDED_IDS: Dict[str, frozenset] = {
    "prediction_decisions": frozenset( { "clamp-001" } ),
}


# --------------------------------------------------------------------------- #
# Pure core. No DB, no HTTP, no clock — every decision this script makes is
# reachable from a unit test with plain values.
# --------------------------------------------------------------------------- #
def classify_norm( norm: float ) -> str:
    """
    Classify a vector's L2 norm against the CURRENT model's measured band.

    This is a drift detector for freshly generated vectors, NOT a way to pick
    which rows to regenerate. A norm says whether a vector was normalized; it
    does not identify the model that produced it, and two different models can
    sit in the same band. Selection is by source text — see the module docstring.

    Requires:
        - norm is a non-negative float

    Ensures:
        - returns "normalized" for norm <= 1.01 — what the retired OpenAI model
          emitted, and what the current one must never emit
        - returns "current" for a norm inside the local model's measured band
        - returns "suspect" for anything else (including 0.0), which is neither
          a known producer nor safe to guess about
    """
    if norm <= NORMALIZED_NORM_CEILING:
        return "normalized"
    if LOCAL_NORM_FLOOR <= norm <= LOCAL_NORM_CEILING:
        return "current"
    return "suspect"


def l2_norm( vector: Sequence[float] ) -> float:
    """
    Compute the Euclidean norm of a vector.

    Requires:
        - vector is a sequence of numbers

    Ensures:
        - returns 0.0 for an empty vector
        - returns sqrt(sum(x*x)) otherwise
    """
    return sum( float( x ) * float( x ) for x in vector ) ** 0.5


def validate_fresh_vector( vector: Optional[Sequence[float]], *,
                           expected_dim: int = EMBEDDING_DIM ) -> Optional[str]:
    """
    Check a newly generated vector before it is allowed anywhere near the DB.

    Requires:
        - vector is a sequence of numbers, or None
        - expected_dim is a positive int

    Ensures:
        - returns None when the vector is usable
        - returns a human-readable reason string when it is not: missing, wrong
          dimension, non-finite, or carrying a norm outside the current model's
          band (which means the model changed again mid-run)
    """
    if vector is None:
        return "embedder returned nothing"
    if len( vector ) != expected_dim:
        return f"wrong dimension {len( vector )} (expected {expected_dim})"
    for value in vector:
        as_float = float( value )
        if as_float != as_float or as_float in ( float( "inf" ), float( "-inf" ) ):
            return "vector contains a non-finite value"
    norm = l2_norm( vector )
    verdict = classify_norm( norm )
    if verdict != "current":
        return f"fresh vector has norm {norm:.4f}, classified {verdict!r} — the embedding model may have changed again"
    return None


def is_excluded( table: str, row_id: Any ) -> bool:
    """
    True iff this row is a deliberate fixture that must keep its wrong vector.

    Requires:
        - table is a table name; row_id is the row's primary key value

    Ensures:
        - returns True only for ids registered in EXCLUDED_IDS for that table
    """
    return str( row_id ) in EXCLUDED_IDS.get( table, frozenset() )


def plan_batches( row_ids: Sequence[Any], batch_size: int = DEFAULT_BATCH_SIZE ) -> List[List[Any]]:
    """
    Split row ids into fixed-size batches.

    Requires:
        - row_ids is a sequence; batch_size is a positive int

    Ensures:
        - returns a list of batches, each at most batch_size long, preserving
          order and covering every id exactly once
        - returns [] for an empty input

    Raises:
        - ValueError if batch_size is not positive
    """
    if batch_size <= 0:
        raise ValueError( f"batch_size must be positive, got {batch_size}" )
    return [ list( row_ids[ i : i + batch_size ] ) for i in range( 0, len( row_ids ), batch_size ) ]


def plan_batches_by_budget( items: Sequence[Any], size_of, *,
                            char_budget: int = DEFAULT_CHAR_BUDGET,
                            max_count: int = DEFAULT_BATCH_SIZE ) -> List[List[Any]]:
    """
    Group items into batches bounded by BOTH a total size budget and a count.

    A fixed count is not a safe batch bound for embedding. Measured 2026-08-02:
    256 typical texts (17,850 chars total) embed fine, while EIGHT of the longest
    texts (~100k chars) return HTTP 500 — `torch.OutOfMemoryError` on a GPU whose
    23.65 GiB is already ~99% held by two other processes. Cost tracks total text,
    not row count, so the count alone lets the long tail through.

    Requires:
        - items is a sequence
        - size_of maps an item to its non-negative size (e.g. len of its text)
        - char_budget and max_count are positive ints

    Ensures:
        - returns batches preserving order and covering every item exactly once
        - no batch exceeds max_count items
        - no batch exceeds char_budget UNLESS it holds a single item that alone
          exceeds it — an oversized row is isolated rather than dropped, so the
          caller can decide, and it can never be silently merged with others
        - returns [] for an empty input

    Raises:
        - ValueError if char_budget or max_count is not positive
    """
    if char_budget <= 0:
        raise ValueError( f"char_budget must be positive, got {char_budget}" )
    if max_count <= 0:
        raise ValueError( f"max_count must be positive, got {max_count}" )

    batches: List[List[Any]] = []
    current: List[Any]       = []
    running                  = 0

    for item in items:
        size = size_of( item )
        if current and ( running + size > char_budget or len( current ) >= max_count ):
            batches.append( current )
            current, running = [], 0
        current.append( item )
        running += size

    if current:
        batches.append( current )
    return batches


class AdaptiveBudget:
    """
    A character budget that FINDS its own ceiling instead of being told one.

    Why this exists rather than a constant: DEFAULT_CHAR_BUDGET was calibrated
    against a GPU with 23 MiB free, because a 16.7 GiB vLLM instance was sharing
    it. Rick's point — the other models can be unloaded for this run — means that
    number describes a machine that will not exist when the run happens. Measured
    2026-08-02: GPU 0 is a 24,564 MiB card holding the model server (7,416 MiB)
    and one vLLM (16,754 MiB). Unloading the vLLM takes free memory from 23 MiB
    to roughly 17 GiB.

    But I only have ONE calibrated point — the crowded card. Scaling a budget
    from it by a made-up chars-per-MiB rate would be inventing the very
    measurement that is missing. So this grows EMPIRICALLY: start conservative,
    widen while batches succeed, halve when one is refused. The run discovers the
    real ceiling on the hardware it actually finds, whether or not anything was
    unloaded, and no constant has to be re-tuned by hand afterwards.

    Pairs with split_batch(): this sets the target size, that recovers the batch
    that overshot.
    """

    def __init__( self, start: int = DEFAULT_CHAR_BUDGET, *,
                  floor: int = MIN_CHAR_BUDGET, ceiling: int = MAX_CHAR_BUDGET,
                  growth: float = 1.5 ):
        """
        Requires:
            - floor <= start <= ceiling, all positive; growth > 1.0

        Ensures:
            - current() starts at start, clamped into [floor, ceiling]

        Raises:
            - ValueError if the bounds are inconsistent or growth is not > 1.0
        """
        if floor <= 0 or ceiling < floor:
            raise ValueError( f"need 0 < floor <= ceiling, got floor={floor} ceiling={ceiling}" )
        if growth <= 1.0:
            raise ValueError( f"growth must exceed 1.0, got {growth}" )
        self.floor    = floor
        self.ceiling  = ceiling
        self.growth   = growth
        self._current = max( floor, min( ceiling, start ) )

    def current( self ) -> int:
        """Ensures: returns the budget to use for the next batch."""
        return self._current

    def record_success( self ) -> int:
        """
        Widen the budget after a batch lands.

        Ensures:
            - the budget grows by the growth factor, never past ceiling
            - returns the new budget
        """
        self._current = min( self.ceiling, int( self._current * self.growth ) )
        return self._current

    def record_failure( self ) -> int:
        """
        Halve the budget after a batch is refused.

        Ensures:
            - the budget halves, never below floor
            - returns the new budget
            - is safe to call repeatedly; it converges on floor rather than 0
        """
        self._current = max( self.floor, self._current // 2 )
        return self._current


def split_batch( batch: Sequence[Any] ) -> List[List[Any]]:
    """
    Halve a batch that the embedder refused, for retry.

    The recovery half of the OOM story: a batch that fails is not evidence that
    any row in it is bad, only that the batch was too big for the memory free at
    that moment. Halving converges on the real culprit — or on success — in
    log2(n) attempts.

    Requires:
        - batch is a sequence

    Ensures:
        - returns [] for an empty batch
        - returns [] for a single-item batch — one item cannot be split, and the
          caller must treat that as a genuine per-row failure rather than retry
          forever
        - otherwise returns exactly two non-empty halves covering the batch in order
    """
    if len( batch ) <= 1:
        return []
    middle = len( batch ) // 2
    return [ list( batch[ :middle ] ), list( batch[ middle: ] ) ]


def is_off_peak( hour_edt: int, end_hour: int = OFF_PEAK_END_HOUR ) -> bool:
    """
    True iff an hour falls in the sanctioned batch window (midnight - end_hour EDT).

    Requires:
        - hour_edt is an int hour-of-day in 0..23, EDT
        - end_hour is an int hour-of-day in 1..24

    Ensures:
        - returns True for 0 <= hour_edt < end_hour, False otherwise
        - the default end_hour is OFF_PEAK_END_HOUR, so callers that do not care
          about the boundary never have to name it
    """
    return 0 <= hour_edt < end_hour


def should_proceed( *, busy: Optional[bool], hour_edt: Optional[int],
                    force: bool = False ) -> Optional[str]:
    """
    Decide whether a write pass may start right now.

    The queue check is the real gate; the clock is a courtesy. An UNKNOWN busy
    state (probe unreachable) blocks — the whole point of the check is that we
    do not guess about a server somebody else is using.

    Requires:
        - busy is True/False, or None when the probe could not answer
        - hour_edt is an int hour 0..23, or None to skip the clock check
        - force is a bool

    Ensures:
        - returns None when the pass may start
        - returns a refusal reason string otherwise
        - force=True bypasses the clock but NEVER the busy check
    """
    if busy is None:
        return "could not determine whether the server is busy — refusing to guess"
    if busy:
        return "server is busy (jobs in flight) — refusing to add embedding load"
    if not force and hour_edt is not None and not is_off_peak( hour_edt ):
        return ( f"hour {hour_edt:02d} EDT is outside the off-peak window "
                 f"(00:00-{OFF_PEAK_END_HOUR:02d}:00); pass --force to override" )
    return None


def summarize_verification( total: int, filled: int, bad_norms: int,
                            dim_mismatches: int ) -> Dict[str, Any]:
    """
    Turn raw shadow-column counts into a swap/no-swap verdict.

    Requires:
        - all four arguments are non-negative ints
        - filled <= total

    Ensures:
        - returns a dict with "ok" plus the reasons it is not ok
        - ok is True only when every in-scope row was filled and no vector failed
          its dimension or norm check
    """
    reasons: List[str] = []
    if filled != total:
        reasons.append( f"{total - filled} of {total} in-scope row(s) have no regenerated vector" )
    if bad_norms:
        reasons.append( f"{bad_norms} regenerated vector(s) carry an out-of-band norm" )
    if dim_mismatches:
        reasons.append( f"{dim_mismatches} regenerated vector(s) have the wrong dimension" )
    return {
        "ok"             : not reasons,
        "total"          : total,
        "filled"         : filled,
        "bad_norms"      : bad_norms,
        "dim_mismatches" : dim_mismatches,
        "reasons"        : reasons,
    }


def qualify( table: str, prefix: str = "" ) -> str:
    """
    Apply the table prefix that redirects every statement at a clone.

    Requires:
        - table is a bare table name
        - prefix is "" (live tables) or a schema prefix ending in "."

    Ensures:
        - returns prefix + table

    Raises:
        - ValueError if a non-empty prefix does not end in "."
    """
    if prefix and not prefix.endswith( "." ):
        raise ValueError( f"table prefix must end in '.', got {prefix!r}" )
    return f"{prefix}{table}"


# --------------------------------------------------------------------------- #
# Checkpoint — a resumable run remembers which batches already landed.
# --------------------------------------------------------------------------- #
def checkpoint_path( label: str, scratch_dir: str ) -> str:
    """
    Build the checkpoint file path for one spec.

    Requires:
        - label names a spec; scratch_dir is a directory path

    Ensures:
        - returns a path under scratch_dir named for the label
    """
    return os.path.join( scratch_dir, f"regen-checkpoint-{label}.json" )


def load_checkpoint( path: str ) -> Dict[str, Any]:
    """
    Read a checkpoint, tolerating absence.

    Requires:
        - path is a filesystem path

    Ensures:
        - returns {"done_ids": []} when the file does not exist
        - returns the parsed checkpoint otherwise, with "done_ids" guaranteed present

    Raises:
        - ValueError if the file exists but is not readable JSON (a corrupt
          checkpoint must not silently restart a 79,000-row run from zero)
    """
    if not os.path.exists( path ):
        return { "done_ids": [] }
    try:
        with open( path, "r" ) as handle:
            data = json.load( handle )
    except json.JSONDecodeError as error:
        raise ValueError( f"checkpoint {path} is corrupt: {error}" ) from error
    data.setdefault( "done_ids", [] )
    return data


def save_checkpoint( path: str, done_ids: Sequence[Any] ) -> None:
    """
    Write a checkpoint atomically.

    Requires:
        - path is writable; done_ids is a sequence of primary-key values

    Ensures:
        - the file at path holds {"done_ids": [...]} after this returns
        - a crash mid-write cannot leave a half-written checkpoint (temp + rename)
    """
    temp = f"{path}.tmp"
    with open( temp, "w" ) as handle:
        json.dump( { "done_ids": list( done_ids ) }, handle )
    os.replace( temp, path )


def remaining_ids( all_ids: Sequence[Any], done_ids: Sequence[Any] ) -> List[Any]:
    """
    Subtract already-completed ids from the work list, preserving order.

    Requires:
        - all_ids and done_ids are sequences of primary-key values

    Ensures:
        - returns the ids in all_ids that are not in done_ids, in original order
    """
    done = { str( row_id ) for row_id in done_ids }
    return [ row_id for row_id in all_ids if str( row_id ) not in done ]


# =========================================================================== #
# IO boundary — live DB, live embedder, argv. Excluded from coverage for the
# same reason vector_store_backfill._run is: it needs a real session, a real
# GPU-backed server, and a command line, none of which a unit test should touch.
# =========================================================================== #
# Selection is by SOURCE TEXT, not by vector norm. A norm cannot identify a
# producing model (see module docstring), so it must never decide what gets
# regenerated — every row with text is in scope, and the table ends up in one
# space by construction rather than by inference.
_TARGET_COUNT_SQL = """
SELECT count(*) FROM {table}
WHERE {text} IS NOT NULL AND btrim({text}) <> ''
"""

_TARGET_IDS_SQL = """
SELECT {pk} FROM {table}
WHERE {text} IS NOT NULL AND btrim({text}) <> ''
ORDER BY {pk}
"""

# Rows carrying text but NO vector are counted separately: regenerating them is
# a repair, not a replacement, and the two should not be silently pooled.
_MISSING_VECTOR_SQL = """
SELECT count(*) FROM {table}
WHERE {vector} IS NULL AND {text} IS NOT NULL AND btrim({text}) <> ''
"""

# Rows with a vector but NO usable text cannot be regenerated at all. Live count
# is zero today; it is reported anyway so a future non-zero is loud, not silent.
_ORPHAN_VECTOR_SQL = """
SELECT count(*) FROM {table}
WHERE {vector} IS NOT NULL AND ({text} IS NULL OR btrim({text}) = '')
"""


def _probe_busy( url=None ):   # pragma: no cover - live HTTP boundary
    """Ask the server whether work is in flight. Returns True/False, or None if unreachable."""
    import urllib.request

    url = url or os.environ.get( "BOUNCE_BUSY_URL", "http://localhost:7999/api/busy" )
    try:
        with urllib.request.urlopen( url, timeout=3 ) as response:
            payload = json.loads( response.read().decode( "utf-8" ) )
        return bool( payload.get( "inflight_agentic_jobs", 0 ) or payload.get( "run_queue_size", 0 ) )
    except Exception as error:
        print( f"  busy probe unreachable ({type( error ).__name__}: {error})" )
        return None


def _plan( session, prefix="" ):   # pragma: no cover - live DB boundary
    """Count what would be regenerated per spec. Issues SELECTs only."""
    from sqlalchemy import text as sql_text

    grand_total = 0
    print( f"{'spec':12} {'table':22} {'to regen':>12} {'missing vec':>12} {'no text':>9}" )
    for spec in REGEN_SPECS:
        table   = qualify( spec.table, prefix )
        fields  = { "table": table, "text": spec.text_column, "vector": spec.vector_column }
        count   = session.execute( sql_text( _TARGET_COUNT_SQL.format( **fields ) ) ).scalar()
        missing = session.execute( sql_text( _MISSING_VECTOR_SQL.format( **fields ) ) ).scalar()
        orphan  = session.execute( sql_text( _ORPHAN_VECTOR_SQL.format( **fields ) ) ).scalar()
        grand_total += count
        print( f"{spec.label:12} {table:22} {count:>12,} {missing:>12,} {orphan:>9,}" )
        if orphan:
            print( f"             ^ {orphan:,} row(s) have a vector but no text — NOT regenerable, left as-is" )
    print( f"{'TOTAL':12} {'':22} {grand_total:>12,} embedding call(s)" )
    return grand_total


def _embed_with_split_retry( provider, rows, content_type, depth=0, budget=None ):   # pragma: no cover - live embedder boundary
    """
    Embed (id, text) rows, halving the batch on failure until it fits or is one row.

    A batch that 500s is not evidence that any row in it is bad — it is evidence
    the batch was too big for the GPU memory free at that instant. Halving
    separates those two cases instead of failing all of them together.

    Returns [ ( row_id, vector_or_None ), ... ]; a None means that single row
    genuinely could not be embedded on its own.

    A TRANSPORT failure is not split. `EmbeddingProviderUnreachable` means the
    service is not answering at all — the provider already spent every retry it
    has before raising — so a smaller batch would fail on the same dead socket.
    Splitting there turns one dead dependency into one doomed retry per row and
    burns the entire run producing nothing (bug 13b35b37). It propagates instead,
    which stops the run loudly and immediately.
    """
    from cosa.memory.embedding_provider import EmbeddingProviderUnreachable

    try:
        vectors = provider.generate_embeddings_batch( [ r[ 1 ] for r in rows ], content_type=content_type )
        if budget is not None and depth == 0: budget.record_success()
        return list( zip( [ r[ 0 ] for r in rows ], vectors ) )
    except EmbeddingProviderUnreachable:
        # Deliberately NOT recorded as a batch-size failure: the budget's job is to
        # learn how big a batch the GPU tolerates, and a dead server teaches it nothing.
        raise
    except Exception as error:
        if budget is not None: budget.record_failure()
        halves = split_batch( rows )
        if not halves:
            print( f"    single row {rows[ 0 ][ 0 ]} failed to embed alone: {type( error ).__name__}: {str( error )[ :90 ]}" )
            return [ ( rows[ 0 ][ 0 ], None ) ]
        print( f"    batch of {len( rows )} failed ({type( error ).__name__}) — splitting" )
        out = []
        for half in halves:
            out.extend( _embed_with_split_retry( provider, half, content_type, depth + 1, budget ) )
        return out


def _fill( session, spec, provider, prefix="", batch_size=DEFAULT_BATCH_SIZE,
           char_budget=DEFAULT_CHAR_BUDGET, limit=None, scratch_dir="/tmp",
           apply=False ):   # pragma: no cover - live DB + embedder boundary
    """Regenerate one spec's vectors into its SHADOW column. Never writes the live column."""
    from sqlalchemy import text as sql_text

    table = qualify( spec.table, prefix )
    rows  = session.execute( sql_text( _TARGET_IDS_SQL.format(
        table=table, pk=spec.pk, text=spec.text_column ) ) ).all()

    ids  = [ row[ 0 ] for row in rows if not is_excluded( spec.table, row[ 0 ] ) ]
    path = checkpoint_path( spec.label, scratch_dir )
    ids  = remaining_ids( ids, load_checkpoint( path )[ "done_ids" ] )
    if limit is not None:
        ids = ids[ :limit ]

    print( f"  {spec.label}: {len( ids ):,} row(s) to regenerate into {spec.shadow_column}" )
    if not apply:
        print( f"  {spec.label}: [DRY-RUN] no writes." )
        return { "planned": len( ids ), "written": 0, "rejected": 0 }

    done, written, rejected = list( load_checkpoint( path )[ "done_ids" ] ), 0, 0

    # The budget FINDS its ceiling on whatever GPU this actually runs on — the
    # starting value describes the crowded card measured on 2026-08-02, not the
    # cleared one Rick intends to run against.
    budget = AdaptiveBudget( start=char_budget )

    # Batch by ID first only to bound the SELECT; the embedder batch is re-planned
    # by CHARACTER BUDGET once the texts are in hand, because that is what the GPU
    # actually costs (see plan_batches_by_budget).
    for id_chunk in plan_batches( ids, batch_size * 4 ):
        fetched = session.execute( sql_text(
            f"SELECT {spec.pk}, {spec.text_column} FROM {table} WHERE {spec.pk} = ANY(:ids)"
        ), { "ids": id_chunk } ).all()

        for batch in plan_batches_by_budget(
            [ ( row[ 0 ], row[ 1 ] ) for row in fetched ],
            size_of     = lambda pair: len( pair[ 1 ] or "" ),
            char_budget = budget.current(),
            max_count   = batch_size,
        ):
            for row_id, vector in _embed_with_split_retry( provider, batch, spec.content_type, budget=budget ):
                reason = "embedder failed on this row alone" if vector is None else validate_fresh_vector( vector )
                if reason:
                    print( f"    REJECTED {spec.pk}={row_id}: {reason}" )
                    rejected += 1
                    continue
                session.execute( sql_text(
                    f"UPDATE {table} SET {spec.shadow_column} = :vec WHERE {spec.pk} = :id"
                ), { "vec": str( list( vector ) ), "id": row_id } )
                written += 1
                done.append( row_id )

        session.commit()
        save_checkpoint( path, done )
        print( f"    {written:,} written / {rejected:,} rejected", end="\r" )

    print( f"\n  {spec.label}: {written:,} written, {rejected:,} rejected, final char budget {budget.current():,}" )
    return { "planned": len( ids ), "written": written, "rejected": rejected }


def _verify( session, spec, prefix="" ):   # pragma: no cover - live DB boundary
    """Compare shadow coverage against scope, read-only, and return the swap verdict."""
    from sqlalchemy import text as sql_text

    # Denominator is every row with source text — the same predicate `fill` used.
    # Counting only the norm-1.0 rows here would let a partial run verify clean.
    table = qualify( spec.table, prefix )
    row = session.execute( sql_text( f"""
        SELECT count(*),
               count(*) FILTER (WHERE {spec.shadow_column} IS NOT NULL),
               count(*) FILTER (WHERE {spec.shadow_column} IS NOT NULL
                            AND sqrt(({spec.shadow_column} <#> {spec.shadow_column}) * -1) NOT BETWEEN {LOCAL_NORM_FLOOR} AND {LOCAL_NORM_CEILING}),
               count(*) FILTER (WHERE {spec.shadow_column} IS NOT NULL
                            AND vector_dims({spec.shadow_column}) <> {EMBEDDING_DIM})
        FROM {table}
        WHERE {spec.text_column} IS NOT NULL AND btrim({spec.text_column}) <> ''
    """ ) ).one()

    report = summarize_verification( total=row[ 0 ], filled=row[ 1 ], bad_norms=row[ 2 ], dim_mismatches=row[ 3 ] )
    status = "OK" if report[ "ok" ] else "BLOCKED"
    print( f"  {spec.label}: {status} — in_scope={report['total']:,} filled={report['filled']:,} "
           f"bad_norm={report['bad_norms']:,} bad_dim={report['dim_mismatches']:,}" )
    for reason in report[ "reasons" ]:
        print( f"      {reason}" )
    return report


def _swap( session, spec, prefix="", apply=False ):   # pragma: no cover - live DB boundary
    """THE destructive step: shadow overwrites live, gated on a clean verify."""
    from sqlalchemy import text as sql_text

    report = _verify( session, spec, prefix )
    if not report[ "ok" ]:
        print( f"  {spec.label}: refusing to swap — verification did not pass." )
        return 1
    if not apply:
        print( f"  {spec.label}: [DRY-RUN] would swap {report['filled']:,} vector(s)." )
        return 0

    table = qualify( spec.table, prefix )
    result = session.execute( sql_text(
        f"UPDATE {table} SET {spec.vector_column} = {spec.shadow_column} WHERE {spec.shadow_column} IS NOT NULL"
    ) )
    session.commit()
    print( f"  {spec.label}: swapped {result.rowcount:,} vector(s)." )
    return 0


def _run( command="plan", prefix="", apply=False, force=False, limit=None,
          batch_size=DEFAULT_BATCH_SIZE, char_budget=DEFAULT_CHAR_BUDGET,
          only=None ):   # pragma: no cover - CLI/DB/HTTP boundary
    """Open a session, dispatch the subcommand, print a report. Returns exit code."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from cosa.rest.db.database import get_db

    specs = [ spec for spec in REGEN_SPECS if only is None or spec.label == only ]
    if not specs:
        print( f"no spec matches --only={only!r}; valid: {[ s.label for s in REGEN_SPECS ]}" )
        return 1

    target = prefix or "LIVE TABLES"
    print( f"embedding_regeneration [{command.upper()}] target={target} apply={apply}" )

    with get_db() as session:
        if command == "plan":
            _plan( session, prefix )
            return 0

        if command == "verify":
            return 0 if all( _verify( session, spec, prefix )[ "ok" ] for spec in specs ) else 1

        if command == "fill":
            refusal = should_proceed(
                busy     = _probe_busy(),
                hour_edt = datetime.now( ZoneInfo( "America/New_York" ) ).hour,
                force    = force,
            )
            if refusal:
                print( f"  REFUSING: {refusal}" )
                return 1
            from cosa.memory.embedding_provider import ( get_embedding_provider,
                                                          EmbeddingProviderUnreachable )
            provider = get_embedding_provider()
            try:
                for spec in specs:
                    _fill( session, spec, provider, prefix=prefix, batch_size=batch_size,
                           char_budget=char_budget, limit=limit, apply=apply )
            except EmbeddingProviderUnreachable as error:
                # One loud stop beats 703,471 identical failures. Whatever committed
                # before this point stays committed — fill is resumable from its
                # checkpoint, so the remedy is "fix the server, run again".
                print( f"  ABORTING: the embedding service is not reachable.\n    {error}" )
                print(  "    Nothing further was attempted. Fix the service, then re-run —"
                        " completed batches are checkpointed and will not be redone." )
                return 1
            return 0

        if command == "swap":
            return max( _swap( session, spec, prefix, apply ) for spec in specs )

    print( f"unknown command {command!r}; valid: plan / fill / verify / swap" )
    return 1


if __name__ == "__main__":   # pragma: no cover - CLI entry
    argv    = sys.argv[ 1: ]
    command = argv[ 0 ] if argv and not argv[ 0 ].startswith( "-" ) else "plan"

    def _opt( name, cast=str, default=None ):
        for token in argv:
            if token.startswith( f"--{name}=" ):
                return cast( token.split( "=", 1 )[ 1 ] )
        return default

    sys.exit( _run(
        command    = command,
        prefix     = _opt( "table-prefix", default="" ),
        apply      = ( "--apply" in argv ),
        force      = ( "--force" in argv ),
        limit      = _opt( "limit", int ),
        batch_size  = _opt( "batch-size", int, DEFAULT_BATCH_SIZE ),
        char_budget = _opt( "char-budget", int, DEFAULT_CHAR_BUDGET ),
        only        = _opt( "only" ),
    ) )
