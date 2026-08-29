"""
Two-tier question search — the Postgres/pgvector solution-snapshot lookup.

THE PROPERLY-NAMED HOME (Rick's ruling 2026-08-15, decision row 29e98243): this
Postgres two-tier lookup used to live inside a wrongly-named file, in a class
named for a store it never touched. So the lookup moved HERE, to a module named
for what it does. Reuse, not rebuild.

WHAT LIVES HERE, AND WHY TWO SHAPES (not a duplication — a policy difference,
ratified by Cheech 2026-08-15):

    TwoTierQuestionSearch — the v2 flow's READ-ONLY, instrumented lookup. Returns
        a CacheLookup carrying the tier taken, the timings, and the embed-cache
        flag the v2 eval reads. It NEVER writes on a lookup (a ghost synonym just
        falls through), and it stops the ANN tier from ever triggering replay
        (R-C1: the replay signal is a tier-1 exact hit, never a float score).
        v2's V2Cache extends this with tagged write-back.

    pg_hierarchical_search — the snapshot manager's OWN two-tier lookup, lifted
        verbatim from `_pg_get_snapshots_by_question`. It has a DIFFERENT contract
        on purpose: it returns [(pct, snapshot)] tuples, auto-cleans ghost
        synonyms (a WRITE), and queries the ANN tier with no SQL threshold. The
        manager's method delegates here so it keeps byte-for-byte behaviour.
        Forcing both shapes through one core would smuggle a write into v2's read
        path — which is exactly why they stay two functions with one home.

THIS MODULE'S IMPORT GRAPH: it imports the Postgres repositories, the embedding
provider, the normalizers, and SolutionSnapshot — nothing else. The guard that
protects v2 is in tests/unit/test_v2_cache_no_lancedb.py.

Created: 2026-08-15 (CJ Flow v2 · row 29e98243 · Tiberius 👑)
"""

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from cosa.memory.embedding_provider import get_embedding_provider
from cosa.memory.gist_normalizer import GistNormalizer
from cosa.memory.normalizer import Normalizer
from cosa.memory.snapshot_manager_interface import PerformanceMonitor
from cosa.memory.solution_snapshot import SolutionSnapshot
from cosa.rest.db.database import get_db
from cosa.rest.db.repositories.canonical_synonym_repository import CanonicalSynonymRepository
from cosa.rest.db.repositories.question_embedding_repository import QuestionEmbeddingRepository
from cosa.rest.db.repositories.solution_snapshot_repository import SolutionSnapshotRepository

# Query the ANN tier at a LOW floor so scores it would reject still come back —
# the §6a threshold table is built post-hoc from those rejected scores, so the
# decision floor is applied in Python, never handed to the SQL query (risk 4).
DEFAULT_QUERY_FLOOR   = 70.0
DEFAULT_ANN_LIMIT     = 7
DEFAULT_EMBEDDING_DIM = 768

# The JSON-serialized Text columns that come back as strings and must be decoded
# when marshalling an ORM row into a replay-ready memory SolutionSnapshot.
_JSON_TEXT_COLUMNS = (
    "synonymous_questions", "synonymous_question_gists",
    "runtime_stats", "replay_history", "replay_stats", "answer_is_correct",
)

# The seven pgvector columns, passed to the constructor so it does NOT regenerate
# them (regeneration is a model-server round trip — ~977 ms and an external dep).
_EMBEDDING_COLUMNS = (
    "question_embedding", "question_normalized_embedding", "question_gist_embedding",
    "solution_embedding", "code_embedding", "thoughts_embedding", "solution_gist_embedding",
)


@dataclass( frozen=True )
class CacheLookup:
    """
    The immutable result of a two-tier lookup.

    Frozen so nothing downstream can rebind a field, and every SolutionSnapshot
    it carries is freshly marshalled (never aliased to a shared structure) — the
    lookup hands over copies, not references.

    Fields:
        is_replay_hit  : True ONLY on a tier-1 exact hit (R-C1). The ANN tier
                         never sets this in phase 1.
        tier           : "exact_verbatim" | "exact_normalized" | "ann" | "miss".
        snapshot       : replay-ready memory SolutionSnapshot on an exact hit,
                         else None.
        best_candidate : the strongest ANN candidate (measurement only), or None.
        similarity     : 100.0 on an exact hit, else the ANN best score, else None.
        best_score     : the ANN best score recorded on EVERY request for the
                         threshold table (None when no candidate came back).
        question_normalized : the normalized form used for tier-1b and the trace.
        t_exact_ms     : wall time spent in the exact tier(s).
        t_embed_ms     : wall time spent embedding for tier 2, or None when the
                         exact tier short-circuited (the "no embedding" case).
        t_ann_ms       : wall time spent in the ANN probe, or None when skipped.
        embed_cached   : True if the query embedding was served from the cache,
                         False if it was generated, None if no embedding happened.
    """
    is_replay_hit       : bool
    tier                : str
    snapshot            : Optional[SolutionSnapshot]
    best_candidate      : Optional[SolutionSnapshot]
    similarity          : Optional[float]
    best_score          : Optional[float]
    question_normalized : str
    t_exact_ms          : float
    t_embed_ms          : Optional[float]
    t_ann_ms            : Optional[float]
    embed_cached        : Optional[bool]


