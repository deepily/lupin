"""
CJ Flow v2 — cache adapter (unit C2).

A two-tier solution-snapshot cache over the Postgres/pgvector repositories, plus
tagged write-back. V2 talks to the Postgres repositories directly.

REUSE, NOT REBUILD (Rick's ruling 2026-08-15, decision row 29e98243): the two-tier
lookup itself now lives in the properly-named module
``cosa.memory.two_tier_question_search`` as ``TwoTierQuestionSearch``. V2Cache
SUBCLASSES it — inheriting ``lookup`` and all the ORM→snapshot marshalling — and
adds only the v2-specific pieces below (tagged write-back + snapshot construction).
So the read path is shared with the snapshot manager's own shim rather than
duplicated, while V2Cache stays read-only on lookup and instrumented for the eval.

The two tiers (design doc §6, revised by handoff §3.C) live in the base class:

    Tier 1 — exact      plain equality on the verbatim question, then on the
                        normalized question, via CanonicalSynonymRepository.
                        One indexed lookup, NO embedding. This is the REPLAY
                        signal (R-C1): a warm-pass repeat is a deterministic,
                        lossless exact hit — never a float comparison against
                        an ANN score, which understates the cache-hit rate the
                        experiment exists to measure.

    Tier 2 — similar    embed the verbatim question (cache-wired via
                        QuestionEmbeddingRepository, keyed by the SAME verbatim
                        text that produced the question_embedding column), then
                        cosine nearest-k via
                        SolutionSnapshotRepository.get_snapshots_by_question.
                        Its best score is RECORDED on every request for the
                        §6a threshold table, but in phase 1 it does NOT trigger
                        replay — below a perfect match, route.

Write-back (design doc §6, revised by handoff R-D2): the tagged field is rebound
with ``{ **old, **tag }`` and NEVER mutated in place, because SolutionSnapshot's
runtime_stats is a shared mutable default — an in-place tag would leak the v2
markers onto every default-constructed snapshot in the process.

Created: 2026-08-14 (CJ Flow v2 · unit C2 · Sam 🎙️)
Reuse refactor: 2026-08-15 (row 29e98243 · Tiberius 👑)
"""

import json
import time
from typing import Any, Callable, Optional

from cosa.memory.solution_snapshot import SolutionSnapshot
from cosa.memory.two_tier_question_search import (
    CacheLookup,
    TwoTierQuestionSearch,
    DEFAULT_ANN_LIMIT,
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_QUERY_FLOOR,
    _EMBEDDING_COLUMNS,
)
from cosa.rest.db.database import get_db
from cosa.rest.db.repositories.canonical_synonym_repository import CanonicalSynonymRepository
from cosa.rest.db.repositories.question_embedding_repository import QuestionEmbeddingRepository
from cosa.rest.db.repositories.solution_snapshot_repository import SolutionSnapshotRepository

# Re-exported for callers that import the result type from here (flow.py duck-types
# it; test_v2_cache imports the name). The lookup contract is unchanged.
__all__ = [ "V2Cache", "CacheLookup" ]

# Tags stamped into runtime_stats on write-back so the shared table can be
# filtered to "what v2 created" with no schema change (runtime_stats is Text).
_V2_FLOW_VERSION = "v2"
_V2_CREATED_BY   = "v2.ask"


class V2Cache( TwoTierQuestionSearch ):
    """
    v2's two-tier snapshot cache: the shared read-only lookup + tagged write-back.

    Postgres only. Inherits ``lookup`` and the ORM→snapshot marshalling from
    TwoTierQuestionSearch; adds snapshot construction and the v2-tagged write path.
    Every collaborator is injectable so the whole adapter is exercised by unit
    tests with fakes — no live Postgres and no model server on the :7999 path.
    """

    def __init__( self, embedding_provider: Any=None, snapshot_factory: Callable[ ..., Any ]=SolutionSnapshot,
                  normalizer: Any=None, gist_normalizer: Any=None, db_scope: Callable[ [], Any ]=get_db,
                  query_floor: float=DEFAULT_QUERY_FLOOR, ann_limit: int=DEFAULT_ANN_LIMIT,
                  embedding_dim: int=DEFAULT_EMBEDDING_DIM, debug: bool=False, verbose: bool=False ) -> None:
        """
        Wire the adapter's collaborators (see TwoTierQuestionSearch.__init__).

        The repository CLASSES are taken from THIS module's namespace and handed to
        the base, so a test monkeypatching ``cache.SolutionSnapshotRepository`` (etc.)
        still steers both the inherited lookup and the write path below.
        """
        super().__init__(
            embedding_provider=embedding_provider, snapshot_factory=snapshot_factory,
            normalizer=normalizer, gist_normalizer=gist_normalizer, db_scope=db_scope,
            query_floor=query_floor, ann_limit=ann_limit, embedding_dim=embedding_dim,
            synonym_repo_cls=CanonicalSynonymRepository,
            snapshot_repo_cls=SolutionSnapshotRepository,
            embedding_repo_cls=QuestionEmbeddingRepository,
            debug=debug, verbose=verbose,
        )

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
