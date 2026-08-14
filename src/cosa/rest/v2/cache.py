"""
CJ Flow v2 — cache adapter (unit C2).

A two-tier solution-snapshot cache over the Postgres/pgvector repositories, plus
tagged write-back. LanceDB appears NOWHERE in this module's import graph — v2
talks to the Postgres repositories directly (Rick's ruling 2026-08-14: "LanceDB
is out, do not use in any way shape or form").

The two tiers (design doc §6, revised by handoff §3.C):

    Tier 1 — exact      plain equality on the verbatim question, then on the
                        normalized question, via CanonicalSynonymRepository.
                        One indexed lookup, NO embedding. This is the REPLAY
                        signal (R-C1): a warm-pass repeat is a deterministic,
                        lossless exact hit — never a float comparison against
                        an ANN score, which understates the cache-hit rate the
                        experiment exists to measure.

    Tier 2 — similar    embed the verbatim question (cache-wired via
                        QuestionEmbeddingRepository, keyed by the SAME verbatim
                        text that produced the question_embedding column — a
                        normalized-keyed cache would hand back a vector from a
                        different space), then cosine nearest-k via
                        SolutionSnapshotRepository.get_snapshots_by_question.
                        Its best score is RECORDED on every request for the
                        §6a threshold table, but in phase 1 it does NOT trigger
                        replay — below a perfect match, route.

Write-back (design doc §6, revised by handoff R-D2): the tagged field is rebound
with ``{ **old, **tag }`` and NEVER mutated in place, because SolutionSnapshot's
runtime_stats is a shared mutable default — an in-place tag would leak the v2
markers onto every default-constructed snapshot in the process.

Created: 2026-08-14 (CJ Flow v2 · unit C2 · Sam 🎙️)
"""

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

from cosa.memory.embedding_provider import get_embedding_provider
from cosa.memory.gist_normalizer import GistNormalizer
from cosa.memory.normalizer import Normalizer
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

# Tags stamped into runtime_stats on write-back so the shared table can be
# filtered to "what v2 created" with no schema change (runtime_stats is Text).
_V2_FLOW_VERSION = "v2"
_V2_CREATED_BY   = "v2.ask"

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
    The immutable result of a cache lookup.

    Frozen so nothing downstream can rebind a field, and every SolutionSnapshot
    it carries is freshly marshalled (never aliased to a shared structure) — v2
    hands over copies, not references.

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