class TwoTierQuestionSearch:
    """
    Two-tier snapshot lookup (exact SQL → pgvector ANN), READ-ONLY.

    Postgres only. Every collaborator is injectable so the whole adapter is
    exercised by unit tests with fakes — no live Postgres and no model server on
    the :7999 test path. The repository CLASSES are injectable too, so a caller
    (e.g. v2's V2Cache) can pass its own module-level names and keep them
    monkeypatchable in that caller's namespace.
    """

    def __init__( self, embedding_provider: Any=None, snapshot_factory: Callable[ ..., Any ]=SolutionSnapshot,
                  normalizer: Any=None, gist_normalizer: Any=None, db_scope: Callable[ [], Any ]=get_db,
                  query_floor: float=DEFAULT_QUERY_FLOOR, ann_limit: int=DEFAULT_ANN_LIMIT,
                  embedding_dim: int=DEFAULT_EMBEDDING_DIM, *,
                  synonym_repo_cls: Callable[ ..., Any ]=CanonicalSynonymRepository,
                  snapshot_repo_cls: Callable[ ..., Any ]=SolutionSnapshotRepository,
                  embedding_repo_cls: Callable[ ..., Any ]=QuestionEmbeddingRepository,
                  debug: bool=False, verbose: bool=False ) -> None:
        """
        Wire the adapter's collaborators.

        Requires:
            - db_scope is a zero-arg callable returning a context manager that
              yields a SQLAlchemy Session and commits on clean exit (get_db)
            - query_floor is a similarity percentage in [0, 100]
            - ann_limit is a positive int; embedding_dim is a positive int

        Ensures:
            - stores the collaborators; constructs the real Normalizer /
              GistNormalizer / EmbeddingProvider lazily only when not injected,
              so a fully-faked construction touches no heavy singletons
        """
        self.debug              = debug
        self.verbose            = verbose
        self._snapshot_factory  = snapshot_factory
        self._db_scope          = db_scope
        self._query_floor       = query_floor
        self._ann_limit         = ann_limit
        self._embedding_dim     = embedding_dim
        self._synonym_repo_cls  = synonym_repo_cls
        self._snapshot_repo_cls = snapshot_repo_cls
        self._embedding_repo_cls = embedding_repo_cls
        self._normalizer        = normalizer      if normalizer      is not None else Normalizer()
        self._gist_normalizer   = gist_normalizer if gist_normalizer is not None else GistNormalizer()
        self._embedding_provider = embedding_provider if embedding_provider is not None else get_embedding_provider( debug=debug, verbose=verbose )

    # ------------------------------------------------------------------ lookup

    def lookup( self, question: str ) -> CacheLookup:
        """
        Two-tier lookup for a cached solution to ``question``.

        Requires:
            - question is a non-empty string

        Ensures:
            - tier 1 (exact verbatim, then exact normalized) returns a replay-ready
              SolutionSnapshot with is_replay_hit=True and similarity=100.0, with
              NO embedding computed
            - a synonym row that points at a missing snapshot (a ghost) is treated
              as a miss for that tier and falls through — the lookup never writes
            - tier 2 embeds the verbatim question, probes ANN, and returns the
              strongest candidate as best_candidate with is_replay_hit=False; its
              best_score is recorded even when below the decision floor
            - returns tier="miss" when nothing matches or the embedding is empty

        Raises:
            - ValueError if question is empty
        """
        if not question:
            raise ValueError( "lookup requires a non-empty question" )

        t_exact_start       = time.perf_counter_ns()
        question_normalized = self._normalizer.normalize( question )

        with self._db_scope() as session:
            snapshots = self._snapshot_repo_cls( session )
            synonyms  = self._synonym_repo_cls( session )

            # Tier 1 — the exact probes, in order (R-C1: THIS is the warm-pass replay
            # signal). The list is a method so a subclass can add a probe of its own
            # without copying the whole lookup; the two below are the base's contract
            # and their order is part of it.
            for tier_name, probe in self._exact_probes( synonyms, question, question_normalized ):
                snapshot = self._resolve_exact( snapshots, probe() )
                if snapshot is not None:
                    return self._exact_hit( snapshot, tier_name, question_normalized, t_exact_start )

            t_exact_ms = self._ms_since( t_exact_start )

            # Tier 2 — embed (cache-wired) then cosine nearest-k.
            embedding, embed_cached, t_embed_ms = self._query_embedding( session, question )
            if embedding is None or len( embedding ) == 0:
                if self.debug: print( "(two-tier) tier-2 miss: empty query embedding" )
                return CacheLookup(
                    is_replay_hit=False, tier="miss", snapshot=None, best_candidate=None,
                    similarity=None, best_score=None, question_normalized=question_normalized,
                    t_exact_ms=t_exact_ms, t_embed_ms=t_embed_ms, t_ann_ms=None, embed_cached=embed_cached,
                )

            t_ann_start = time.perf_counter_ns()
            candidates  = snapshots.get_snapshots_by_question(
                embedding, threshold=self._query_floor, limit=self._ann_limit
            )
            t_ann_ms = self._ms_since( t_ann_start )

            if not candidates:
                if self.debug: print( "(two-tier) tier-2 miss: no candidate above query floor" )
                return CacheLookup(
                    is_replay_hit=False, tier="miss", snapshot=None, best_candidate=None,
                    similarity=None, best_score=None, question_normalized=question_normalized,
                    t_exact_ms=t_exact_ms, t_embed_ms=t_embed_ms, t_ann_ms=t_ann_ms, embed_cached=embed_cached,
                )

            best_score, best_row = candidates[ 0 ]
            best_candidate       = self._orm_to_snapshot( best_row )
            if self.debug: print( f"(two-tier) tier-2 candidate at {best_score:.2f}% (route: below perfect match)" )
            return CacheLookup(
                is_replay_hit=False, tier="ann", snapshot=None, best_candidate=best_candidate,
                similarity=best_score, best_score=best_score, question_normalized=question_normalized,
                t_exact_ms=t_exact_ms, t_embed_ms=t_embed_ms, t_ann_ms=t_ann_ms, embed_cached=embed_cached,
            )

    def _exact_probes( self, synonyms: Any, question: str, question_normalized: str ) -> tuple:
        """
        The tier-1 probes this search runs, in order — (tier name, callable).

        A SEAM, not a refactor for its own sake: v2's cache adds a gist probe after
        these two, and the alternative was copying the whole of ``lookup`` into the
        subclass to insert one line — where the copy would then drift from this one
        silently. Each probe is a callable so a later probe costs nothing when an
        earlier one hits.

        Requires:
            - synonyms is an open-session CanonicalSynonymRepository

        Ensures:
            - returns exact-match probes ONLY: each is deterministic and returns a
              snapshot_id or None, never a score. A probe that ranked by similarity
              would make ``is_replay_hit`` a float comparison, which is what R-C1
              forbids.
            - the base returns verbatim then normalized, in that order
        """
        return (
            ( "exact_verbatim",   lambda: synonyms.find_exact_verbatim( question ) ),
            ( "exact_normalized", lambda: synonyms.find_exact_normalized( question_normalized ) ),
        )

    def _resolve_exact( self, snapshots: Any, snapshot_id: Optional[str] ) -> Optional[SolutionSnapshot]:
        """
        Marshal an exact-tier snapshot_id into a replay-ready memory snapshot.

        Requires:
            - snapshots is an open-session SolutionSnapshotRepository
            - snapshot_id is a snapshot id string, or None on a synonym miss

        Ensures:
            - returns the marshalled SolutionSnapshot, or None when the id is None
              or points at a missing row (a ghost — a miss for this tier)
        """
        if snapshot_id is None:
            return None
        row = snapshots.get_snapshot_by_id( snapshot_id )
        if row is None:
            if self.debug: print( f"(two-tier) ghost synonym → missing snapshot {snapshot_id}; falling through" )
            return None
        return self._orm_to_snapshot( row )

    def _exact_hit( self, snapshot: SolutionSnapshot, tier: str, question_normalized: str, t_exact_start: int ) -> CacheLookup:
        """
        Build the CacheLookup for a tier-1 exact hit (the replay signal).

        Ensures:
            - is_replay_hit=True, similarity=best_score=100.0, no embedding marks
        """
        if self.debug: print( f"(two-tier) tier-1 {tier} hit → replay" )
        return CacheLookup(
            is_replay_hit=True, tier=tier, snapshot=snapshot, best_candidate=None,
            similarity=100.0, best_score=100.0, question_normalized=question_normalized,
            t_exact_ms=self._ms_since( t_exact_start ), t_embed_ms=None, t_ann_ms=None, embed_cached=None,
        )

    def _query_embedding( self, session: Any, question: str ) -> Tuple[ List[float], bool, float ]:
        """
        Return the verbatim-question embedding for the ANN tier, cache-wired.

        Requires:
            - session is an open SQLAlchemy Session
            - question is a non-empty string

        Ensures:
            - returns ( embedding, embed_cached, t_embed_ms )
            - a cache hit (QuestionEmbeddingRepository, keyed by the VERBATIM
              question so the vector matches the question_embedding column's
              space) is returned as-is with embed_cached=True and no model call
            - a miss generates via the provider (content_type="prose", matching
              solution_snapshot.py:319) with embed_cached=False; generation does
              NOT write the cache — write-back owns cache population
        """
        t_embed_start = time.perf_counter_ns()
        cached = self._embedding_repo_cls( session ).get_embedding( question )
        if cached is not None:
            if self.debug: print( "(two-tier) query embedding served from cache (free)" )
            return cached, True, self._ms_since( t_embed_start )

        embedding = self._embedding_provider.generate_embedding( question, content_type="prose" )
        if self.debug: print( f"(two-tier) query embedding generated ({len( embedding ) if embedding else 0} dims)" )
        return embedding, False, self._ms_since( t_embed_start )

    # ----------------------------------------------------------- marshalling

    def _orm_to_snapshot( self, row: Any ) -> SolutionSnapshot:
        """
        Marshal a solution_snapshots ORM row into a replay-ready memory snapshot.

        Requires:
            - row is a SolutionSnapshot ORM entity accessed inside its open session

        Ensures:
            - JSON Text columns are decoded; all seven pgvector columns are passed
              to the constructor so it does NOT regenerate them; returns the
              memory SolutionSnapshot (a plain object, safe to return detached)
        """
        decoded    = { column: self._loads_or( getattr( row, column ), {} ) for column in _JSON_TEXT_COLUMNS }
        embeddings = { column: self._fit_embedding( getattr( row, column ) ) for column in _EMBEDDING_COLUMNS }

        return self._snapshot_factory(
            question=row.question,
            question_normalized=row.question_normalized or "",
            question_gist=row.question_gist or "",
            answer=row.answer or "",
            answer_conversational=row.answer_conversational or "",
            thoughts=row.thoughts or "",
            error=row.error or "",
            routing_command=row.routing_command or "",
            agent_class_name=row.agent_class_name,
            synonymous_questions=decoded[ "synonymous_questions" ],
            synonymous_question_gists=decoded[ "synonymous_question_gists" ],
            non_synonymous_questions=self._ensure_list( row.non_synonymous_questions ),
            last_question_asked=row.last_question_asked or "",
            created_date=row.created_date or "",
            updated_date=row.updated_date or "",
            run_date=row.run_date or "",
            runtime_stats=decoded[ "runtime_stats" ],
            id_hash=row.id_hash,
            solution_summary=row.solution_summary or "",
            code=self._ensure_list( row.code ),
            solution_summary_gist=row.solution_summary_gist or "",
            code_returns=row.code_returns or "",
            code_example=row.code_example or "",
            code_type=row.code_type or "",
            programming_language=row.programming_language or "python",
            language_version=row.language_version or "3.10",
            replay_history=decoded[ "replay_history" ],
            replay_stats=decoded[ "replay_stats" ],
            is_cache_hit=row.is_cache_hit,
            answer_is_correct=decoded[ "answer_is_correct" ],
            **embeddings,
        )

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _ms_since( start_ns: int ) -> float:
        """Elapsed milliseconds since a perf_counter_ns mark."""
        return ( time.perf_counter_ns() - start_ns ) / 1_000_000.0

    @staticmethod
    def _loads_or( raw: Any, default: Any ) -> Any:
        """
        Decode a JSON Text column, or return ``default`` for an empty/None cell.

        A malformed JSON string raises (fail loud) — a silently-swallowed decode
        error would hide a corrupt row.
        """
        if raw is None or raw == "":
            return default
        return json.loads( raw )

    @staticmethod
    def _ensure_list( value: Any ) -> list:
        """Coerce a list/None/array column into a plain list ([] for None)."""
        if value is None:
            return []
        if isinstance( value, list ):
            return value
        return list( value )

    def _fit_embedding( self, embedding: Any ) -> List[float]:
        """
        Fit a vector to the embedding dimension so pgvector never sees a
        NULL/short/long vector: zero-fill an empty, pad a short, truncate a long.
        """
        dim = self._embedding_dim
        if embedding is None or len( embedding ) == 0:
            return [ 0.0 ] * dim
        values = [ float( x ) for x in embedding ]
        if len( values ) == dim:
            return values
        if len( values ) < dim:
            return values + [ 0.0 ] * ( dim - len( values ) )
        return values[ :dim ]


