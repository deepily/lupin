"""
LanceDB-based solution snapshot manager implementing the swappable interface.

This module provides a LanceDB implementation of the SolutionSnapshotManagerInterface,
offering native vector similarity search capabilities with performance optimization
while maintaining 100% API compatibility with the file-based implementation.
"""

import os
import json
import time
from threading import Lock
from typing import List, Tuple, Optional, Dict, Any

import lancedb
import pyarrow as pa
import numpy as np

import cosa.utils.util as du
from cosa.config.configuration_manager import ConfigurationManager
from cosa.memory.snapshot_manager_interface import (
    SolutionSnapshotManagerInterface,
    PerformanceMetrics,
    PerformanceMonitor
)
from cosa.memory.solution_snapshot import SolutionSnapshot
from cosa.memory.question_embeddings_table import QuestionEmbeddingsTable


class LanceDBSolutionManager( SolutionSnapshotManagerInterface ):
    """
    LanceDB-based solution snapshot manager with native vector search.

    Implements the SolutionSnapshotManagerInterface using LanceDB's vector database
    capabilities for high-performance semantic similarity search. Provides identical
    API to file-based implementation while leveraging native vector operations.
    """

    # Thread safety: Lock for save operations to prevent TOCTOU race conditions
    # that cause duplicate records when concurrent save_snapshot() calls occur
    _save_lock = Lock()

    def __init__( self, config: Dict[str, Any], debug: bool = False, verbose: bool = False ) -> None:
        """
        Initialize LanceDB solution snapshot manager with multi-backend support.

        Requires:
            - config["table_name"] contains target table name
            - config["storage backend"] is "local" or "gcs" (defaults to "local")
            - If backend=local: config["db_path"] must exist or be creatable
            - If backend=gcs: config["gcs_uri"] must be valid gs:// URI

        Ensures:
            - Configures connection to LanceDB database (local or GCS)
            - Prepares table schema for solution snapshots
            - Sets up performance monitoring
            - Validates backend-specific configuration

        Args:
            config: Configuration dictionary with backend, path, and table settings
            debug: Enable debug output
            verbose: Enable verbose output

        Raises:
            - KeyError if required config keys missing
            - ValueError if database path invalid or backend misconfigured
        """
        super().__init__( config, debug, verbose )

        # Validate required configuration (db_path/gcs_uri validated in _resolve_db_path)
        required_keys = ["table_name"]
        missing_keys = [key for key in required_keys if key not in config]
        if missing_keys:
            raise KeyError( f"LanceDBSolutionManager requires {missing_keys} in configuration" )

        # Store backend type and table name
        self.storage_backend = config.get( "storage backend", "local" )
        self.table_name = config["table_name"]

        # Resolve database path based on backend (local filesystem or GCS)
        self.db_path = self._resolve_db_path( config )

        # LanceDB connection and table objects
        self._db = None
        self._table = None

        # Cache for embeddings and quick lookups
        self._question_lookup = {}  # question -> id_hash mapping
        self._id_lookup = {}       # id_hash -> row mapping

        # Initialize components for hierarchical search
        self._canonical_synonyms = None  # Lazy initialization
        self._normalizer = None  # Lazy initialization
        self._question_embeddings_tbl = QuestionEmbeddingsTable( debug=debug, verbose=verbose )

        # Vector search performance tuning (nprobes for IVF index)
        self._nprobes = config.get( "nprobes", 20 )

        # Get standardized embedding dimension from config
        _cfg = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self._embedding_dim = int( _cfg.get( "embedding dimensions", default="768" ) )

        if self.debug:
            print( f"LanceDBSolutionManager configured:" )
            print( f"       Backend: {self.storage_backend}" )
            print( f"      Database: {self.db_path}" )
            print( f"         Table: {self.table_name}" )
            print( f"  Embedding dim: {self._embedding_dim}" )

    def _validate_embedding_dimensions( self, db, table_name, embedding_field_name ):
        """
        Validate that existing table's embedding dimensions match current config.

        Requires:
            - db is a valid lancedb connection
            - table_name is a string
            - embedding_field_name is the name of an embedding column in the table

        Ensures:
            - No-op if table doesn't exist (will be created fresh)
            - No-op if dimensions match
            - Drops table if dimensions mismatch (will be recreated by caller)
        """
        if table_name not in db.table_names():
            return

        table        = db.open_table( table_name )
        schema       = table.schema
        field        = schema.field( embedding_field_name )
        existing_dim = field.type.list_size

        if existing_dim == self._embedding_dim:
            return

        du.print_banner( f"EMBEDDING DIMENSION MISMATCH: {table_name}" )
        print( f"  Table schema expects: {existing_dim} dims" )
        print( f"  Current config has:   {self._embedding_dim} dims" )
        print( f"  Action: Dropping table (will be recreated with correct dimensions)" )

        db.drop_table( table_name )

    def _resolve_db_path( self, config: Dict[str, Any] ) -> str:
        """
        Resolve database path based on storage backend configuration.

        Requires:
            - config["storage backend"] is "local" or "gcs"
            - If backend=gcs: config["gcs_uri"] must be valid GCS URI
            - If backend=local: config["db_path"] must exist or be creatable

        Ensures:
            - Returns fully qualified database path for lancedb.connect()
            - Local paths have project root prefix applied if relative
            - GCS URIs validated for correct format (gs:// prefix)
            - Clear error messages for misconfiguration

        Args:
            config: Configuration dictionary with backend and path settings

        Returns:
            str: Resolved database path (local absolute path or GCS URI)

        Raises:
            ValueError: If backend unknown, required keys missing, or validation fails
        """
        backend = config.get( "storage backend", "local" )

        if backend == "gcs":
            # GCS backend - use cloud storage URI
            gcs_uri = config.get( "gcs_uri" )

            if not gcs_uri:
                raise ValueError(
                    "storage_backend=gcs requires 'gcs_uri' config key. "
                    "Example: solution snapshots lancedb gcs uri = gs://bucket/path/db.lancedb"
                )

            if not gcs_uri.startswith( "gs://" ):
                raise ValueError(
                    f"GCS URI must start with 'gs://', got: {gcs_uri}. "
                    f"Example: gs://lupin-lancedb-prod/lupin.lancedb"
                )

            if self.debug:
                print( f"[GCS Backend] Using GCS URI: {gcs_uri}" )

            return gcs_uri

        elif backend == "local":
            # Local backend - use filesystem path
            db_path = config.get( "db_path" )

            if not db_path:
                raise ValueError(
                    "storage_backend=local requires 'db_path' config key. "
                    "Example: solution snapshots lancedb path = /src/conf/long-term-memory/lupin.lancedb"
                )

            # Apply project root prefix if path is relative
            if db_path.startswith( "/src/" ):
                full_path = du.get_project_root() + db_path
            else:
                full_path = db_path

            # Validate path exists (or parent directory exists for creation)
            if not os.path.exists( full_path ):
                parent_dir = os.path.dirname( full_path )
                if not os.path.exists( parent_dir ):
                    raise ValueError(
                        f"Local database path parent directory does not exist: {parent_dir}. "
                        f"Full path: {full_path}"
                    )

            if self.debug:
                print( f"[Local Backend] Using local path: {full_path}" )

            return full_path

        else:
            raise ValueError(
                f"Unknown storage_backend: '{backend}'. Must be 'local' or 'gcs'. "
                f"Check your configuration file [config_block] section."
            )

    def _get_schema( self ) -> pa.Schema:
        """
        Get PyArrow schema for solution snapshots table.
        
        Requires:
            - Nothing
            
        Ensures:
            - Returns complete schema for solution snapshot storage
            - Includes all fields from SolutionSnapshot class
            - Optimizes vector fields for LanceDB
            
        Returns:
            PyArrow schema for solution snapshots table
        """
        return pa.schema([
            # Primary identifiers
            pa.field( "id_hash", pa.string() ),
            pa.field( "user_id", pa.string() ),
            
            # Content fields
            pa.field( "question", pa.string() ),
            pa.field( "question_normalized", pa.string() ),
            pa.field( "question_gist", pa.string() ),
            pa.field( "answer", pa.string() ),
            pa.field( "answer_conversational", pa.string() ),
            pa.field( "solution_summary", pa.string() ),
            pa.field( "thoughts", pa.string() ),
            pa.field( "error", pa.string() ),
            pa.field( "routing_command", pa.string() ),
            pa.field( "agent_class_name", pa.string() ),  # e.g., "MathAgent", "CalendarAgent"

            # Code execution data
            pa.field( "code", pa.list_( pa.string() ) ),
            pa.field( "solution_summary_gist", pa.string() ),  # Gist of solution_summary
            pa.field( "code_returns", pa.string() ),
            pa.field( "code_example", pa.string() ),
            pa.field( "code_type", pa.string() ),
            pa.field( "programming_language", pa.string() ),
            pa.field( "language_version", pa.string() ),
            
            # Synonymous questions (JSON serialized)
            pa.field( "synonymous_questions", pa.string() ),
            pa.field( "synonymous_question_gists", pa.string() ),
            pa.field( "non_synonymous_questions", pa.list_( pa.string() ) ),
            pa.field( "last_question_asked", pa.string() ),
            
            # Temporal data
            pa.field( "created_date", pa.string() ),
            pa.field( "updated_date", pa.string() ),
            pa.field( "run_date", pa.string() ),
            pa.field( "runtime_stats", pa.string() ),  # JSON serialized

            # Replay tracking for Time Saved Dashboard
            pa.field( "replay_history", pa.string() ),   # JSON serialized list
            pa.field( "replay_stats", pa.string() ),     # JSON serialized dict
            pa.field( "is_cache_hit", pa.bool_() ),
            pa.field( "answer_is_correct", pa.string() ),  # JSON tri-state: "true", "false", "null"

            # Vector embeddings (configurable dimensions: 768 for local, 1536 for openai)
            pa.field( "question_embedding", pa.list_( pa.float32(), self._embedding_dim ) ),
            pa.field( "question_normalized_embedding", pa.list_( pa.float32(), self._embedding_dim ) ),
            pa.field( "question_gist_embedding", pa.list_( pa.float32(), self._embedding_dim ) ),
            pa.field( "solution_embedding", pa.list_( pa.float32(), self._embedding_dim ) ),
            pa.field( "code_embedding", pa.list_( pa.float32(), self._embedding_dim ) ),
            pa.field( "thoughts_embedding", pa.list_( pa.float32(), self._embedding_dim ) ),
            pa.field( "solution_gist_embedding", pa.list_( pa.float32(), self._embedding_dim ) ),
        ])

    def _snapshot_to_record( self, snapshot: SolutionSnapshot ) -> Dict[str, Any]:
        """
        Convert SolutionSnapshot to LanceDB record format.
        
        Requires:
            - snapshot is valid SolutionSnapshot instance
            - snapshot.question is not empty
            
        Ensures:
            - Returns dictionary compatible with LanceDB schema
            - Handles missing fields gracefully with defaults
            - Converts embeddings to proper format
            
        Args:
            snapshot: SolutionSnapshot to convert
            
        Returns:
            Dictionary record for LanceDB insertion
            
        Raises:
            - ValueError if snapshot invalid
        """
        if not snapshot or not snapshot.question:
            raise ValueError( "Invalid snapshot: question cannot be empty" )

        # Preserve original snapshot ID hash (SHA256 of timestamp)
        id_hash = snapshot.id_hash
        
        # Helper function to ensure vector is proper format
        def normalize_embedding( embedding ):
            dim = self._embedding_dim
            if not embedding:
                return [0.0] * dim
            if isinstance( embedding, list ):
                if len( embedding ) == dim:
                    return [float( x ) for x in embedding]
                elif len( embedding ) < dim:
                    # Pad with zeros
                    return [float( x ) for x in embedding] + [0.0] * ( dim - len( embedding ) )
                else:
                    # Truncate
                    return [float( x ) for x in embedding[ :dim ]]
            return [0.0] * dim
        
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

            # Code execution data - ensure code is always a list for LanceDB schema compatibility
            "code": self._ensure_list( getattr( snapshot, 'code', [] ) ),
            "solution_summary_gist": getattr( snapshot, 'solution_summary_gist', '' ) or '',  # Gist of solution_summary
            "code_returns": getattr( snapshot, 'code_returns', '' ) or '',
            "code_example": getattr( snapshot, 'code_example', '' ) or '',
            "code_type": getattr( snapshot, 'code_type', '' ) or '',
            "programming_language": getattr( snapshot, 'programming_language', 'python' ),
            "language_version": getattr( snapshot, 'language_version', '3.10' ),
            
            # Synonymous questions (convert dict to JSON string)
            "synonymous_questions": json.dumps( getattr( snapshot, 'synonymous_questions', {} ) ),
            "synonymous_question_gists": json.dumps( getattr( snapshot, 'synonymous_question_gists', {} ) ),
            "non_synonymous_questions": self._ensure_list( getattr( snapshot, 'non_synonymous_questions', [] ) ),
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
    
    def _ensure_list( self, value ) -> list:
        """
        Ensure value is a list for LanceDB schema compatibility.
        
        Handles the common case where test suite passes strings instead of lists
        for fields that expect list types in the PyArrow schema.
        
        Requires:
            - value can be any type
            
        Ensures:
            - Returns a list
            - Strings are converted to single-item lists
            - Lists are returned as-is
            - None/empty values become empty lists
            
        Raises:
            - None
        """
        if value is None:
            return []
        elif isinstance( value, str ):
            return [value] if value else []
        elif isinstance( value, list ):
            return value
        else:
            # For other types (including NumPy arrays from LanceDB), try to convert to list
            # Note: Cannot use 'if value' check here - NumPy arrays raise ValueError in boolean context
            try:
                return list( value )
            except (TypeError, ValueError):
                return []
    
    def _record_to_snapshot( self, record: Dict[str, Any] ) -> SolutionSnapshot:
        """
        Convert LanceDB record back to SolutionSnapshot.

        Requires:
            - record contains all required fields
            - Vector fields are in proper format

        Ensures:
            - Returns valid SolutionSnapshot instance
            - Handles JSON deserialization
            - Preserves all original data
            - CRITICAL: Passes embeddings to constructor to prevent regeneration (977ms savings)

        Args:
            record: LanceDB record dictionary

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
            code=self._ensure_list( record.get( "code", [] ) ),  # Ensure code is list, not NumPy array
            solution_summary_gist=record.get( "solution_summary_gist", "" ),  # Gist of solution_summary
            code_returns=record.get( "code_returns", "" ),
            code_example=record.get( "code_example", "" ),
            code_type=record.get( "code_type", "" ),
            programming_language=record.get( "programming_language", "python" ),
            language_version=record.get( "language_version", "3.10" ),
            # CRITICAL: Pass embeddings to constructor to prevent regeneration
            question_embedding=self._ensure_list( record.get( "question_embedding", [] ) ),
            question_normalized_embedding=self._ensure_list( record.get( "question_normalized_embedding", [] ) ),
            question_gist_embedding=self._ensure_list( record.get( "question_gist_embedding", [] ) ),
            solution_embedding=self._ensure_list( record.get( "solution_embedding", [] ) ),
            code_embedding=self._ensure_list( record.get( "code_embedding", [] ) ),
            thoughts_embedding=self._ensure_list( record.get( "thoughts_embedding", [] ) ),
            solution_gist_embedding=self._ensure_list( record.get( "solution_gist_embedding", [] ) ),
            # Replay tracking for Time Saved Dashboard
            replay_history=replay_history,
            replay_stats=replay_stats,
            is_cache_hit=is_cache_hit,
            answer_is_correct=answer_is_correct
        )

        return snapshot
    
    def initialize( self ) -> None:
        """
        Initialize LanceDB connection and create/open solution snapshots table.
        
        Requires:
            - Database path is valid and accessible
            - Sufficient permissions for database operations
            
        Ensures:
            - Establishes connection to LanceDB database
            - Creates table if it doesn't exist
            - Loads existing data for quick lookups
            - Sets _initialized flag to True
            
        Raises:
            - ConnectionError if database inaccessible
            - PermissionError if insufficient access rights
            - ValueError if configuration invalid
        """
        monitor = PerformanceMonitor( "initialization" )
        monitor.start()
        
        try:
            if self.debug:
                print( f"Connecting to LanceDB at: {self.db_path}" )
            
            # Connect to database
            self._db = lancedb.connect( self.db_path )

            # Validate existing table dimensions match config before opening
            self._validate_embedding_dimensions( self._db, self.table_name, "question_embedding" )

            # Check if table exists
            existing_tables = self._db.table_names()
            
            if self.table_name in existing_tables:
                # Open existing table
                self._table = self._db.open_table( self.table_name )

                # Ensure scalar index exists on id_hash (safe if already present)
                # Critical for merge_insert performance and correctness
                try:
                    self._table.create_scalar_index( "id_hash", replace=True )
                    if self.debug:
                        print( f"✓ Verified/created scalar index on id_hash" )
                except Exception as idx_error:
                    if self.debug:
                        print( f"⚠ Could not create index (may already exist): {idx_error}" )

                if self.debug:
                    print( f"✓ Opened existing table: {self.table_name}" )
            else:
                # Create new table with explicit schema (not from data to avoid type inference issues)
                schema = self._get_schema()
                
                # Create table with explicit schema - this ensures correct list item types
                self._table = self._db.create_table( self.table_name, schema=schema )

                # Create scalar index on id_hash for merge_insert operations
                # LanceDB merge_insert requires scalar index for reliable matching
                self._table.create_scalar_index( "id_hash", replace=True )

                if self.debug:
                    print( f"✓ Created new table: {self.table_name}" )
                    print( f"✓ Created scalar index on id_hash column" )
            
            # Load existing data for caching
            snapshot_count = 0
            try:
                # Get count of existing records
                # Get all rows using to_arrow() - efficient full table access in LanceDB 0.23.0
                result = self._table.to_arrow().to_pandas()
                snapshot_count = len( result )
                
                # Build lookup caches
                self._question_lookup.clear()
                self._id_lookup.clear()
                
                for _, row in result.iterrows():
                    question = row["question"]
                    id_hash = row["id_hash"]
                    
                    self._question_lookup[question] = id_hash
                    self._id_lookup[id_hash] = dict( row )
                
                if self.debug:
                    print( f"✓ Loaded {snapshot_count} existing snapshots into cache" )
                    
            except Exception as cache_error:
                if self.debug:
                    print( f"⚠ Cache loading failed (table may be empty): {cache_error}" )
                snapshot_count = 0
            
            self._initialized = True
            
            if self.debug:
                print( f"✓ LanceDB manager initialized with {snapshot_count} snapshots" )
                
        except Exception as e:
            self._initialized = False
            if self.debug:
                print( f"✗ Failed to initialize LanceDB manager: {e}" )
            raise
        finally:
            monitor.stop()
        
        # Initialization complete, no return value needed

    def reload( self ) -> None:
        """
        Reload/refresh data from LanceDB database.

        Requires:
            - Manager has been previously initialized
            - Database connection is accessible

        Ensures:
            - Refreshes connection to LanceDB database
            - Reloads all cached data from persistent storage
            - Updates internal lookup dictionaries
            - Can be called multiple times safely

        Raises:
            - RuntimeError if manager not initialized
            - ConnectionError if database unavailable
            - PermissionError if insufficient access rights
        """
        if not self._initialized:
            raise RuntimeError( "LanceDBSolutionManager must be initialized before reload" )

        if self.debug:
            print( f"Reloading LanceDB solution manager from {self.db_path}..." )

        # Re-use existing initialize logic which handles:
        # - Database reconnection
        # - Cache refreshing
        # - Loading existing data
        try:
            # Store previous state for debugging
            old_count = len( self._question_lookup ) if hasattr( self, '_question_lookup' ) else 0

            # Clear existing caches before reload
            self._question_lookup.clear()
            self._id_lookup.clear()

            # Reconnect and reload data (reuse initialize logic)
            self._db = lancedb.connect( self.db_path )
            self._table = self._db.open_table( self.table_name )

            # Reload data into caches
            try:
                result = self._table.to_pandas()
                snapshot_count = len( result )

                for _, row in result.iterrows():
                    question = row["question"]
                    id_hash = row["id_hash"]

                    self._question_lookup[question] = id_hash
                    self._id_lookup[id_hash] = dict( row )

                if self.debug:
                    print( f"✓ Reloaded {snapshot_count} snapshots (was {old_count})" )

            except Exception as cache_error:
                if self.debug:
                    print( f"⚠ Cache reload failed (table may be empty): {cache_error}" )

        except Exception as e:
            if self.debug:
                print( f"✗ Failed to reload LanceDB manager: {e}" )
            raise

    def save_snapshot( self, snapshot: SolutionSnapshot ) -> bool:
        """
        Save snapshot to LanceDB table using context-aware upsert operations.

        Performs INSERT for new snapshots or UPDATE for existing ones. This is
        the primary method for persisting snapshot state including runtime_stats.

        Requires:
            - Manager is initialized
            - snapshot is valid SolutionSnapshot
            - snapshot.question is not empty

        Ensures:
            - New snapshots are inserted using table.add()
            - Existing snapshots are updated using merge_insert
            - Cache is updated with snapshot data
            - Returns True if successful

        Raises:
            - RuntimeError if not initialized
            - ValueError if snapshot invalid
        """
        if not self.is_initialized():
            raise RuntimeError( "Manager must be initialized before saving snapshots" )

        if not snapshot or not snapshot.question:
            raise ValueError( "Invalid snapshot: question cannot be empty" )

        try:
            # CRITICAL: Lock the entire check-then-insert flow to prevent TOCTOU race conditions.
            # Without this lock, two concurrent calls for the same question can both pass
            # the cache and DB checks before either INSERT commits, creating duplicate records.
            # See: 2025.12 duplicate snapshot investigation - f4aa24b5 and 2ea576fa bug
            with self._save_lock:
                # Check if snapshot already exists (cache-based fast path)
                question = snapshot.question
                exists_in_cache = self._check_snapshot_exists( question )

                if not exists_in_cache:
                    # Cache miss - but record might still exist in DB due to race conditions
                    # (e.g., cache invalidated during merge, or double-submission)
                    # Do a direct DB check to prevent duplicate INSERTs
                    existing_records = self._check_db_for_question( question )

                    if existing_records:
                        # DUPE-GUARD: Found in DB but not cache - restore cache and UPDATE
                        if self.debug: print( f"[DUPE-GUARD] Found existing record in DB (cache miss): {du.truncate_string( question, 50 )}" )
                        # Restore cache entry
                        self._question_lookup[question] = existing_records[0]["id_hash"]
                        self._id_lookup[existing_records[0]["id_hash"]] = existing_records[0]
                        return self._update_existing_snapshot( snapshot )

                    # Truly new snapshot - use direct INSERT
                    if self.debug:
                        verbatim = snapshot.last_question_asked or snapshot.question or question
                        print( f"Inserting new snapshot for: {du.truncate_string( verbatim, 50 )}" )
                    return self._insert_new_snapshot( snapshot )
                else:
                    # Existing snapshot in cache - determine best update approach
                    if self.debug:
                        print( f"Updating existing snapshot for: {du.truncate_string( question, 50 )}" )
                    return self._update_existing_snapshot( snapshot )

        except Exception as e:
            if self.debug:
                print( f"✗ Failed to save snapshot: {e}" )
            return False
    
    def _check_snapshot_exists( self, question: str ) -> bool:
        """
        Check if snapshot exists using cache for fast lookup.

        Requires:
            - question is non-empty string

        Ensures:
            - Returns True if snapshot exists
            - Returns False if snapshot doesn't exist

        Raises:
            - None
        """
        return question in self._question_lookup

    def _check_db_for_question( self, question: str ) -> list:
        """
        Check LanceDB directly for question (bypass cache).

        Used as fallback when cache miss occurs, to catch race conditions
        where cache was invalidated but record exists in DB.

        Requires:
            - question is non-empty string
            - Table is initialized

        Ensures:
            - Returns list of matching records (empty if not found)
            - Does NOT modify cache

        Raises:
            - None (returns empty list on error)
        """
        try:
            # Escape single quotes in question for SQL WHERE clause
            escaped_question = question.replace( "'", "''" )
            results = self._table.search().where( f"question = '{escaped_question}'" ).limit( 1 ).to_list()
            return results
        except Exception as e:
            if self.debug:
                print( f"[DUPE-GUARD] DB check failed: {e}" )
            return []

    def _insert_new_snapshot( self, snapshot: SolutionSnapshot ) -> bool:
        """
        Insert a brand new snapshot using direct LanceDB add.
        
        Requires:
            - snapshot is valid SolutionSnapshot
            - snapshot doesn't exist in table
            
        Ensures:
            - Snapshot inserted using table.add()
            - Cache updated with new snapshot
            - Returns True if successful
            
        Raises:
            - Exception if insert fails
        """
        try:
            record = self._snapshot_to_record( snapshot )
            
            # Use direct insert for new snapshots
            import pandas as pd
            df = pd.DataFrame( [record] )
            self._table.add( df )
            
            # Update cache
            id_hash = record["id_hash"]
            self._question_lookup[snapshot.question] = id_hash
            self._id_lookup[id_hash] = record
            
            if self.debug:
                print( f"  ✓ Inserted new snapshot with id_hash: {id_hash[:8]}..." )

            # Update canonical synonyms table for hierarchical search
            self._update_canonical_synonyms( snapshot )

            return True
            
        except Exception as e:
            if self.debug:
                print( f"  ✗ Insert failed: {e}" )
            raise e
    
    def _update_existing_snapshot( self, snapshot: SolutionSnapshot ) -> bool:
        """
        Update existing snapshot using appropriate LanceDB operation.

        Determines the most efficient update method based on what fields changed:
        - Runtime stats only: Use table.update() for targeted field update
        - Multiple fields: Use merge_insert for full replacement

        Requires:
            - snapshot is valid SolutionSnapshot
            - snapshot exists in table

        Ensures:
            - Snapshot updated using optimal LanceDB operation
            - Cache updated with new data
            - Returns True if successful

        Raises:
            - Exception if update fails
        """
        try:
            # Get existing snapshot's id_hash from cache
            existing_id_hash = self._question_lookup[snapshot.question]
            existing_record  = self._id_lookup[existing_id_hash]

            # Session 108: DON'T modify snapshot.id_hash directly!
            # The snapshot object may be shared (e.g., in the done queue) and modifying it
            # would break user-job tracking which relies on the compound hash.
            # Instead, pass the existing_id_hash to _full_replace_snapshot which will
            # use it for the database record without modifying the source object.
            # See: 2025.12 duplicate snapshot investigation + Session 108 compound hash fix
            return self._full_replace_snapshot( snapshot, db_id_hash=existing_id_hash )

        except Exception as e:
            if self.debug: print( f"  ✗ Update failed: {e}" )
            raise e
    
    def _full_replace_snapshot( self, snapshot: SolutionSnapshot, db_id_hash: str = None ) -> bool:
        """
        Replace entire snapshot using LanceDB merge_insert operation.

        Uses the proper LanceDB merge_insert API which handles atomicity
        and persistence correctly, unlike the old delete/add pattern.

        Requires:
            - snapshot is valid SolutionSnapshot
            - db_id_hash (optional) overrides record's id_hash for database matching

        Ensures:
            - Snapshot replaced using merge_insert
            - Cache updated with new data
            - Returns True if successful

        Raises:
            - Exception if merge fails
        """
        try:
            record = self._snapshot_to_record( snapshot )

            # Session 108: Use provided db_id_hash for database operations if available
            # This allows the snapshot object to keep its compound hash (for user tracking)
            # while the database uses the base hash for merge matching
            if db_id_hash:
                record["id_hash"] = db_id_hash
            id_hash = record["id_hash"]

            # DEBUG: Print pre-merge stats
            if self.debug:
                pre_stats = snapshot.runtime_stats
                print( f"[STATS DEBUG] PRE-MERGE for {id_hash[:8]}...:" )
                print( f"  run_count = {pre_stats.get('run_count', -1)}" )
                print( f"  last_run_ms = {pre_stats.get('last_run_ms', 0)}" )
                print( f"  total_ms = {pre_stats.get('total_ms', 0)}" )

            # Invalidate cache BEFORE merge to force fresh DB read after
            # This prevents cache from masking persistence failures
            if id_hash in self._id_lookup:
                del self._id_lookup[id_hash]
            if snapshot.question in self._question_lookup:
                del self._question_lookup[snapshot.question]

            if self.debug: print( f"[CACHE DEBUG] Invalidated cache for {id_hash[:8]}... before merge" )

            # Use proper LanceDB merge_insert for atomic upsert
            (
                self._table.merge_insert( "id_hash" )
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .execute( [record] )
            )

            # DEBUG: Verify stats persisted by reading back from database
            if self.debug:
                fresh_records = self._table.search().where( f"id_hash = '{id_hash}'" ).limit( 1 ).to_list()
                if fresh_records:
                    import json
                    post_stats = json.loads( fresh_records[0]["runtime_stats"] )
                    print( f"[STATS DEBUG] POST-MERGE from DB:" )
                    print( f"  run_count = {post_stats.get('run_count', -1)}" )
                    print( f"  last_run_ms = {post_stats.get('last_run_ms', 0)}" )
                    print( f"  total_ms = {post_stats.get('total_ms', 0)}" )

                    if post_stats.get("run_count") != pre_stats.get("run_count"):
                        print( f"[STATS DEBUG] ⚠️ STATS NOT PERSISTED!" )
                        print( f"  Expected run_count: {pre_stats.get('run_count')}" )
                        print( f"  Got run_count: {post_stats.get('run_count')}" )
                    else:
                        print( f"[STATS DEBUG] ✓ Stats successfully persisted to database" )

            # Repopulate cache from fresh DB read (not stale in-memory record)
            # This ensures cache reflects actual persisted data
            fresh_records = self._table.search().where( f"id_hash = '{id_hash}'" ).limit( 1 ).to_list()
            if fresh_records:
                fresh_record = fresh_records[0]
                self._id_lookup[id_hash] = dict( fresh_record )
                self._question_lookup[snapshot.question] = id_hash

                if self.debug:
                    print( f"[CACHE DEBUG] Repopulated cache from DB with fresh data" )
            else:
                # Fallback: use in-memory record if DB read fails (should not happen)
                self._id_lookup[id_hash] = record
                self._question_lookup[snapshot.question] = id_hash

                if self.debug:
                    print( f"[CACHE DEBUG] ⚠ DB read failed, using in-memory record" )

            # Verify cache consistency in debug mode
            if self.debug: self._verify_cache_consistency( id_hash )

            if self.debug: print( f"  ✓ Merge completed for id_hash: {id_hash[:8]}..." )

            # Update canonical synonyms table for hierarchical search
            self._update_canonical_synonyms( snapshot )

            return True
            
        except Exception as e:
            if self.debug: print( f"  ✗ Merge failed: {e}" )
            raise e

    def _verify_cache_consistency( self, id_hash: str ) -> bool:
        """
        Verify cache entry matches database for given id_hash.

        Requires:
            - id_hash is valid hash string
            - Manager is initialized

        Ensures:
            - Returns True if cache matches DB
            - Returns False if mismatch detected
            - Logs discrepancies in debug mode

        Args:
            id_hash: The snapshot ID hash to verify

        Returns:
            True if consistent, False if mismatch
        """
        try:
            # Read from database
            db_records = self._table.search().where( f"id_hash = '{id_hash}'" ).limit( 1 ).to_list()

            if not db_records:
                if self.debug:
                    print( f"[CONSISTENCY] ⚠ DB has no record for {id_hash[:8]}... but cache does" )
                return False

            db_record = db_records[0]

            # Compare with cache
            if id_hash not in self._id_lookup:
                if self.debug:
                    print( f"[CONSISTENCY] ⚠ Cache missing entry for {id_hash[:8]}... but DB has it" )
                return False

            cached_record = self._id_lookup[id_hash]

            # Compare critical fields
            import json
            db_stats = json.loads( db_record.get( "runtime_stats", "{}" ) )
            cached_stats = json.loads( cached_record.get( "runtime_stats", "{}" ) )

            if db_stats.get( "run_count" ) != cached_stats.get( "run_count" ):
                if self.debug:
                    print( f"[CONSISTENCY] ✗ MISMATCH for {id_hash[:8]}...:" )
                    print( f"  DB run_count: {db_stats.get('run_count')}" )
                    print( f"  Cache run_count: {cached_stats.get('run_count')}" )
                return False

            if self.debug:
                print( f"[CONSISTENCY] ✓ Cache consistent with DB for {id_hash[:8]}..." )

            return True

        except Exception as e:
            if self.debug:
                print( f"[CONSISTENCY] Error during verification: {e}" )
            return False

    def _update_canonical_synonyms( self, snapshot: SolutionSnapshot ) -> None:
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
        if not self._canonical_synonyms or self._canonical_synonyms is False:
            if self.debug and self.verbose:
                print( "  ⓘ CanonicalSynonyms not available, skipping synonym update" )
            return

        # Add the primary question (last_question_asked)
        if snapshot.last_question_asked:
            try:
                self._canonical_synonyms.add_synonym(
                    snapshot_id=snapshot.id_hash,
                    question_verbatim=snapshot.last_question_asked,
                    confidence_score=100.0,
                    source="runtime"
                )
                if self.debug:
                    print( f"  ✓ Added primary question to canonical synonyms: '{snapshot.last_question_asked[:50]}...'" )
            except Exception as e:
                if self.debug:
                    print( f"  ⚠ Failed to add primary question to synonyms: {e}" )

        # Skip synonymous_questions - contains historical corruption from deprecated remove_non_alphanumerics()
        # The deprecated method stripped math operators: "What's 2+2?" → "whats 22"
        # Future synonyms will be added correctly now that add_synonymous_question() uses Normalizer.normalize()
        # Canonical table will rebuild with correct normalization as users ask questions
        if self.debug and self.verbose:
            if hasattr( snapshot, 'synonymous_questions' ) and snapshot.synonymous_questions:
                print( f"  ⓘ Skipping {len( snapshot.synonymous_questions )} synonymous questions (legacy corrupted data)" )

    def get_snapshot_by_id( self, snapshot_id: str ) -> Optional[Any]:
        """
        Get snapshot by ID hash.

        Requires:
            - snapshot_id is a valid ID hash string
            - Storage backend is initialized

        Ensures:
            - Returns SolutionSnapshot if found
            - Returns None if not found
            - No side effects on storage

        Args:
            snapshot_id: The ID hash of the snapshot to retrieve

        Returns:
            SolutionSnapshot instance if found, None otherwise
        """
        if not self._initialized:
            if self.debug:
                print( f"Manager not initialized, cannot retrieve snapshot {snapshot_id}" )
            return None

        try:
            # Search for snapshot by id_hash
            results = self._table.search().where( f"id_hash = '{snapshot_id}'" ).limit( 1 ).to_list()

            if results and len( results ) > 0:
                # Convert row data back to SolutionSnapshot
                row = results[0]
                snapshot = self._record_to_snapshot( row )

                if self.debug:
                    print( f"Found snapshot {snapshot_id}: {snapshot.question[:50]}..." )

                return snapshot
            else:
                if self.debug:
                    print( f"No snapshot found with id_hash: {snapshot_id}" )
                return None

        except Exception as e:
            if self.debug:
                print( f"Error retrieving snapshot by id {snapshot_id}: {e}" )
            return None

    def delete_snapshot( self, question: str, delete_physical: bool = False ) -> bool:
        """
        Delete snapshot by question.
        
        Requires:
            - Manager is initialized
            - question is non-empty string
            
        Ensures:
            - Snapshot removed from LanceDB table if exists
            - Cache updated to remove snapshot
            - Returns True if found and deleted
            
        Raises:
            - RuntimeError if not initialized
            - ValueError if question empty
        """
        if not self.is_initialized():
            raise RuntimeError( "Manager must be initialized before deleting snapshots" )
        
        if not question:
            raise ValueError( "Question cannot be empty" )
        
        try:
            # Use verbatim question for lookup (cache stores original case)
            if self.debug:
                print( f"[DELETE-DEBUG] Looking up question: '{question}'" )
                print( f"[DELETE-DEBUG] Cache size: {len(self._question_lookup)} questions" )

            # Check cache first
            if question not in self._question_lookup:
                # FALLBACK: Check DB directly (cache may be stale)
                if self.debug:
                    print( f"[DELETE-DEBUG] Cache miss - checking DB directly..." )

                existing_records = self._check_db_for_question( question )

                if not existing_records:
                    if self.debug:
                        print( f"[DELETE-DEBUG] Not found in cache OR DB" )
                        print( f"Snapshot not found for: {du.truncate_string( question, 50 )}" )
                    return False

                # Found in DB but not cache - get id_hash from DB record
                id_hash = existing_records[0]["id_hash"]
                if self.debug:
                    print( f"[DELETE-DEBUG] Found in DB (cache miss): {id_hash[:8]}..." )
            else:
                id_hash = self._question_lookup[question]
                if self.debug:
                    print( f"[DELETE-DEBUG] Found in cache: {id_hash[:8]}..." )

            # Delete from table
            self._table.delete( f"id_hash = '{id_hash}'" )

            # Clean up associated canonical_synonyms entries to prevent ghost snapshots
            if self._canonical_synonyms is not None and self._canonical_synonyms is not False:
                deleted_count = self._canonical_synonyms.delete_by_snapshot_id( id_hash )
                if self.debug:
                    print( f"[DELETE-DEBUG] Cleaned up {deleted_count} canonical synonym(s) for {id_hash[:8]}..." )

            # Update cache (remove if present)
            if question in self._question_lookup:
                del self._question_lookup[question]
            if id_hash in self._id_lookup:
                del self._id_lookup[id_hash]

            if self.debug:
                print( f"✓ Deleted snapshot: {id_hash[:8]}..." )

            return True

        except Exception as e:
            if self.debug:
                print( f"✗ Failed to delete snapshot: {e}" )
            return False
    
    def get_snapshots_by_question( self,
                                  question: str,
                                  question_gist: Optional[str] = None,
                                  threshold_question: float = 90.0,
                                  threshold_gist: float = 90.0,
                                  limit: int = 7,
                                  debug: bool = False ) -> List[Tuple[float, Any]]:
        """
        Search for snapshots by question using hierarchical exact match then similarity.

        Implements three-level hierarchical search:
        1. Exact verbatim match (instant, no embeddings)
        2. Exact normalized match (instant, no embeddings)
        3. Exact gist match (instant, no embeddings)
        4. Similarity search (fallback, uses embeddings)

        Requires:
            - Manager is initialized
            - question is non-empty string
            - thresholds are between 0.0 and 100.0

        Ensures:
            - Returns list of (similarity_score, snapshot) tuples
            - Results sorted by similarity descending
            - Exact matches return immediately (no embeddings computed)
            - Falls back to similarity search only if needed
            - Performance metrics included

        Raises:
            - RuntimeError if not initialized
            - ValueError if parameters invalid
        """
        if not self.is_initialized():
            raise RuntimeError( "Manager must be initialized before searching" )

        if not question:
            raise ValueError( "Question cannot be empty" )

        if not (0.0 <= threshold_question <= 100.0) or not (0.0 <= threshold_gist <= 100.0):
            raise ValueError( "Thresholds must be between 0.0 and 100.0" )

        monitor = PerformanceMonitor( "get_snapshots_by_question" )
        monitor.start()

        try:
            # Initialize hierarchical search components if needed
            if self._canonical_synonyms is None:
                try:
                    from cosa.memory.canonical_synonyms_table import CanonicalSynonymsTable
                    self._canonical_synonyms = CanonicalSynonymsTable( db_path=self.db_path, debug=self.debug, verbose=self.verbose )
                    if self.debug:
                        print( "Initialized CanonicalSynonyms for hierarchical search" )
                except Exception as e:
                    if self.debug:
                        print( f"Could not initialize CanonicalSynonyms, using direct search: {e}" )
                    self._canonical_synonyms = False  # Mark as unavailable

            if self._normalizer is None:
                try:
                    from cosa.memory.normalizer import Normalizer
                    self._normalizer = Normalizer()
                    if self.debug:
                        print( "Initialized Normalizer for hierarchical search" )
                except Exception as e:
                    if self.debug:
                        print( f"Could not initialize Normalizer: {e}" )
                    self._normalizer = False

            # HIERARCHICAL SEARCH IMPLEMENTATION

            # Level 1: Exact verbatim match in CanonicalSynonyms
            if self._canonical_synonyms and self._canonical_synonyms is not False:
                snapshot_id = self._canonical_synonyms.find_exact_verbatim( question )
                if snapshot_id:
                    if self.debug:
                        print( f"✓ LEVEL 1: Exact verbatim match found for snapshot: {snapshot_id}" )
                    snapshot = self.get_snapshot_by_id( snapshot_id )
                    if snapshot:
                        monitor.stop()
                        return [( 100.0, snapshot )]
                    else:
                        # Ghost snapshot: synonym points to non-existent solution — auto-heal
                        print( f"[GHOST] WARNING: Level 1 synonym points to missing snapshot {snapshot_id[:8]}... — auto-cleaning" )
                        self._canonical_synonyms.delete_by_snapshot_id( snapshot_id )

                # Level 2: Exact normalized match
                if self._normalizer and self._normalizer is not False:
                    question_normalized = self._normalizer.normalize( question )
                    snapshot_id = self._canonical_synonyms.find_exact_normalized( question_normalized )
                    if snapshot_id:
                        if self.debug:
                            print( f"✓ LEVEL 2: Exact normalized match found for snapshot: {snapshot_id}" )
                        snapshot = self.get_snapshot_by_id( snapshot_id )
                        if snapshot:
                            monitor.stop()
                            return [( 100.0, snapshot )]
                        else:
                            # Ghost snapshot: synonym points to non-existent solution — auto-heal
                            print( f"[GHOST] WARNING: Level 2 synonym points to missing snapshot {snapshot_id[:8]}... — auto-cleaning" )
                            self._canonical_synonyms.delete_by_snapshot_id( snapshot_id )

                # Level 3: Exact gist match — DISABLED (top-1 + confirm strategy)
                # Gist text still generated for display/logging, but not used for matching
                # if question_gist:
                #     snapshot_id = self._canonical_synonyms.find_exact_gist( question_gist )
                #     if snapshot_id:
                #         if self.debug:
                #             print( f"✓ LEVEL 3: Exact gist match found for snapshot: {snapshot_id}" )
                #         snapshot = self.get_snapshot_by_id( snapshot_id )
                #         if snapshot:
                #             monitor.stop()
                #             return [(95.0, snapshot)]

            # Check for exact match in local cache (backward compatibility)
            # NOTE: Cache stores VERBATIM questions, so use verbatim lookup for consistency
            # This matches the behavior of delete_snapshot() and cache population during init
            if question in self._question_lookup:
                if self.debug:
                    print( f"Found exact match in local cache for: {du.truncate_string( question, 50 )}" )

                id_hash = self._question_lookup[question]
                record = self._id_lookup[id_hash]
                snapshot = self._record_to_snapshot( record )

                monitor.stop()
                return [(100.0, snapshot)]

            # Level 4: Vector similarity search using LanceDB
            if self.debug:
                print( f"LEVEL 4: No exact matches found, performing vector similarity search..." )

            # Get embedding for query (uses cached if available, generates if not)
            query_embedding = self._question_embeddings_tbl.get_embedding( question )

            if not query_embedding:
                if self.debug:
                    print( "Failed to generate query embedding, returning empty results" )
                monitor.stop()
                return []

            # Point 1: Query embedding validation
            if self.debug and self.verbose:
                print( f"[SIMILARITY-DEBUG] Query text: '{du.truncate_string( question, 80 )}'" )
                if query_embedding:  # pragma: no branch - always truthy here: the `if not query_embedding: return []` guard above (line ~1361) precludes the False arc
                    print( f"[SIMILARITY-DEBUG] Query embedding: {len( query_embedding )} dims, first 5 values: {query_embedding[:5]}" )
                    # Check if embedding is all zeros
                    is_zeros = all( v == 0.0 for v in query_embedding[:100] )
                    if is_zeros:
                        print( f"[SIMILARITY-DEBUG] ⚠️ WARNING: Query embedding appears to be all zeros!" )

            # Perform vector similarity search on question_embedding field
            search_results = self._table.search(
                query_embedding,
                vector_column_name="question_embedding"
            ).metric( "dot" ).nprobes( self._nprobes ).limit( limit if limit > 0 else 100 ).to_list()

            # Point 2: Raw search results count
            if self.debug and self.verbose:
                print( f"[SIMILARITY-DEBUG] Raw LanceDB search returned {len( search_results )} results" )
                if not search_results:
                    print( f"[SIMILARITY-DEBUG] ⚠️ No results from LanceDB - database may be empty or embeddings missing" )

            similar_snapshots = []
            for record in search_results:
                # Extract distance value from LanceDB
                # NOTE: With dot metric, _distance = 1 - dot_product (lower = more similar)
                distance = record.get( "_distance", 0.0 )

                # Convert distance to similarity percentage (0-100 scale)
                # similarity = 1 - distance, matching file-based np.dot() * 100 formula
                similarity_percent = ( 1.0 - distance ) * 100

                # Top-1 + confirm strategy: return ALL results, let caller decide
                snapshot = self._record_to_snapshot( record )
                similar_snapshots.append( ( similarity_percent, snapshot ) )

            # Point 3: Top 10 results logging (no threshold — all returned to caller)
            if self.debug and self.verbose and search_results:
                print( f"[SIMILARITY-DEBUG] Top 10 results (no threshold — top-1 + confirm strategy):" )
                for i, record in enumerate( search_results[:10] ):
                    distance       = record.get( "_distance", 0.0 )
                    score          = ( 1.0 - distance ) * 100
                    id_hash        = record.get( "id_hash", "?" )[:8]
                    created_date   = record.get( "created_date", "?" )[:10]  # Just date part
                    answer_preview = du.truncate_string( record.get( "answer", "?" ), 20 )
                    q_preview      = du.truncate_string( record.get( "question", "?" ), 40 )
                    rank_marker    = "→" if i == 0 else " "
                    print( f"[SIMILARITY-DEBUG]   {i+1}. {rank_marker} {score:.1f}% [{id_hash}] {created_date} - '{q_preview}' → '{answer_preview}'" )

            # Point 4: Summary
            if self.debug:
                total = len( search_results )
                print( f"[SIMILARITY-DEBUG] Vector search: {total} results returned (no threshold filter)" )
                if self.verbose and similar_snapshots:
                    print( f"[SIMILARITY-DEBUG] Top result: {similar_snapshots[0][0]:.1f}% - '{du.truncate_string( similar_snapshots[0][1].question, 50 )}'" )

            # LanceDB already returns sorted by similarity descending, but ensure consistency
            similar_snapshots.sort( key=lambda x: x[0], reverse=True )
            
        except Exception as e:
            if self.debug:
                print( f"✗ Search failed: {e}" )
            raise
        finally:
            monitor.stop()
            
        return similar_snapshots

    def get_snapshots_by_code_similarity( self,
                                         exemplar_snapshot: SolutionSnapshot,
                                         threshold: float = 85.0,
                                         limit: int = 20,
                                         exclude_self: bool = True,
                                         ensure_top_result: bool = True,
                                         debug: bool = False ) -> List[Tuple[float, Any]]:
        """
        Search for snapshots by code similarity using LanceDB vector search.

        Requires:
            - Manager is initialized
            - exemplar_snapshot has valid code_embedding (non-zero 1536-dim vector)
            - threshold is between 0.0 and 100.0

        Ensures:
            - Returns list of (similarity_score, snapshot) tuples
            - Results sorted by similarity descending
            - Uses LanceDB's native vector search on code_embedding field
            - Excludes exemplar snapshot if exclude_self=True
            - If ensure_top_result=True and no results meet threshold, includes best match
            - Performance metrics included

        Raises:
            - RuntimeError if not initialized
            - ValueError if exemplar_snapshot invalid or missing code_embedding
        """
        if not self.is_initialized():
            raise RuntimeError( "Manager must be initialized before searching" )

        if not exemplar_snapshot:
            raise ValueError( "Exemplar snapshot cannot be None" )

        if not (0.0 <= threshold <= 100.0):
            raise ValueError( "Threshold must be between 0.0 and 100.0" )

        monitor = PerformanceMonitor( "get_snapshots_by_code_similarity" )
        monitor.start()

        try:
            # Get code embedding from exemplar snapshot
            query_embedding = exemplar_snapshot.code_embedding

            # Validate code embedding exists and is non-zero
            if not query_embedding:
                if debug: print( "Exemplar snapshot has no code_embedding" )
                monitor.stop()
                return []

            # Check if embedding is all zeros (invalid)
            is_zeros = all( v == 0.0 for v in query_embedding[:100] )
            if is_zeros:
                if debug: print( "Exemplar snapshot has zero code_embedding" )
                monitor.stop()
                return []

            if debug:
                print( f"[CODE-SIMILARITY] Searching with code_embedding ({len( query_embedding )} dims)" )
                print( f"[CODE-SIMILARITY] Exemplar: '{du.truncate_string( exemplar_snapshot.question, 60 )}'" )

            # Perform vector similarity search on code_embedding field
            # Request extra results to account for self-exclusion
            effective_limit = ( limit + 1 ) if exclude_self else ( limit if limit > 0 else 100 )

            search_results = self._table.search(
                query_embedding,
                vector_column_name="code_embedding"
            ).metric( "dot" ).nprobes( self._nprobes ).limit( effective_limit ).to_list()

            if debug:
                print( f"[CODE-SIMILARITY] LanceDB returned {len( search_results )} raw results" )

            similar_snapshots = []
            best_below_threshold = None  # Track best result that doesn't meet threshold

            for record in search_results:
                # Skip self if requested
                if exclude_self and record.get( "id_hash" ) == exemplar_snapshot.id_hash:
                    continue

                # Extract distance and convert to similarity percentage
                # With dot metric: _distance = 1 - dot_product (lower = more similar)
                distance = record.get( "_distance", 0.0 )
                similarity_percent = ( 1.0 - distance ) * 100

                # Apply threshold filter
                if similarity_percent >= threshold:
                    snapshot = self._record_to_snapshot( record )
                    similar_snapshots.append( ( similarity_percent, snapshot ) )
                elif ensure_top_result and best_below_threshold is None:
                    # Track the best result below threshold (first one since LanceDB returns sorted)
                    snapshot = self._record_to_snapshot( record )
                    best_below_threshold = ( similarity_percent, snapshot )

            # Sort by similarity descending
            similar_snapshots.sort( key=lambda x: x[0], reverse=True )

            # Limit results
            if limit > 0:
                similar_snapshots = similar_snapshots[:limit]

            if debug:
                print( f"[CODE-SIMILARITY] Found {len( similar_snapshots )} snapshots above {threshold}% threshold" )
                for i, ( score, snap ) in enumerate( similar_snapshots[:5] ):
                    print( f"[CODE-SIMILARITY]   {i+1}. {score:.1f}% - '{du.truncate_string( snap.question, 50 )}'" )

            # If no results met threshold but ensure_top_result is enabled, include best match
            if len( similar_snapshots ) == 0 and ensure_top_result and best_below_threshold is not None:
                similar_snapshots.append( best_below_threshold )
                if debug:
                    score, snap = best_below_threshold
                    print( f"[CODE-SIMILARITY] Including best result below threshold: {score:.1f}% - '{du.truncate_string( snap.question, 50 )}'" )

        except Exception as e:
            if debug:
                print( f"✗ Code similarity search failed: {e}" )
            raise
        finally:
            monitor.stop()

        return similar_snapshots

    def get_snapshots_by_solution_similarity( self,
                                              exemplar_snapshot: SolutionSnapshot,
                                              threshold: float = 85.0,
                                              limit: int = 20,
                                              exclude_self: bool = True,
                                              ensure_top_result: bool = True,
                                              debug: bool = False ) -> List[Tuple[float, Any]]:
        """
        Search for snapshots by solution/explanation similarity using LanceDB vector search.

        Requires:
            - Manager is initialized
            - exemplar_snapshot has valid solution_embedding (non-zero 1536-dim vector)
            - threshold is between 0.0 and 100.0

        Ensures:
            - Returns list of (similarity_score, snapshot) tuples
            - Results sorted by similarity descending
            - Uses LanceDB's native vector search on solution_embedding field
            - Excludes exemplar snapshot if exclude_self=True
            - If ensure_top_result=True and no results meet threshold, includes best match
            - Performance metrics included

        Raises:
            - RuntimeError if not initialized
            - ValueError if exemplar_snapshot invalid or missing solution_embedding
        """
        if not self.is_initialized():
            raise RuntimeError( "Manager must be initialized before searching" )

        if not exemplar_snapshot:
            raise ValueError( "Exemplar snapshot cannot be None" )

        if not (0.0 <= threshold <= 100.0):
            raise ValueError( "Threshold must be between 0.0 and 100.0" )

        monitor = PerformanceMonitor( "get_snapshots_by_solution_similarity" )
        monitor.start()

        try:
            # Get solution embedding from exemplar snapshot
            query_embedding = exemplar_snapshot.solution_embedding

            # Validate solution embedding exists and is non-zero
            if not query_embedding:
                if debug: print( "Exemplar snapshot has no solution_embedding" )
                monitor.stop()
                return []

            # Check if embedding is all zeros (invalid)
            is_zeros = all( v == 0.0 for v in query_embedding[:100] )
            if is_zeros:
                if debug: print( "Exemplar snapshot has zero solution_embedding" )
                monitor.stop()
                return []

            if debug:
                print( f"[SOLUTION-SIMILARITY] Searching with solution_embedding ({len( query_embedding )} dims)" )
                print( f"[SOLUTION-SIMILARITY] Exemplar: '{du.truncate_string( exemplar_snapshot.question, 60 )}'" )

            # Perform vector similarity search on solution_embedding field
            # Request extra results to account for self-exclusion
            effective_limit = ( limit + 1 ) if exclude_self else ( limit if limit > 0 else 100 )

            search_results = self._table.search(
                query_embedding,
                vector_column_name="solution_embedding"
            ).metric( "dot" ).nprobes( self._nprobes ).limit( effective_limit ).to_list()

            if debug:
                print( f"[SOLUTION-SIMILARITY] LanceDB returned {len( search_results )} raw results" )

            similar_snapshots = []
            best_below_threshold = None  # Track best result that doesn't meet threshold

            for record in search_results:
                # Skip self if requested
                if exclude_self and record.get( "id_hash" ) == exemplar_snapshot.id_hash:
                    continue

                # Extract distance and convert to similarity percentage
                # With dot metric: _distance = 1 - dot_product (lower = more similar)
                distance = record.get( "_distance", 0.0 )
                similarity_percent = ( 1.0 - distance ) * 100

                # Apply threshold filter
                if similarity_percent >= threshold:
                    snapshot = self._record_to_snapshot( record )
                    similar_snapshots.append( ( similarity_percent, snapshot ) )
                elif ensure_top_result and best_below_threshold is None:
                    # Track the best result below threshold (first one since LanceDB returns sorted)
                    snapshot = self._record_to_snapshot( record )
                    best_below_threshold = ( similarity_percent, snapshot )

            # Sort by similarity descending
            similar_snapshots.sort( key=lambda x: x[0], reverse=True )

            # Limit results
            if limit > 0:
                similar_snapshots = similar_snapshots[:limit]

            if debug:
                print( f"[SOLUTION-SIMILARITY] Found {len( similar_snapshots )} snapshots above {threshold}% threshold" )
                for i, ( score, snap ) in enumerate( similar_snapshots[:5] ):
                    print( f"[SOLUTION-SIMILARITY]   {i+1}. {score:.1f}% - '{du.truncate_string( snap.question, 50 )}'" )

            # If no results met threshold but ensure_top_result is enabled, include best match
            if len( similar_snapshots ) == 0 and ensure_top_result and best_below_threshold is not None:
                similar_snapshots.append( best_below_threshold )
                if debug:
                    score, snap = best_below_threshold
                    print( f"[SOLUTION-SIMILARITY] Including best result below threshold: {score:.1f}% - '{du.truncate_string( snap.question, 50 )}'" )

        except Exception as e:
            if debug:
                print( f"✗ Solution similarity search failed: {e}" )
            raise
        finally:
            monitor.stop()

        return similar_snapshots

    def get_gists( self ) -> List[str]:
        """
        Return all available question gists.
        
        Requires:
            - Manager is initialized
            
        Ensures:
            - Returns list of all question gists
            - Empty list if no snapshots exist
            
        Raises:
            - RuntimeError if not initialized
        """
        if not self.is_initialized():
            raise RuntimeError( "Manager must be initialized before getting gists" )
        
        try:
            gists = []
            
            for record in self._id_lookup.values():
                gist = record.get( "question_gist", "" )
                if gist and gist not in gists:
                    gists.append( gist )
            
            if self.debug:
                print( f"Retrieved {len( gists )} unique question gists" )
            
            return gists
            
        except Exception as e:
            if self.debug:
                print( f"✗ Failed to get gists: {e}" )
            return []
    
    def get_stats( self ) -> Dict[str, Any]:
        """
        Return storage statistics for monitoring.
        
        Requires:
            - Manager is initialized
            
        Ensures:
            - Returns dictionary with standardized statistics
            - Includes LanceDB-specific metrics
            
        Raises:
            - RuntimeError if not initialized
        """
        if not self.is_initialized():
            raise RuntimeError( "Manager must be initialized before getting stats" )
        
        try:
            snapshot_count = len( self._question_lookup )
            
            # Calculate storage size (approximate)
            storage_size_mb = 0.0
            if os.path.exists( self.db_path ):
                for root, dirs, files in os.walk( self.db_path ):
                    for file in files:
                        file_path = os.path.join( root, file )
                        storage_size_mb += os.path.getsize( file_path )
                storage_size_mb = storage_size_mb / 1024 / 1024  # Convert to MB
            
            stats = {
                "total_snapshots": snapshot_count,
                "storage_size_mb": round( storage_size_mb, 2 ),
                "database_path": self.db_path,
                "table_name": self.table_name,
                "backend_type": "lancedb",
                "last_updated": time.strftime( "%Y-%m-%d @ %H:%M:%S %Z" )
            }
            
            if self.debug:
                print( f"Stats: {snapshot_count} snapshots, {stats['storage_size_mb']} MB" )
            
            return stats
            
        except Exception as e:
            if self.debug:
                print( f"✗ Failed to get stats: {e}" )
            return {
                "total_snapshots": 0,
                "storage_size_mb": 0.0,
                "backend_type": "lancedb",
                "status": "error",
                "error": str( e )
            }
    
    def health_check( self ) -> Dict[str, Any]:
        """
        Return health status and diagnostics.
        
        Requires:
            - Nothing (works even if not initialized)
            
        Ensures:
            - Returns health information dictionary
            - Status is "healthy", "degraded", or "unhealthy"
            
        Raises:
            - None (handles all errors gracefully)
        """
        try:
            health = {
                "status": "healthy",
                "initialized": self.is_initialized(),
                "backend_type": "lancedb",
                "database_path": self.db_path,
                "table_name": self.table_name,
                "errors": []
            }
            
            # Check database accessibility
            if not os.path.exists( self.db_path ):
                health["errors"].append( f"Database path does not exist: {self.db_path}" )
                health["status"] = "unhealthy"
            elif not os.access( self.db_path, os.R_OK ):
                health["errors"].append( f"Cannot read database: {self.db_path}" )
                health["status"] = "degraded"
            elif not os.access( self.db_path, os.W_OK ):
                health["errors"].append( f"Cannot write to database: {self.db_path}" )
                health["status"] = "degraded"
            
            # Check if initialized and working
            if self.is_initialized():
                try:
                    snapshot_count = len( self._question_lookup )
                    health["snapshot_count"] = snapshot_count
                    
                    # Test database connection
                    if self._db and self._table:
                        health["connection_status"] = "connected"
                    else:
                        health["errors"].append( "Database connection not established" )
                        health["status"] = "degraded"
                        
                except Exception as e:
                    health["errors"].append( f"Error accessing snapshots: {e}" )
                    health["status"] = "degraded"
            else:
                health["status"] = "degraded" if health["status"] == "healthy" else health["status"]
            
            return health
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "initialized": False,
                "backend_type": "lancedb",
                "errors": [f"Health check failed: {e}"]
            }
    

def quick_smoke_test():
    """Test the LanceDB manager interface implementation."""
    du.print_banner( "LanceDBSolutionManager Smoke Test", prepend_nl=True )
    
    try:
        # Test configuration validation
        print( "Testing configuration validation..." )
        try:
            manager = LanceDBSolutionManager( {}, debug=False )
            print( "✗ Empty config was accepted" )
        except KeyError:
            print( "✓ Empty config properly rejected" )
        
        # Test with database configuration
        config = {
            "db_path": "/src/conf/long-term-memory/lupin.lancedb",
            "table_name": "test_solution_snapshots"
        }
        
        print( f"\nTesting manager creation with database: {config['db_path']}" )
        manager = LanceDBSolutionManager( config, debug=True, verbose=False )
        print( "✓ LanceDBSolutionManager created successfully" )
        
        # Test health check before initialization
        print( "\nTesting health check (before initialization)..." )
        health = manager.health_check()
        if health["backend_type"] == "lancedb" and not health["initialized"]:
            print( "✓ Health check working before initialization" )
        else:
            print( "✗ Health check not working properly" )
        
        # Test initialization
        print( "\nTesting initialization..." )
        try:
            init_metrics = manager.initialize()
            if manager.is_initialized() and init_metrics.operation_type == "initialization":
                print( f"✓ Initialization successful, loaded {init_metrics.result_count} snapshots" )
                print( f"  Initialization time: {init_metrics.initialization_time_ms:.1f}ms" )
            else:
                print( "✗ Initialization failed or metrics incorrect" )
        except Exception as e:
            print( f"✗ Initialization failed: {e}" )
            return
        
        # Test health check after initialization
        print( "\nTesting health check (after initialization)..." )
        health = manager.health_check()
        if health["initialized"] and health["status"] in ["healthy", "degraded"]:
            print( f"✓ Health check shows status: {health['status']}" )
        else:
            print( f"✗ Health check failed: {health}" )
        
        # Test stats
        print( "\nTesting statistics..." )
        stats = manager.get_stats()
        if "total_snapshots" in stats and "backend_type" in stats:
            print( f"✓ Stats: {stats['total_snapshots']} snapshots, {stats['storage_size_mb']} MB" )
        else:
            print( "✗ Stats missing required fields" )
        
        # Test gists retrieval
        print( "\nTesting gists retrieval..." )
        gists = manager.get_gists()
        print( f"✓ Retrieved {len( gists )} question gists" )
        
        # Test basic search
        print( "\nTesting basic search..." )
        results = manager.get_snapshots_by_question( "test question" )
        print( f"✓ Search returned {len( results )} results" )

        # Test concurrent save protection (regression test for TOCTOU duplicate bug)
        # See: 2025.12 duplicate snapshot investigation - f4aa24b5 and 2ea576fa bug
        print( "\nTesting concurrent save protection..." )
        import threading

        # Pre-create snapshots (expensive due to embedding generation)
        # This tests the lock without waiting for slow OpenAI API calls
        concurrent_snapshots = [
            SolutionSnapshot( question="concurrent test question", answer="test" )
            for _ in range( 3 )
        ]
        print( f"  Pre-created {len( concurrent_snapshots )} snapshots with different id_hashes" )

        concurrent_results = []
        def threaded_save( snapshot ):
            result = manager.save_snapshot( snapshot )
            concurrent_results.append( result )

        threads = [ threading.Thread( target=threaded_save, args=( s, ) ) for s in concurrent_snapshots ]
        for t in threads: t.start()
        for t in threads: t.join()

        # Verify no duplicates created
        records = manager._table.to_pandas()
        matching = records[ records["question"] == "concurrent test question" ]
        if len( matching ) == 1:
            print( "✓ Concurrent save protection working (1 record, no duplicates)" )
        else:
            print( f"✗ Concurrent save issue: {len( matching )} records exist (expected 1)" )

        # Cleanup test record
        manager.delete_snapshot( "concurrent test question" )

        print( "\n✓ LanceDBSolutionManager smoke test completed successfully" )

    except Exception as e:
        print( f"✗ Error during smoke test: {e}" )
        du.print_stack_trace( e, explanation="LanceDBSolutionManager smoke test failed", caller="quick_smoke_test()" )


if __name__ == "__main__":
    quick_smoke_test()