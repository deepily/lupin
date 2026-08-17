"""
Postgres+pgvector solution snapshot manager — the first-class Postgres backend.

This module is the Postgres implementation of SolutionSnapshotManagerInterface,
lifted out of cosa/memory/lancedb_solution_manager.py where it had been living as
an `if self._use_postgres:` second path inside a LanceDB-named class.

WHY IT MOVED (Rick's ruling 29e98243, 2026-08-15): the Postgres path touches no
LanceDB, so it must not live in a LanceDB-named file. The record marshalling and
the two-tier lookup were lifted first (into cosa.memory.two_tier_question_search);
this module completes the move by giving the backend its own class and its own name.

CACHE BYPASS (design §9, carried over verbatim from the lifted path): this manager
DELIBERATELY builds no in-memory _question_lookup / _id_lookup. Every lookup queries
pgvector (HNSW) directly. That leans on index latency where the LanceDB path leaned
on in-memory exact-match hits — an expected trade-off of the design, not a surprise.
Caller-visible cache-hit semantics (same question -> same snapshot) are preserved.

IMPORT-GRAPH NOTE, stated precisely because it is easy to overclaim: this module
imports NO lancedb at module level. It is NOT yet free of lancedb transitively —
importing SolutionSnapshot still pulls the package in through
solution_snapshot.py -> embedding_manager.py -> embedding_cache_table.py, and
QuestionEmbeddingsTable does the same. Those six cache-layer modules already route
to Postgres at runtime and still import lancedb at module level; fixing them is a
separate unit of work. Measured 2026-08-17: 55 lancedb package modules resident.

Created: 2026-08-17 (Cheech, store row 5ff7b8f5) · v0.2.0
"""

import time
from threading import Lock
from typing import List, Tuple, Optional, Dict, Any

import cosa.utils.util as du
from cosa.config.configuration_manager import ConfigurationManager
from cosa.memory.snapshot_manager_interface import SolutionSnapshotManagerInterface
from cosa.memory.solution_snapshot import SolutionSnapshot
from cosa.memory.two_tier_question_search import (
    pg_hierarchical_search,
    snapshot_to_pg_record,
    pg_record_to_snapshot,
    update_canonical_synonyms,
    pg_similarity_search,
)


# Column order mirrors snapshot_to_pg_record EXACTLY (Postgres ORM columns are 1:1
# with the record keys pg_record_to_snapshot reads). Used by _pg_record_from_entity
# to marshal a SolutionSnapshot ORM entity back into that record dict.
_SNAPSHOT_RECORD_COLUMNS = (
    "id_hash", "user_id", "question", "question_normalized", "question_gist",
    "answer", "answer_conversational", "solution_summary", "thoughts", "error",
    "routing_command", "agent_class_name", "code", "solution_summary_gist",
    "code_returns", "code_example", "code_type", "programming_language",
    "language_version", "synonymous_questions", "synonymous_question_gists",
    "non_synonymous_questions", "last_question_asked", "created_date",
    "updated_date", "run_date", "runtime_stats", "replay_history", "replay_stats",
    "is_cache_hit", "answer_is_correct", "question_embedding",
    "question_normalized_embedding", "question_gist_embedding", "solution_embedding",
    "code_embedding", "thoughts_embedding", "solution_gist_embedding",
)