def pg_hierarchical_search( manager: Any,
                            question: str,
                            question_gist: Optional[str] = None,
                            threshold_question: float = 90.0,
                            threshold_gist: float = 90.0,
                            limit: int = 7,
                            debug: bool = False ) -> List[Tuple[float, Any]]:
    """
    Hierarchical question search against Postgres, MIRRORING the manager's original
    hierarchy minus the in-memory cache tier (cache bypass): Level 1 exact-verbatim -> Level 2
    exact-normalized (both via the already-postgres-routed canonical_synonyms) ->
    Level 4 pgvector dot similarity.

    Lifted VERBATIM from the manager's `_pg_get_snapshots_by_question` (Rick's
    ruling 2026-08-15): the manager's own two-tier lookup, which WRITES
    (auto-cleans ghost synonyms), returns [(pct, snapshot)] tuples, and queries
    the ANN tier with no SQL threshold — a deliberately different contract from
    TwoTierQuestionSearch's read-only, instrumented one. ``manager`` is the
    snapshot manager whose collaborators the search drives; its method is now a
    one-line delegating shim to this function so behaviour is byte-exact.

    Requires:
        - manager is initialized; question non-empty; thresholds in [0,100]

    Ensures:
        - returns [(similarity_pct, snapshot)] sorted descending; exact matches
          short-circuit at 100.0; empty list when no embedding / no hits

    Raises:
        - RuntimeError if not initialized
        - ValueError if question empty or a threshold is out of range
    """
    if not manager.is_initialized():
        raise RuntimeError( "Manager must be initialized before searching" )

    if not question:
        raise ValueError( "Question cannot be empty" )

    if not (0.0 <= threshold_question <= 100.0) or not (0.0 <= threshold_gist <= 100.0):
        raise ValueError( "Thresholds must be between 0.0 and 100.0" )

    monitor = PerformanceMonitor( "get_snapshots_by_question" )
    monitor.start()

    try:
        # Lazy-init hierarchical search components
        if manager._canonical_synonyms is None:
            try:
                from cosa.memory.canonical_synonyms_table import CanonicalSynonymsTable
                manager._canonical_synonyms = CanonicalSynonymsTable( debug=manager.debug, verbose=manager.verbose )
                if manager.debug: print( "Initialized CanonicalSynonyms for hierarchical search" )
            except Exception as e:
                if manager.debug: print( f"Could not initialize CanonicalSynonyms, using direct search: {e}" )
                manager._canonical_synonyms = False

        if manager._normalizer is None:
            try:
                from cosa.memory.normalizer import Normalizer as _Normalizer
                manager._normalizer = _Normalizer()
                if manager.debug: print( "Initialized Normalizer for hierarchical search" )
            except Exception as e:
                if manager.debug: print( f"Could not initialize Normalizer: {e}" )
                manager._normalizer = False

        # Level 1: exact verbatim match in CanonicalSynonyms
        if manager._canonical_synonyms and manager._canonical_synonyms is not False:
            snapshot_id = manager._canonical_synonyms.find_exact_verbatim( question )
            if snapshot_id:
                if manager.debug: print( f"✓ LEVEL 1: Exact verbatim match found for snapshot: {snapshot_id}" )
                snapshot = manager.get_snapshot_by_id( snapshot_id )
                if snapshot:
                    monitor.stop()
                    return [ ( 100.0, snapshot ) ]
                else:
                    print( f"[GHOST] WARNING: Level 1 synonym points to missing snapshot {snapshot_id[:8]}... — auto-cleaning" )
                    manager._canonical_synonyms.delete_by_snapshot_id( snapshot_id )

            # Level 2: exact normalized match
            if manager._normalizer and manager._normalizer is not False:
                question_normalized = manager._normalizer.normalize( question )
                snapshot_id = manager._canonical_synonyms.find_exact_normalized( question_normalized )
                if snapshot_id:
                    if manager.debug: print( f"✓ LEVEL 2: Exact normalized match found for snapshot: {snapshot_id}" )
                    snapshot = manager.get_snapshot_by_id( snapshot_id )
                    if snapshot:
                        monitor.stop()
                        return [ ( 100.0, snapshot ) ]
                    else:
                        print( f"[GHOST] WARNING: Level 2 synonym points to missing snapshot {snapshot_id[:8]}... — auto-cleaning" )
                        manager._canonical_synonyms.delete_by_snapshot_id( snapshot_id )

        # (Level-3 gist tier + in-memory cache tier are SKIPPED — postgres cache bypass)

        # Level 4: pgvector dot similarity search
        if manager.debug: print( "LEVEL 4: No exact matches found, performing vector similarity search..." )

        query_embedding = manager._question_embeddings_tbl.get_embedding( question )
        if not query_embedding:
            if manager.debug: print( "Failed to generate query embedding, returning empty results" )
            monitor.stop()
            return []

        from cosa.rest.db.database import get_db as _get_db
        from cosa.rest.db.repositories.solution_snapshot_repository import SolutionSnapshotRepository as _SnapRepo

        similar_snapshots = []
        with _get_db() as session:
            # threshold=None => no SQL threshold (top-1 + confirm: return all, caller decides)
            hits = _SnapRepo( session ).get_snapshots_by_question(
                query_embedding, threshold=None, limit=limit if limit > 0 else 100
            )
            for pct, entity in hits:
                similar_snapshots.append( ( pct, manager._record_to_snapshot( manager._pg_record_from_entity( entity ) ) ) )

        similar_snapshots.sort( key=lambda x: x[0], reverse=True )

    except Exception as e:
        if manager.debug: print( f"✗ Search failed: {e}" )
        raise
    finally:
        monitor.stop()

    return similar_snapshots