class V2Cache:
    """
    Two-tier snapshot cache (exact SQL → pgvector ANN) + tagged write-back.

    Postgres only. Every collaborator is injectable so the whole adapter is
    exercised by unit tests with fakes — no live Postgres and no model server
    on the :7999 test path.
    """

    def __init__( self, embedding_provider: Any=None, snapshot_factory: Callable[ ..., Any ]=SolutionSnapshot,
                  normalizer: Any=None, gist_normalizer: Any=None, db_scope: Callable[ [], Any ]=get_db,
                  query_floor: float=DEFAULT_QUERY_FLOOR, ann_limit: int=DEFAULT_ANN_LIMIT,
                  embedding_dim: int=DEFAULT_EMBEDDING_DIM, debug: bool=False, verbose: bool=False ) -> None:
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
        self.debug             = debug
        self.verbose           = verbose
        self._snapshot_factory = snapshot_factory
        self._db_scope         = db_scope
        self._query_floor      = query_floor
        self._ann_limit        = ann_limit
        self._embedding_dim    = embedding_dim
        self._normalizer       = normalizer      if normalizer      is not None else Normalizer()
        self._gist_normalizer  = gist_normalizer if gist_normalizer is not None else GistNormalizer()
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
            snapshots = SolutionSnapshotRepository( session )
            synonyms  = CanonicalSynonymRepository( session )

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
            if not embedding:
                if self.debug: print( "(v2cache) tier-2 miss: empty query embedding" )
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
                if self.debug: print( "(v2cache) tier-2 miss: no candidate above query floor" )
                return CacheLookup(
                    is_replay_hit=False, tier="miss", snapshot=None, best_candidate=None,
                    similarity=None, best_score=None, question_normalized=question_normalized,
                    t_exact_ms=t_exact_ms, t_embed_ms=t_embed_ms, t_ann_ms=t_ann_ms, embed_cached=embed_cached,
                )

            best_score, best_row = candidates[ 0 ]
            best_candidate       = self._orm_to_snapshot( best_row )
            if self.debug: print( f"(v2cache) tier-2 candidate at {best_score:.2f}% (route: below perfect match)" )
            return CacheLookup(
                is_replay_hit=False, tier="ann", snapshot=None, best_candidate=best_candidate,
                similarity=best_score, best_score=best_score, question_normalized=question_normalized,
                t_exact_ms=t_exact_ms, t_embed_ms=t_embed_ms, t_ann_ms=t_ann_ms, embed_cached=embed_cached,
            )

    def _resolve_exact( self, snapshots: SolutionSnapshotRepository, snapshot_id: Optional[str] ) -> Optional[SolutionSnapshot]:
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
            if self.debug: print( f"(v2cache) ghost synonym → missing snapshot {snapshot_id}; falling through" )
            return None
        return self._orm_to_snapshot( row )

    def _exact_hit( self, snapshot: SolutionSnapshot, tier: str, question_normalized: str, t_exact_start: int ) -> CacheLookup:
        """
        Build the CacheLookup for a tier-1 exact hit (the replay signal).

        Ensures:
            - is_replay_hit=True, similarity=best_score=100.0, no embedding marks
        """
        if self.debug: print( f"(v2cache) tier-1 {tier} hit → replay" )
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
        cached = QuestionEmbeddingRepository( session ).get_embedding( question )
        if cached is not None:
            if self.debug: print( "(v2cache) query embedding served from cache (free)" )
            return cached, True, self._ms_since( t_embed_start )

        embedding = self._embedding_provider.generate_embedding( question, content_type="prose" )
        if self.debug: print( f"(v2cache) query embedding generated ({len( embedding ) if embedding else 0} dims)" )
        return embedding, False, self._ms_since( t_embed_start )

    # ------------------------------------------------------------ construction

    def snapshot_from_result( self, question: str, answer: str, answer_conversational: str,
                              routing_command: str, agent_class_name: str="",
                              user_id: str="", session_id: str="" ) -> SolutionSnapshot:
        """
        Build a replay-shaped SolutionSnapshot from a flow result's raw fields.

        This is the ONE place that knows how to construct a snapshot — the flow
        (unit D) hands over raw fields and never builds one itself, which is the
        coupling this exercise deletes. NO policy flag lives here (write-back's
        kill-switch is checked in exactly one place, `write_back`), so the flag
        cannot be checked twice and drift.

        Requires:
            - question is a non-empty string

        Ensures:
            - returns a SolutionSnapshot with question_normalized derived via the
              adapter's normalizer and every other field defaulted by the
              constructor (which mints the id_hash and the embeddings)

        Raises:
            - ValueError if question is empty
        """
        if not question:
            raise ValueError( "snapshot_from_result requires a non-empty question" )
        return self._snapshot_factory(
            question=question,
            question_normalized=self._normalizer.normalize( question ),
            answer=answer,
            answer_conversational=answer_conversational,
            routing_command=routing_command,
            agent_class_name=agent_class_name,
            last_question_asked=question,
            user_id=user_id,
            session_id=session_id,
        )

    # -------------------------------------------------------------- write-back

    def write_back( self, snapshot: SolutionSnapshot, writeback_enabled: bool=True,
                    created_at_iso: Optional[str]=None ) -> Optional[str]:
        """
        Persist a v2-created snapshot into the shared table, tagged v2.

        The writeback kill-switch is checked HERE and nowhere else.

        Requires:
            - snapshot is a memory SolutionSnapshot with a non-empty question and
              a set id_hash

        Ensures:
            - writeback_enabled=False records NOTHING and returns None (the
              deliberate off state — `v2 snapshot writeback enabled = false`)
            - writeback_enabled=True with a missing persist collaborator RAISES —
              a disabled write is a config choice, but an ON write that cannot
              complete must fail loud, never silently drop
            - on a live write: runtime_stats is REBOUND with { **old,
              "flow_version": "v2", "created_by": "v2.ask", "created_at": <iso> }
              — never mutated in place (R-D2); question_gist and question_embedding
              are computed here (off the hot path, §6) only when absent; the row is
              upserted, one canonical-synonym row is (re)registered so tier-1 finds
              it on the warm pass, the verbatim embedding cache is populated, and
              the snapshot's id_hash is returned

        Raises:
            - ValueError if the snapshot has no question or no id_hash
            - RuntimeError if writeback_enabled is True but the db scope needed to
              persist is missing (the embedding provider and gist normalizer are
              coalesced to real objects at construction, so they cannot be None)
        """
        if not snapshot.question:
            raise ValueError( "write_back requires a snapshot with a non-empty question" )
        if not snapshot.id_hash:
            raise ValueError( "write_back requires a snapshot with a set id_hash" )

        if not writeback_enabled:
            if self.debug: print( "(v2cache) write-back disabled — recording nothing" )
            return None

        if self._db_scope is None:
            raise RuntimeError( "write-back enabled but the db scope is missing — cannot persist" )

        created_at = created_at_iso if created_at_iso is not None else time.strftime( "%Y-%m-%dT%H:%M:%S%z" )

        # R-D2: REBIND, do not mutate — runtime_stats is a shared mutable default.
        snapshot.runtime_stats = { **snapshot.runtime_stats,
                                   "flow_version" : _V2_FLOW_VERSION,
                                   "created_by"   : _V2_CREATED_BY,
                                   "created_at"   : created_at }

        # Gist + embedding computed lazily here (off the hot path, §6).
        if not snapshot.question_gist:
            snapshot.question_gist = self._gist_normalizer.get_normalized_gist( snapshot.question )
        if not snapshot.question_embedding:
            snapshot.question_embedding = self._embedding_provider.generate_embedding( snapshot.question, content_type="prose" )

        record  = self._snapshot_to_record( snapshot )
        id_hash = record.pop( "id_hash" )

        with self._db_scope() as session:
            SolutionSnapshotRepository( session ).upsert_snapshot( id_hash, **record )

            synonyms = CanonicalSynonymRepository( session )
            synonyms.delete_by_snapshot_id( id_hash )   # idempotent re-registration
            synonyms.add_synonym(
                id                  = self._synonym_id( id_hash, snapshot.question ),
                snapshot_id         = id_hash,
                question_verbatim   = snapshot.question,
                question_normalized = snapshot.question_normalized,
                question_gist       = snapshot.question_gist,
                confidence_score    = 100.0,
                source              = _V2_CREATED_BY,
            )

            # Populate the verbatim embedding cache so a later ANN probe is free.
            QuestionEmbeddingRepository( session ).add_embedding( snapshot.question, snapshot.question_embedding )

        if self.debug: print( f"(v2cache) wrote back {id_hash} tagged {_V2_FLOW_VERSION}" )
        return id_hash

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

    def _snapshot_to_record( self, snapshot: SolutionSnapshot ) -> dict:
        """
        Marshal a memory snapshot into the SolutionSnapshotRepository field dict.

        Requires:
            - snapshot is a memory SolutionSnapshot with a non-empty question and
              its attributes populated (SolutionSnapshot.__init__ sets them all,
              so no defensive getattr is needed)

        Ensures:
            - dict fields are 1:1 with the solution_snapshots columns; dict-valued
              fields are JSON-serialized, list columns are lists, and the seven
              embeddings are fitted to the vector dimension so no NULL/short
              vector reaches pgvector
        """
        record = {
            "id_hash"                  : snapshot.id_hash,
            "user_id"                  : snapshot.user_id,
            "question"                 : snapshot.question,
            "question_normalized"      : snapshot.question_normalized or "",
            "question_gist"            : snapshot.question_gist or "",
            "answer"                   : snapshot.answer or "",
            "answer_conversational"    : snapshot.answer_conversational or "",
            "solution_summary"         : snapshot.solution_summary or "",
            "thoughts"                 : snapshot.thoughts or "",
            "error"                    : snapshot.error or "",
            "routing_command"          : snapshot.routing_command or "",
            "agent_class_name"         : snapshot.agent_class_name or "",
            "code"                     : self._ensure_list( snapshot.code ),
            "solution_summary_gist"    : snapshot.solution_summary_gist or "",
            "code_returns"             : snapshot.code_returns or "",
            "code_example"             : snapshot.code_example or "",
            "code_type"                : snapshot.code_type or "",
            "programming_language"     : snapshot.programming_language,
            "language_version"         : snapshot.language_version,
            "synonymous_questions"     : json.dumps( snapshot.synonymous_questions ),
            "synonymous_question_gists": json.dumps( snapshot.synonymous_question_gists ),
            "non_synonymous_questions" : self._ensure_list( snapshot.non_synonymous_questions ),
            "last_question_asked"      : snapshot.last_question_asked or "",
            "created_date"             : snapshot.created_date,
            "updated_date"             : snapshot.updated_date,
            "run_date"                 : snapshot.run_date or "",
            "runtime_stats"            : json.dumps( snapshot.runtime_stats ),
            "replay_history"           : json.dumps( snapshot.replay_history ),
            "replay_stats"             : json.dumps( snapshot.replay_stats ),
            "is_cache_hit"             : snapshot.is_cache_hit,
            "answer_is_correct"        : json.dumps( snapshot.answer_is_correct ),
        }
        for column in _EMBEDDING_COLUMNS:
            record[ column ] = self._fit_embedding( getattr( snapshot, column ) )
        return record

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _synonym_id( snapshot_id: str, question: str ) -> str:
        """
        Deterministic canonical-synonym row id for ( snapshot, question ).

        Ensures:
            - the SAME id for the same pair, so a re-registered synonym is stable
        """
        import hashlib
        return hashlib.sha256( f"{snapshot_id}|{question}".encode( "utf-8" ) ).hexdigest()

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
        if not embedding:
            return [ 0.0 ] * dim
        values = [ float( x ) for x in embedding ]
        if len( values ) == dim:
            return values
        if len( values ) < dim:
            return values + [ 0.0 ] * ( dim - len( values ) )
        return values[ :dim ]
