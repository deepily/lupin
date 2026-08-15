"""
Two-tier question search — the Postgres/pgvector solution-snapshot lookup.

THE PROPERLY-NAMED HOME (Rick's ruling 2026-08-15, decision row 29e98243): the
Postgres two-tier lookup used to live inside a LanceDB-*named* file
(`lancedb_solution_manager._pg_get_snapshots_by_question`) even though it touches
no LanceDB. "LanceDB is out, do not use in any way shape or form" — so the lookup
moves HERE, a module named for what it does, and the old name stays as a
delegating shim. Reuse, not rebuild.

WHAT LIVES HERE, AND WHY TWO SHAPES (not a duplication — a policy difference,
ratified by Cheech 2026-08-15):

    TwoTierQuestionSearch — the v2 flow's READ-ONLY, instrumented lookup. Returns
        a CacheLookup carrying the tier taken, the timings, and the embed-cache
        flag the v2 eval reads. It NEVER writes on a lookup (a ghost synonym just
        falls through), and it stops the ANN tier from ever triggering replay
        (R-C1: the replay signal is a tier-1 exact hit, never a float score).
        v2's V2Cache extends this with tagged write-back.

    pg_hierarchical_search — the LanceDB manager's OWN two-tier lookup, lifted
        verbatim from `_pg_get_snapshots_by_question`. It has a DIFFERENT contract
        on purpose: it returns [(pct, snapshot)] tuples, auto-cleans ghost
        synonyms (a WRITE), and queries the ANN tier with no SQL threshold. Its
        old method delegates here so the manager keeps byte-for-byte behaviour.
        Forcing both shapes through one core would smuggle a write into v2's read
        path — which is exactly why they stay two functions with one home.

NO LANCEDB MODULE IN THIS MODULE'S IMPORT GRAPH: this file imports the Postgres
repositories, the embedding provider, the normalizers, and SolutionSnapshot —
never `cosa.memory.lancedb_solution_manager`. Importing SolutionSnapshot does pull
the third-party `lancedb` PACKAGE (55 modules, unavoidable while snapshots have
their current shape — Mr. Radio's measurement 2026-08-14), but the guard that
protects v2 bans the MODULE, not the package. See tests/unit/test_v2_cache_no_lancedb.py.

Created: 2026-08-15 (CJ Flow v2 · row 29e98243 · Tiberius 👑)
"""

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

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

            # Tier 1a — exact verbatim.
            snapshot = self._resolve_exact( snapshots, synonyms.find_exact_verbatim( question ) )
            if snapshot is not None:
                return self._exact_hit( snapshot, "exact_verbatim", question_normalized, t_exact_start )

            # Tier 1b — exact normalized (R-C1: THIS is the warm-pass replay signal).
            snapshot = self._resolve_exact( snapshots, synonyms.find_exact_normalized( question_normalized ) )
            if snapshot is not None:
                return self._exact_hit( snapshot, "exact_normalized", question_normalized, t_exact_start )

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
    Hierarchical question search against Postgres, MIRRORING the LanceDB hierarchy
    minus the in-memory cache tier (cache bypass): Level 1 exact-verbatim -> Level 2
    exact-normalized (both via the already-postgres-routed canonical_synonyms) ->
    Level 4 pgvector dot similarity.

    Lifted VERBATIM from SolutionSnapshotManager._pg_get_snapshots_by_question
    (Rick's ruling 2026-08-15): the manager's own two-tier lookup, which WRITES
    (auto-cleans ghost synonyms), returns [(pct, snapshot)] tuples, and queries
    the ANN tier with no SQL threshold — a deliberately different contract from
    TwoTierQuestionSearch's read-only, instrumented one. ``manager`` is the
    SolutionSnapshotManager whose collaborators the search drives; the old method
    is now a one-line delegating shim to this function so behaviour is byte-exact.

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
        # Lazy-init hierarchical search components (mirrors the LanceDB path)
        if manager._canonical_synonyms is None:
            try:
                from cosa.memory.canonical_synonyms_table import CanonicalSynonymsTable
                manager._canonical_synonyms = CanonicalSynonymsTable( db_path=manager.db_path, debug=manager.debug, verbose=manager.verbose )
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