# ──────────────────────────────────────────────────────────────────────────────
# Additive step-2 lift (Cheech 2026-08-15): the record marshalling, the synonym
# cascade, and the shared pgvector similarity search — all pure Postgres — move
# here beside the two-tier lookup, each a VERBATIM copy of its former manager
# method with ``self`` renamed to ``manager``.
# The manager keeps its old method names as one-line delegating shims, so every
# collaborator (``manager._ensure_list``, ``manager._record_to_snapshot``,
# ``manager._pg_record_from_entity``, ``manager._canonical_synonyms``) resolves
# exactly as before and behaviour is byte-for-byte unchanged. Additive only:
# TwoTierQuestionSearch's public contract is untouched.
# ──────────────────────────────────────────────────────────────────────────────


def snapshot_to_pg_record( manager: Any, snapshot: SolutionSnapshot ) -> Dict[str, Any]:
    """
    Convert SolutionSnapshot to the Postgres record format.

    Requires:
        - snapshot is valid SolutionSnapshot instance
        - snapshot.question is not empty

    Ensures:
        - Returns dictionary compatible with the Postgres snapshot columns
        - Handles missing fields gracefully with defaults
        - Converts embeddings to proper format

    Args:
        snapshot: SolutionSnapshot to convert

    Returns:
        Dictionary record for Postgres insertion

    Raises:
        - ValueError if snapshot invalid
    """
    if not snapshot or not snapshot.question:
        raise ValueError( "Invalid snapshot: question cannot be empty" )

    # Preserve original snapshot ID hash (SHA256 of timestamp)
    id_hash = snapshot.id_hash

    # Helper function to ensure vector is proper format. Guards on length, not
    # truthiness, and processes any sequence (list OR numpy ndarray) uniformly —
    # `if not embedding:` raised "truth value of an array ... is ambiguous" on an
    # ndarray, and the old list-only branch would have zero-filled one even after
    # the guard. Mirrors TwoTierQuestionSearch._fit_embedding (bug 60b5221e).
    def normalize_embedding( embedding ):
        dim = manager._embedding_dim
        if embedding is None or not hasattr( embedding, "__len__" ) or len( embedding ) == 0:
            return [0.0] * dim
        values = [ float( x ) for x in embedding ]
        if len( values ) == dim:
            return values
        if len( values ) < dim:
            # Pad with zeros
            return values + [0.0] * ( dim - len( values ) )
        # Truncate
        return values[ :dim ]

    record = {
        # Primary identifiers
        "id_hash": id_hash,
        "user_id": getattr( snapshot, 'user_id', 'default_user' ),

        # Content fields
        "question": snapshot.question,
        "question_normalized": getattr( snapshot, 'question_normalized', '' ) or '',
        "question_gist": getattr( snapshot, 'question_gist', '' ) or '',
        "answer": getattr( snapshot, 'answer', '' ) or '',
        "answer_conversational": getattr( snapshot, 'answer_conversational', '' ) or '',
        "solution_summary": getattr( snapshot, 'solution_summary', '' ) or '',
        "thoughts": getattr( snapshot, 'thoughts', '' ) or '',
        "error": getattr( snapshot, 'error', '' ) or '',
        "routing_command": getattr( snapshot, 'routing_command', '' ) or '',
        "agent_class_name": getattr( snapshot, 'agent_class_name', '' ) or '',

        # Code execution data - ensure code is always a list for schema compatibility
        "code": manager._ensure_list( getattr( snapshot, 'code', [] ) ),
        "solution_summary_gist": getattr( snapshot, 'solution_summary_gist', '' ) or '',  # Gist of solution_summary
        "code_returns": getattr( snapshot, 'code_returns', '' ) or '',
        "code_example": getattr( snapshot, 'code_example', '' ) or '',
        "code_type": getattr( snapshot, 'code_type', '' ) or '',
        "programming_language": getattr( snapshot, 'programming_language', 'python' ),
        "language_version": getattr( snapshot, 'language_version', '3.10' ),

        # Synonymous questions (convert dict to JSON string)
        "synonymous_questions": json.dumps( getattr( snapshot, 'synonymous_questions', {} ) ),
        "synonymous_question_gists": json.dumps( getattr( snapshot, 'synonymous_question_gists', {} ) ),
        "non_synonymous_questions": manager._ensure_list( getattr( snapshot, 'non_synonymous_questions', [] ) ),
        "last_question_asked": getattr( snapshot, 'last_question_asked', '' ) or '',

        # Temporal data
        "created_date": getattr( snapshot, 'created_date', time.strftime( "%Y-%m-%d @ %H:%M:%S %Z" ) ),
        "updated_date": getattr( snapshot, 'updated_date', time.strftime( "%Y-%m-%d @ %H:%M:%S %Z" ) ),
        "run_date": getattr( snapshot, 'run_date', '' ) or '',
        "runtime_stats": json.dumps( getattr( snapshot, 'runtime_stats', {} ) ),

        # Replay tracking for Time Saved Dashboard
        "replay_history": json.dumps( getattr( snapshot, 'replay_history', [] ) ),
        "replay_stats": json.dumps( getattr( snapshot, 'replay_stats', {} ) ),
        "is_cache_hit": getattr( snapshot, 'is_cache_hit', False ),
        "answer_is_correct": json.dumps( snapshot.answer_is_correct ),

        # Vector embeddings
        "question_embedding": normalize_embedding( getattr( snapshot, 'question_embedding', [] ) ),
        "question_normalized_embedding": normalize_embedding( getattr( snapshot, 'question_normalized_embedding', [] ) ),
        "question_gist_embedding": normalize_embedding( getattr( snapshot, 'question_gist_embedding', [] ) ),
        "solution_embedding": normalize_embedding( getattr( snapshot, 'solution_embedding', [] ) ),
        "code_embedding": normalize_embedding( getattr( snapshot, 'code_embedding', [] ) ),
        "thoughts_embedding": normalize_embedding( getattr( snapshot, 'thoughts_embedding', [] ) ),
        "solution_gist_embedding": normalize_embedding( getattr( snapshot, 'solution_gist_embedding', [] ) ),
    }

    return record