class PostgresSolutionManager( SolutionSnapshotManagerInterface ):
    """
    Postgres+pgvector solution snapshot manager.

    Routes every operation through SolutionSnapshotRepository. Implements the same
    interface as the file-based and LanceDB managers, so the factory can swap it in
    on the `solution snapshots manager type` config key.

    The `_pg_*` method names are retained deliberately: cosa.memory.two_tier_question_search
    drives its collaborator through `manager._pg_get_snapshots_by_question` and
    `manager._pg_record_from_entity`, so renaming them here would break the lifted
    helpers this class depends on.
    """

    def __init__( self, config: Dict[str, Any], debug: bool = False, verbose: bool = False ) -> None:
        """
        Configure the Postgres manager.

        Requires:
            - config is a dict; "table_name" is optional (Postgres has a fixed table,
              so the key is reporting-only and defaults to "solution_snapshots")
            - debug and verbose are booleans

        Ensures:
            - stores config + flags via the interface base; storage is NOT touched
            - db_path is None — there is no on-disk location under this backend, and
              publishing one would advertise a path nothing honors (decision 2b20a6d6)
            - prepares the collaborators the lifted search helpers drive

        Raises:
            - None (no required config keys; unlike the LanceDB manager there is no
              storage location to validate)
        """
        super().__init__( config, debug, verbose )

        # Reporting-only under Postgres: the table is fixed by the ORM model.
        self.table_name       = config.get( "table_name", "solution_snapshots" )
        self.storage_backend  = "postgres"

        # No on-disk location exists under this backend. Kept as an attribute because
        # get_stats()/health_check() report it and the lifted helpers read it.
        self.db_path          = None

        # Guards the resolve-then-upsert flow in save_snapshot (mirrors the TOCTOU
        # guard the LanceDB path needed).
        self._save_lock       = Lock()

        # Lazy collaborators for the hierarchical search (two_tier_question_search
        # initializes these on first use through the manager it is handed).
        self._canonical_synonyms = None
        self._normalizer         = None

        # Imported HERE rather than at module scope: QuestionEmbeddingsTable still
        # imports lancedb at module level, and this module's own import graph is
        # deliberately lancedb-free. See the module docstring's import-graph note.
        from cosa.memory.question_embeddings_table import QuestionEmbeddingsTable
        self._question_embeddings_tbl = QuestionEmbeddingsTable( debug=debug, verbose=verbose )

        _cfg                  = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self._embedding_dim   = int( _cfg.get( "embedding dimensions", default="768" ) )

        if self.debug:
            print( f"PostgresSolutionManager configured:" )
            print( f"        Backend: postgres (pgvector)" )
            print( f"          Table: {self.table_name}" )
            print( f"  Embedding dim: {self._embedding_dim}" )

    # -- record marshalling (delegates to the lifted, LanceDB-free helpers) --------

    def _snapshot_to_record( self, snapshot: SolutionSnapshot ) -> Dict[str, Any]:
        """
        Convert a SolutionSnapshot into the Postgres record dict.

        Requires:
            - snapshot is a valid SolutionSnapshot with a non-empty question

        Ensures:
            - returns a dict keyed 1:1 with the ORM columns
        """
        return snapshot_to_pg_record( self, snapshot )

    def _record_to_snapshot( self, record: Dict[str, Any] ) -> SolutionSnapshot:
        """
        Convert a Postgres record dict back into a SolutionSnapshot.

        Requires:
            - record carries every _SNAPSHOT_RECORD_COLUMNS key

        Ensures:
            - returns a SolutionSnapshot with embeddings passed to the constructor
              (never regenerated)
        """
        return pg_record_to_snapshot( self, record )

    def _ensure_list( self, value ) -> list:
        """
        Coerce a value into a list for the ARRAY/JSON columns.

        Requires:
            - value may be any type

        Ensures:
            - None -> []; str -> [str] (empty str -> []); list -> unchanged;
              anything else -> list(value), or [] when that is not possible
        """
        if value is None:
            return []
        elif isinstance( value, str ):
            return [value] if value else []
        elif isinstance( value, list ):
            return value
        else:
            # Other types (including pgvector/NumPy arrays) — a boolean test on a
            # NumPy array raises, so convert and catch rather than truth-test.
            try:
                return list( value )
            except (TypeError, ValueError):
                return []

    def _pg_record_from_entity( self, entity ) -> Dict[str, Any]:
        """
        Marshal a SolutionSnapshot ORM entity into the record dict _record_to_snapshot reads.

        Requires:
            - entity carries all _SNAPSHOT_RECORD_COLUMNS attrs
            - called INSIDE an open session (attrs read before the row detaches)

        Ensures:
            - returns a dict keyed by every _SNAPSHOT_RECORD_COLUMNS name
        """
        return { column: getattr( entity, column ) for column in _SNAPSHOT_RECORD_COLUMNS }

    def _update_canonical_synonyms( self, snapshot: SolutionSnapshot ) -> None:
        """
        Index the snapshot's verbatim / normalized / gist question forms.

        Requires:
            - snapshot is valid with id_hash set

        Ensures:
            - adds the verbatim question plus every synonymous question; no-op when
              the canonical-synonyms table is unavailable
        """
        return update_canonical_synonyms( self, snapshot )

    # -- interface implementation --------------------------------------------------

    def initialize( self ) -> None:
        """
        Mark the manager ready — cache BYPASS: builds NO in-memory lookups.

        Ensures:
            - sets _initialized True; lookups query pgvector per-call (no table scan)
        """
        self._initialized = True
        if self.debug: print( "✓ PostgresSolutionManager initialized (postgres backend, cache bypass)" )

    def reload( self ) -> None:
        """
        No-op — there is no in-memory cache to refresh; pgvector is queried live.

        Requires:
            - manager has been initialized

        Ensures:
            - raises RuntimeError if not initialized; otherwise a no-op

        Raises:
            - RuntimeError if not initialized
        """
        if not self._initialized:
            raise RuntimeError( "PostgresSolutionManager must be initialized before reload" )
        if self.debug: print( "Postgres backend reload is a no-op (cache bypass — pgvector queried live)" )

    def save_snapshot( self, snapshot: SolutionSnapshot ) -> bool:
        """
        Upsert a snapshot via SolutionSnapshotRepository.

        Resolves an existing row by VERBATIM question (reproducing the dedup-by-question
        plus Session-108 base-hash override) without an in-memory cache.

        Requires:
            - manager is initialized; snapshot is valid with a non-empty question

        Ensures:
            - inserts a new row, or updates the row keyed on the resolved id_hash
            - updates canonical synonyms; returns True on success, False on failure

        Raises:
            - RuntimeError if not initialized
            - ValueError if snapshot invalid
        """
        if not self.is_initialized():
            raise RuntimeError( "Manager must be initialized before saving snapshots" )

        if not snapshot or not snapshot.question:
            raise ValueError( "Invalid snapshot: question cannot be empty" )

        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.solution_snapshot_repository import SolutionSnapshotRepository
        from cosa.rest.db.vector_store_models import SolutionSnapshot as _PgRow

        try:
            # Lock the whole resolve-then-upsert flow (TOCTOU guard).
            with self._save_lock:
                record = self._snapshot_to_record( snapshot )
                with get_db() as session:
                    existing = session.query( _PgRow ).filter( _PgRow.question == snapshot.question ).first()
                    if existing is not None:
                        # DUPE-GUARD + Session-108 base-hash override, cache-free
                        record[ "id_hash" ] = existing.id_hash
                    id_hash = record.pop( "id_hash" )
                    SolutionSnapshotRepository( session ).upsert_snapshot( id_hash, **record )
                # Synonyms keyed on the snapshot's own id_hash — matches the prior path.
                self._update_canonical_synonyms( snapshot )
                return True
        except Exception as e:
            if self.debug: print( f"✗ Failed to save snapshot (postgres): {e}" )
            return False

    def get_snapshot_by_id( self, snapshot_id: str ) -> Optional[Any]:
        """
        Fetch a snapshot by id_hash.

        Ensures:
            - returns the SolutionSnapshot if found, else None (marshalled INSIDE the
              session to avoid DetachedInstanceError)
        """
        if not self._initialized:
            if self.debug: print( f"Manager not initialized, cannot retrieve snapshot {snapshot_id}" )
            return None

        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.solution_snapshot_repository import SolutionSnapshotRepository

        try:
            with get_db() as session:
                entity = SolutionSnapshotRepository( session ).get_snapshot_by_id( snapshot_id )
                if entity is None:
                    if self.debug: print( f"No snapshot found with id_hash: {snapshot_id}" )
                    return None
                snapshot = self._record_to_snapshot( self._pg_record_from_entity( entity ) )
                if self.debug: print( f"Found snapshot {snapshot_id}: {snapshot.question[:50]}..." )
                return snapshot
        except Exception as e:
            if self.debug: print( f"Error retrieving snapshot by id {snapshot_id}: {e}" )
            return None

    def delete_snapshot( self, question: str, delete_physical: bool = False ) -> bool:
        """
        Delete a snapshot by verbatim question and cascade its canonical synonyms.

        (delete_physical is accepted for signature parity and IGNORED — there is no
        physical file under this backend.)

        Requires:
            - manager is initialized; question is non-empty

        Ensures:
            - deletes the row + its canonical-synonym entries; True if found, else False

        Raises:
            - RuntimeError if not initialized
            - ValueError if question empty
        """
        if not self.is_initialized():
            raise RuntimeError( "Manager must be initialized before deleting snapshots" )

        if not question:
            raise ValueError( "Question cannot be empty" )

        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.solution_snapshot_repository import SolutionSnapshotRepository
        from cosa.rest.db.vector_store_models import SolutionSnapshot as _PgRow

        try:
            with get_db() as session:
                existing = session.query( _PgRow ).filter( _PgRow.question == question ).first()
                if existing is None:
                    if self.debug: print( f"Snapshot not found for: {du.truncate_string( question, 50 )}" )
                    return False
                id_hash = existing.id_hash
                SolutionSnapshotRepository( session ).delete_snapshot( id_hash )
            # Same guard as the prior path: only when the synonyms table is initialized.
            if self._canonical_synonyms is not None and self._canonical_synonyms is not False:
                deleted_count = self._canonical_synonyms.delete_by_snapshot_id( id_hash )
                if self.debug: print( f"[DELETE-DEBUG] Cleaned up {deleted_count} canonical synonym(s) for {id_hash[:8]}..." )
            if self.debug: print( f"✓ Deleted snapshot: {id_hash[:8]}..." )
            return True
        except Exception as e:
            if self.debug: print( f"✗ Failed to delete snapshot: {e}" )
            return False

    def get_snapshots_by_question( self,
                                   question: str,
                                   question_gist: Optional[str] = None,
                                   threshold_question: float = 90.0,
                                   threshold_gist: float = 90.0,
                                   limit: int = 7,
                                   debug: bool = False ) -> List[Tuple[float, Any]]:
        """
        Hierarchical two-tier question lookup against pgvector.

        Requires:
            - manager is initialized; question non-empty; thresholds in [0,100]

        Ensures:
            - returns [(similarity_pct, snapshot)] sorted descending; exact matches
              short-circuit at 100.0; empty list when no embedding / no hits

        Raises:
            - RuntimeError if not initialized
            - ValueError if question empty or a threshold is out of range
        """
        return self._pg_get_snapshots_by_question( question, question_gist, threshold_question,
                                                   threshold_gist, limit, debug )

    def _pg_get_snapshots_by_question( self,
                                       question: str,
                                       question_gist: Optional[str] = None,
                                       threshold_question: float = 90.0,
                                       threshold_gist: float = 90.0,
                                       limit: int = 7,
                                       debug: bool = False ) -> List[Tuple[float, Any]]:
        """
        Internal name kept because two_tier_question_search drives it by this name
        (its ghost-cleanup path re-enters the manager through it).

        Ensures:
            - forwards to pg_hierarchical_search, which supplies the whole contract
        """
        return pg_hierarchical_search( self, question, question_gist, threshold_question,
                                       threshold_gist, limit, debug )

    def _pg_similarity_search( self, exemplar_snapshot, embedding_attr, repo_method_name,
                               threshold, limit, exclude_self, ensure_top_result ):
        """
        Shared pgvector dot-similarity search backing the code + solution paths.

        Requires:
            - manager is initialized; exemplar_snapshot not None; threshold in [0,100]

        Ensures:
            - returns [(similarity_pct, snapshot)] sorted descending, capped at limit;
              [] on a missing / all-zero embedding

        Raises:
            - RuntimeError if not initialized
            - ValueError if exemplar_snapshot None or threshold out of range
        """
        return pg_similarity_search( self, exemplar_snapshot, embedding_attr, repo_method_name,
                                     threshold, limit, exclude_self, ensure_top_result )

    def get_snapshots_by_code_similarity( self,
                                          exemplar_snapshot,
                                          threshold: float = 85.0,
                                          limit: int = 20,
                                          exclude_self: bool = True,
                                          ensure_top_result: bool = True,
                                          debug: bool = False ) -> List[Tuple[float, Any]]:
        """
        Code-similarity search (thin wrapper over the shared pgvector search).

        Requires:
            - manager is initialized; threshold in [0,100]

        Ensures:
            - returns [(similarity_pct, snapshot)] sorted descending
        """
        return self._pg_similarity_search( exemplar_snapshot, "code_embedding",
                                           "get_snapshots_by_code_similarity",
                                           threshold, limit, exclude_self, ensure_top_result )

    def get_snapshots_by_solution_similarity( self,
                                              exemplar_snapshot,
                                              threshold: float = 85.0,
                                              limit: int = 20,
                                              exclude_self: bool = True,
                                              ensure_top_result: bool = True,
                                              debug: bool = False ) -> List[Tuple[float, Any]]:
        """
        Solution-similarity search (thin wrapper over the shared pgvector search).

        Requires:
            - manager is initialized; threshold in [0,100]

        Ensures:
            - returns [(similarity_pct, snapshot)] sorted descending
        """
        return self._pg_similarity_search( exemplar_snapshot, "solution_embedding",
                                           "get_snapshots_by_solution_similarity",
                                           threshold, limit, exclude_self, ensure_top_result )

    def get_gists( self ) -> List[str]:
        """
        Return distinct non-empty question gists (dedup preserves first-seen order).

        Requires:
            - manager is initialized

        Ensures:
            - returns the gist list, or [] on error

        Raises:
            - RuntimeError if not initialized
        """
        if not self.is_initialized():
            raise RuntimeError( "Manager must be initialized before getting gists" )

        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.solution_snapshot_repository import SolutionSnapshotRepository

        try:
            with get_db() as session:
                raw_gists = SolutionSnapshotRepository( session ).get_gists()
            gists = []
            for gist in raw_gists:
                if gist and gist not in gists:
                    gists.append( gist )
            if self.debug: print( f"Retrieved {len( gists )} unique question gists" )
            return gists
        except Exception as e:
            if self.debug: print( f"✗ Failed to get gists: {e}" )
            return []

    def get_stats( self ) -> Dict[str, Any]:
        """
        Return storage statistics. storage_size_mb is 0.0 — a shared Postgres table has
        no per-manager on-disk footprint to walk.

        Requires:
            - manager is initialized

        Ensures:
            - returns the stats dict, or an error-shaped dict on failure

        Raises:
            - RuntimeError if not initialized
        """
        if not self.is_initialized():
            raise RuntimeError( "Manager must be initialized before getting stats" )

        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.solution_snapshot_repository import SolutionSnapshotRepository

        try:
            with get_db() as session:
                total = SolutionSnapshotRepository( session ).get_stats()[ "total_snapshots" ]
            stats = {
                "total_snapshots" : total,
                "storage_size_mb" : 0.0,
                "database_path"   : self.db_path,
                "table_name"      : self.table_name,
                "backend_type"    : "postgres",
                "last_updated"    : time.strftime( "%Y-%m-%d @ %H:%M:%S %Z" )
            }
            if self.debug: print( f"Stats: {total} snapshots (postgres)" )
            return stats
        except Exception as e:
            if self.debug: print( f"✗ Failed to get stats: {e}" )
            return {
                "total_snapshots" : 0,
                "storage_size_mb" : 0.0,
                "backend_type"    : "postgres",
                "status"          : "error",
                "error"           : str( e )
            }

    def health_check( self ) -> Dict[str, Any]:
        """
        Report health — pings the store through get_stats.

        Ensures:
            - status is healthy / degraded / unhealthy; never raises
        """
        health = {
            "status"        : "healthy",
            "initialized"   : self.is_initialized(),
            "backend_type"  : "postgres",
            "database_path" : self.db_path,
            "table_name"    : self.table_name,
            "errors"        : []
        }

        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.solution_snapshot_repository import SolutionSnapshotRepository

        try:
            with get_db() as session:
                count = SolutionSnapshotRepository( session ).get_stats()[ "total_snapshots" ]
            health[ "snapshot_count" ]    = count
            health[ "connection_status" ] = "connected"
            if not self.is_initialized():
                health[ "status" ] = "degraded"
            return health
        except Exception as e:
            health[ "status" ]            = "unhealthy"
            health[ "connection_status" ] = "disconnected"
            health[ "errors" ].append( f"Health check failed: {e}" )
            return health


