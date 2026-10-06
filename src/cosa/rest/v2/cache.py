"""
CJ Flow v2 cache adapter: a two-tier solution-snapshot cache with tagged write-back.

It reads and writes the Postgres and pgvector repositories directly. The two-tier lookup lives in
`cosa.memory.two_tier_question_search` as `TwoTierQuestionSearch`. V2Cache subclasses it and inherits
`lookup` and the conversion from database rows to snapshots. It adds only snapshot construction and
tagged write-back. The read path is shared with the snapshot manager rather than duplicated. V2Cache
stays read-only on lookup and is instrumented for the evaluation.

The two tiers live in the base class:

    Tier 1, exact:   plain equality on the verbatim question, then on the normalized one.
                     It goes through CanonicalSynonymRepository. It is one indexed lookup with no
                     embedding. This is the replay signal. A repeat question is a deterministic
                     and lossless exact hit. It is never a float comparison against a
                     nearest-neighbour score. That would understate the cache-hit rate the
                     experiment measures.

    Tier 2, similar: embed the verbatim question, then take the cosine nearest-k through
                     SolutionSnapshotRepository.get_snapshots_by_question. The embedding comes
                     through QuestionEmbeddingRepository, keyed by the same verbatim text that
                     produced the stored question_embedding column. The best score is recorded on
                     every request for the threshold table. For now it does not trigger
                     replay. Anything below a perfect match is routed.

Write-back rebinds the tagged field as `{ **old, **tag }` and never mutates it in place.
SolutionSnapshot's runtime_stats is a shared mutable default, so an in-place tag would leak the v2
markers onto every default-constructed snapshot in the process.
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
    v2's two-tier snapshot cache: the shared read-only lookup plus tagged write-back.

    It uses Postgres only. It inherits `lookup` and the row-to-snapshot conversion from
    TwoTierQuestionSearch. It adds snapshot construction and the v2-tagged write path. Every collaborator
    is injectable, so unit tests exercise the whole adapter with fakes. No live Postgres and no model
    server is needed on the :7999 path.
    """

    def __init__( self, embedding_provider: Any=None, snapshot_factory: Callable[ ..., Any ]=SolutionSnapshot,
                  normalizer: Any=None, gist_normalizer: Any=None, db_scope: Callable[ [], Any ]=get_db,
                  query_floor: float=DEFAULT_QUERY_FLOOR, ann_limit: int=DEFAULT_ANN_LIMIT,
                  embedding_dim: int=DEFAULT_EMBEDDING_DIM, debug: bool=False, verbose: bool=False ) -> None:
        """
        Wire the adapter's collaborators (see TwoTierQuestionSearch.__init__).

        The repository classes come from this module's namespace and are handed to the base. A test that
        monkeypatches `cache.SolutionSnapshotRepository` (or a sibling) therefore steers both the inherited
        lookup and the write path below.
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
                              routing_command: str, user_id: str, agent_class_name: str="",
                              session_id: str="", code: Optional[ list ]=None,
                              code_example: Optional[ str ]=None,
                              code_returns: Optional[ str ]=None ) -> SolutionSnapshot:
        """
        Build a replay-shaped SolutionSnapshot from a flow result's raw fields.

        This is the one place that knows how to construct a snapshot. The flow hands over raw fields and
        never builds one itself. No policy flag lives here. The write-back kill-switch is checked in exactly
        one place, `write_back`, so it cannot be checked twice and drift.

        Requires:
            - question is a non-empty string
            - user_id is a non-empty string — a row nobody owns is not writable

        Ensures:
            - returns a SolutionSnapshot with question_normalized derived via the
              adapter's normalizer, and every other field defaulted by the
              constructor (which mints the id_hash and the embeddings)
            - code, code_example and code_returns are passed on only when not None,
              so the constructor's own defaults stand for an agent that produced no code

        Raises:
            - ValueError if question is empty
            - ValueError if user_id is empty

        `user_id` has no default and a blank value is refused. A default that produces an unowned row is not
        a convenience, and an empty question already raises for the same reason. `session_id` keeps its
        default, because a write can have no live session behind it but never no owner.

        The code fields are required for replay. `SolutionSnapshot.run_code()` raises "Cannot execute empty
        code list" for every class outside CODELESS_AGENT_CLASSES. A row written without its code could
        never be served.
        """
        if not question:
            raise ValueError( "snapshot_from_result requires a non-empty question" )
        if not user_id:
            raise ValueError(
                "snapshot_from_result requires a non-empty user_id — a snapshot nobody owns "
                "cannot be filtered, attributed, or deleted by its owner"
            )
        generated = { name: value for name, value in ( ( "code", code ),
                                                       ( "code_example", code_example ),
                                                       ( "code_returns", code_returns ) )
                      if value is not None }
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
            **generated,
        )

    # ------------------------------------------------------------------ lookup

    def _exact_probes( self, synonyms: Any, question: str, question_normalized: str ) -> tuple:
        """
        The base's two exact probes, plus v2's third: exact match on the gist.

        The gist probe is one indexed equality lookup, with no embedding and no float comparison. That keeps
        `is_replay_hit` deterministic. It matches different wordings of one question.

        Requires:
            - synonyms is an open-session CanonicalSynonymRepository

        Ensures:
            - returns the base's two probes first, in the base's order, then the
              gist probe
            - nothing is normalized until the gist probe is actually reached
            - the gist probe answers None (a miss for that tier) when the question's
              gist is empty

        The gist is a tier-1 probe, not a second nearest-neighbour pass. It is already written for every
        row, because write_back computes it and registers it on the canonical-synonym row. Different
        wordings that normalize apart but gist together, such as "what's on my todo list" and "what is on my
        todo list", therefore match.

        The gist probe is last of the three. Verbatim and normalized matching are stricter, so a question
        matches its own row rather than a neighbour's row with the same gist.

        A blank gist never matches. The gist normalizer reduces a question made only of stopwords to "". That
        would match every row whose gist column is also blank and replay a stranger's answer. An empty gist
        is not a key, so the probe reports a miss for its tier.

        The gist is computed inside the probe, not before it. Computing it eagerly would make every verbatim
        and normalized hit pay for a normalization it never uses. Handing back callables means a later probe
        costs nothing when an earlier one hits.
        """
        def _gist_probe():
            question_gist = self._gist_normalizer.get_normalized_gist( question )
            if not question_gist:
                if self.debug: print( "(v2cache) tier-1c skipped: the question has no gist to key on" )
                return None
            return synonyms.find_exact_gist( question_gist )

        return super()._exact_probes( synonyms, question, question_normalized ) + ( ( "exact_gist", _gist_probe ), )

    def normalize( self, question: str ) -> str:
        """
        The normalized form of a question, from the same normalizer the store is keyed by.

        It is the companion to gist(). The query log records this field, so a second normalizer would write
        a form that no lookup could match.
        """
        return self._normalizer.normalize( question )

    def gist( self, question: str ) -> str:
        """
        The normalized gist of a question, from the same normalizer the store is keyed by.

        The flow needs this to build the agent the queue builds. The v1 path passes a real computed gist as
        `question_gist`, and the query log reads that field. A second normalizer instance would answer
        differently for the same question. Every logged row would then be quietly wrong. The flow asks the
        cache rather than growing its own normalizer.
        """
        return self._gist_normalizer.get_normalized_gist( question )

    # -------------------------------------------------------------- write-back

    def write_back( self, snapshot: SolutionSnapshot, writeback_enabled: bool=True,
                    created_at_iso: Optional[str]=None ) -> Optional[str]:
        """
        Persist a v2-created snapshot into the shared table, tagged v2.

        The write-back kill-switch is checked here and nowhere else.

        Requires:
            - snapshot is a memory SolutionSnapshot with a non-empty question and
              a set id_hash

        Ensures:
            - writeback_enabled=False records nothing and returns None (the
              deliberate off state, `v2 snapshot writeback enabled = false`)
            - writeback_enabled=True with a missing persist collaborator raises —
              a disabled write is a config choice, but an enabled write that cannot
              complete must fail loud, never silently drop
            - on a live write: runtime_stats is rebound with { **old,
              "flow_version": "v2", "created_by": "v2.ask", "created_at": <iso> }
              and never mutated in place; question_gist and question_embedding
              are computed here (off the hot path) only when absent; the row is
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
            - the same id for the same pair, so a re-registered synonym is stable
        """
        import hashlib
        return hashlib.sha256( f"{snapshot_id}|{question}".encode( "utf-8" ) ).hexdigest()