def pg_record_to_snapshot( manager: Any, record: Dict[str, Any] ) -> SolutionSnapshot:
    """
    Convert a Postgres record back to SolutionSnapshot.

    Requires:
        - record contains all required fields
        - Vector fields are in proper format

    Ensures:
        - Returns valid SolutionSnapshot instance
        - Handles JSON deserialization
        - Preserves all original data
        - CRITICAL: Passes embeddings to constructor to prevent regeneration (977ms savings)

    Args:
        record: Postgres record dictionary

    Returns:
        Reconstructed SolutionSnapshot
    """
    # Deserialize JSON fields first for constructor
    try:
        synonymous_questions = json.loads( record.get( "synonymous_questions", "{}" ) )
    except:
        synonymous_questions = {}

    try:
        synonymous_question_gists = json.loads( record.get( "synonymous_question_gists", "{}" ) )
    except:
        synonymous_question_gists = {}

    try:
        runtime_stats = json.loads( record.get( "runtime_stats", "{}" ) )
    except:
        runtime_stats = {}

    # Deserialize replay tracking fields
    try:
        replay_history = json.loads( record.get( "replay_history", "[]" ) )
    except:
        replay_history = []

    try:
        replay_stats = json.loads( record.get( "replay_stats", "{}" ) )
    except:
        replay_stats = {}

    is_cache_hit = record.get( "is_cache_hit", False )

    try:
        answer_is_correct = json.loads( record.get( "answer_is_correct", "null" ) )
    except:
        answer_is_correct = None

    # Create SolutionSnapshot with ALL fields INCLUDING embeddings
    # CRITICAL: Passing embeddings to constructor prevents 977ms regeneration
    snapshot = SolutionSnapshot(
        question=record["question"],
        question_normalized=record.get( "question_normalized", "" ),
        question_gist=record.get( "question_gist", "" ),
        answer=record.get( "answer", "" ),
        answer_conversational=record.get( "answer_conversational", "" ),
        thoughts=record.get( "thoughts", "" ),
        error=record.get( "error", "" ),
        routing_command=record.get( "routing_command", "" ),
        agent_class_name=record.get( "agent_class_name", None ),
        synonymous_questions=synonymous_questions,
        synonymous_question_gists=synonymous_question_gists,
        non_synonymous_questions=record.get( "non_synonymous_questions", [] ),
        last_question_asked=record.get( "last_question_asked", "" ),
        created_date=record.get( "created_date", "" ),
        updated_date=record.get( "updated_date", "" ),
        run_date=record.get( "run_date", "" ),
        runtime_stats=runtime_stats,
        id_hash=record["id_hash"],  # CRITICAL: Preserve existing hash from database
        solution_summary=record.get( "solution_summary", "" ),
        code=manager._ensure_list( record.get( "code", [] ) ),  # Ensure code is list, not NumPy array
        solution_summary_gist=record.get( "solution_summary_gist", "" ),  # Gist of solution_summary
        code_returns=record.get( "code_returns", "" ),
        code_example=record.get( "code_example", "" ),
        code_type=record.get( "code_type", "" ),
        programming_language=record.get( "programming_language", "python" ),
        language_version=record.get( "language_version", "3.10" ),
        # CRITICAL: Pass embeddings to constructor to prevent regeneration
        question_embedding=manager._ensure_list( record.get( "question_embedding", [] ) ),
        question_normalized_embedding=manager._ensure_list( record.get( "question_normalized_embedding", [] ) ),
        question_gist_embedding=manager._ensure_list( record.get( "question_gist_embedding", [] ) ),
        solution_embedding=manager._ensure_list( record.get( "solution_embedding", [] ) ),
        code_embedding=manager._ensure_list( record.get( "code_embedding", [] ) ),
        thoughts_embedding=manager._ensure_list( record.get( "thoughts_embedding", [] ) ),
        solution_gist_embedding=manager._ensure_list( record.get( "solution_gist_embedding", [] ) ),
        # Replay tracking for Time Saved Dashboard
        replay_history=replay_history,
        replay_stats=replay_stats,
        is_cache_hit=is_cache_hit,
        answer_is_correct=answer_is_correct
    )

    return snapshot