def quick_smoke_test():
    """Exercise the Postgres manager's contract without touching the store."""
    du.print_banner( "PostgresSolutionManager Smoke Test", prepend_nl=True )

    try:
        print( "Testing construction with an empty config..." )
        manager = PostgresSolutionManager( {}, debug=False, verbose=False )
        if manager.table_name == "solution_snapshots" and manager.db_path is None:
            print( "✓ Empty config accepted; no storage location advertised" )
        else:
            print( f"✗ Unexpected defaults: table={manager.table_name} db_path={manager.db_path}" )

        print( "\nTesting health check (before initialization)..." )
        health = manager.health_check()
        if health[ "backend_type" ] == "postgres" and not health[ "initialized" ]:
            print( f"✓ Health check reports postgres, uninitialized (status: {health['status']})" )
        else:
            print( f"✗ Health check wrong: {health}" )

        print( "\nTesting the not-initialized guards..." )
        guards = 0
        for label, call in (
            ( "reload",    lambda: manager.reload() ),
            ( "get_gists", lambda: manager.get_gists() ),
            ( "get_stats", lambda: manager.get_stats() ),
        ):
            try:
                call()
                print( f"✗ {label} did not guard on initialization" )
            except RuntimeError:
                guards += 1
        if guards == 3: print( "✓ reload / get_gists / get_stats all guard on initialization" )

        print( "\nTesting initialization (cache bypass — no store access)..." )
        manager.initialize()
        if manager.is_initialized():
            print( "✓ Initialized without touching storage" )
        else:
            print( "✗ initialize() did not set the flag" )

        print( "\nTesting reload is a no-op once initialized..." )
        manager.reload()
        print( "✓ reload returned without error" )

        print( "\nTesting _ensure_list coercions..." )
        cases = { "None": ( None, [] ), "empty str": ( "", [] ), "str": ( "a", ["a"] ),
                  "list": ( [1, 2], [1, 2] ), "tuple": ( (1, 2), [1, 2] ), "int": ( 7, [] ) }
        bad = [ name for name, ( value, want ) in cases.items() if manager._ensure_list( value ) != want ]
        if not bad: print( f"✓ All {len( cases )} coercions correct" )
        else: print( f"✗ Wrong coercion for: {bad}" )

        print( "\nTesting save_snapshot input validation..." )
        try:
            manager.save_snapshot( None )
            print( "✗ save_snapshot accepted None" )
        except ValueError:
            print( "✓ save_snapshot rejects an empty snapshot" )

        print( "\n✓ PostgresSolutionManager smoke test completed successfully" )

    except Exception as e:
        print( f"✗ Error during smoke test: {e}" )
        du.print_stack_trace( e, explanation="PostgresSolutionManager smoke test failed", caller="quick_smoke_test()" )


if __name__ == "__main__":
    quick_smoke_test()