def update_canonical_synonyms( manager: Any, snapshot: SolutionSnapshot ) -> None:
    """
    Update CanonicalSynonyms table with questions from snapshot.

    Ensures all three representations (verbatim, normalized, gist) are indexed
    for fast exact-match lookups in hierarchical search (Levels 1-3).

    Requires:
        - snapshot is a valid SolutionSnapshot instance
        - snapshot.id_hash is set

    Ensures:
        - Adds verbatim question to canonical_synonyms table
        - Adds all synonymous questions from snapshot
        - Each entry gets normalized + gist variants auto-generated
        - No-op if canonical_synonyms not available

    Args:
        snapshot: The SolutionSnapshot to extract questions from
    """
    # Check if CanonicalSynonyms is available
    if not manager._canonical_synonyms or manager._canonical_synonyms is False:
        if manager.debug and manager.verbose:
            print( "  ⓘ CanonicalSynonyms not available, skipping synonym update" )
        return

    # Add the primary question (last_question_asked)
    if snapshot.last_question_asked:
        try:
            manager._canonical_synonyms.add_synonym(
                snapshot_id=snapshot.id_hash,
                question_verbatim=snapshot.last_question_asked,
                confidence_score=100.0,
                source="runtime"
            )
            if manager.debug:
                print( f"  ✓ Added primary question to canonical synonyms: '{snapshot.last_question_asked[:50]}...'" )
        except Exception as e:
            if manager.debug:
                print( f"  ⚠ Failed to add primary question to synonyms: {e}" )

    # Skip synonymous_questions - contains historical corruption from deprecated remove_non_alphanumerics()
    # The deprecated method stripped math operators: "What's 2+2?" → "whats 22"
    # Future synonyms will be added correctly now that add_synonymous_question() uses Normalizer.normalize()
    # Canonical table will rebuild with correct normalization as users ask questions
    if manager.debug and manager.verbose:
        if hasattr( snapshot, 'synonymous_questions' ) and snapshot.synonymous_questions:
            print( f"  ⓘ Skipping {len( snapshot.synonymous_questions )} synonymous questions (legacy corrupted data)" )


def pg_similarity_search( manager: Any, exemplar_snapshot, embedding_attr, repo_method_name,
                          threshold, limit, exclude_self, ensure_top_result ):
    """
    Shared pgvector dot similarity search backing the code + solution similarity paths.

    Fetches WITHOUT a SQL threshold/exclusion (threshold=None) then replicates the
    original Python-side self-skip + threshold split + ensure_top_result + limit —
    byte-exact behavior including the best-below-threshold fallback.

    Requires:
        - manager is initialized; exemplar_snapshot not None; threshold in [0,100]

    Ensures:
        - returns [(similarity_pct, snapshot)] sorted descending, capped at limit;
          [] on a missing / all-zero embedding

    Raises:
        - RuntimeError if not initialized
        - ValueError if exemplar_snapshot None or threshold out of range
    """
    if not manager.is_initialized():
        raise RuntimeError( "Manager must be initialized before searching" )
    if not exemplar_snapshot:
        raise ValueError( "Exemplar snapshot cannot be None" )
    if not (0.0 <= threshold <= 100.0):
        raise ValueError( "Threshold must be between 0.0 and 100.0" )

    query_embedding = getattr( exemplar_snapshot, embedding_attr )
    if not query_embedding:
        return []
    if all( v == 0.0 for v in query_embedding[:100] ):
        return []

    effective_limit = ( limit + 1 ) if exclude_self else ( limit if limit > 0 else 100 )

    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.solution_snapshot_repository import SolutionSnapshotRepository

    similar_snapshots     = []
    best_below_threshold  = None
    with get_db() as session:
        repo = SolutionSnapshotRepository( session )
        hits = getattr( repo, repo_method_name )( query_embedding, threshold=None, limit=effective_limit )
        for pct, entity in hits:
            if exclude_self and entity.id_hash == exemplar_snapshot.id_hash:
                continue
            if pct >= threshold:
                similar_snapshots.append( ( pct, manager._record_to_snapshot( manager._pg_record_from_entity( entity ) ) ) )
            elif ensure_top_result and best_below_threshold is None:
                best_below_threshold = ( pct, manager._record_to_snapshot( manager._pg_record_from_entity( entity ) ) )

    similar_snapshots.sort( key=lambda x: x[0], reverse=True )
    if limit > 0:
        similar_snapshots = similar_snapshots[:limit]
    if len( similar_snapshots ) == 0 and ensure_top_result and best_below_threshold is not None:
        similar_snapshots.append( best_below_threshold )
    return similar_snapshots
