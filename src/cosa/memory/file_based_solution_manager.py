"""
File-based solution snapshot manager implementing the swappable interface.

⚠️ DEPRECATED: This implementation is deprecated in favor of LanceDBSolutionManager.
This module is retained for backwards compatibility only and will be removed
in a future release. Please use LanceDBSolutionManager for all new development.

This module provides a complete file-based implementation of the
SolutionSnapshotManagerInterface with JSON storage, performance monitoring
and all serialization logic handled internally.
"""

import os
import json
import time
import hashlib
import glob
import warnings
from typing import List, Tuple, Optional, Dict, Any

import cosa.utils.util as du
from cosa.memory.snapshot_manager_interface import (
    SolutionSnapshotManagerInterface,
    PerformanceMetrics,
    PerformanceMonitor
)
from cosa.memory.solution_snapshot import SolutionSnapshot
from cosa.memory.embedding_manager import EmbeddingManager
from cosa.memory.embedding_provider import get_embedding_provider
from cosa.memory.question_embeddings_table import QuestionEmbeddingsTable
from cosa.memory.normalizer import Normalizer


class FileBasedSolutionManager( SolutionSnapshotManagerInterface ):
    """
    File-based solution snapshot manager with interface compliance.

    ⚠️ DEPRECATED: This class is deprecated. Use LanceDBSolutionManager instead.

    Complete file-based implementation that manages JSON storage directly,
    providing performance monitoring and standardized error handling.
    All serialization logic is handled internally by the manager.
    """
    
    def __init__( self, config: Dict[str, Any], debug: bool = False, verbose: bool = False ) -> None:
        """
        Initialize file-based solution snapshot manager.

        ⚠️ DEPRECATED: This class is deprecated. Use LanceDBSolutionManager instead.

        Requires:
            - config["path"] contains valid directory path for JSON files
            - Directory exists or can be created

        Ensures:
            - Initializes internal data structures
            - Configures performance monitoring
            - Prepares for storage operations
            - Issues deprecation warning

        Args:
            config: Configuration dictionary with "path" key
            debug: Enable debug output
            verbose: Enable verbose output

        Raises:
            - KeyError if config["path"] not provided
            - ValueError if path is invalid
        """
        super().__init__( config, debug, verbose )

        # Issue deprecation warning
        warnings.warn(
            "FileBasedSolutionManager is deprecated and will be removed in a future release. "
            "Please use LanceDBSolutionManager instead for better performance and features.",
            DeprecationWarning,
            stacklevel=2
        )

        # Validate required configuration
        if "path" not in config:
            raise KeyError( "FileBasedSolutionManager requires 'path' in configuration" )

        self.path = config["path"]
        self._embedding_mgr      = EmbeddingManager( debug=debug, verbose=verbose )
        self._embedding_provider = get_embedding_provider( debug=debug, verbose=verbose )
        self._normalizer = Normalizer()  # For consistent normalization

        # Internal data structures
        self._snapshots_by_question = None
        self._snapshots_by_synonymous_questions = None
        self._snapshots_by_question_gist = None
        self._question_embeddings_tbl = None

        # Validate path exists or can be created
        if not os.path.exists( self.path ):
            try:
                # Try to get project root and construct full path
                full_path = du.get_project_root() + self.path
                if not os.path.exists( full_path ):
                    raise ValueError( f"Path does not exist and cannot be created: {self.path}" )
                self.path = full_path
            except Exception as e:
                raise ValueError( f"Invalid path configuration: {self.path}. Error: {e}" )

        if self.debug:
            print( f"FileBasedSolutionManager configured with path: {self.path}" )
    
    def initialize( self ) -> None:
        """
        Initialize the file-based storage system directly.

        Requires:
            - Path is valid and accessible
            - JSON files are readable (if any exist)

        Ensures:
            - Loads all existing snapshots from disk
            - Initializes internal data structures
            - Sets _initialized flag to True

        Raises:
            - PermissionError if cannot read/write to path
            - IOError if file operations fail
            - JSONDecodeError if snapshot files corrupted
        """
        monitor = PerformanceMonitor( "initialization" )
        monitor.start()

        try:
            if self.debug:
                print( f"Initializing file-based solution manager at: {self.path}" )

            # Load snapshots directly (no more wrapper pattern)
            self.load_snapshots()
            self._initialized = True

            if self.debug:
                snapshot_count = len( self._snapshots_by_question )
                print( f"✓ Loaded {snapshot_count} snapshots from {self.path}" )

        except Exception as e:
            self._initialized = False
            if self.debug:
                print( f"✗ Failed to initialize file-based manager: {e}" )
            raise
        finally:
            monitor.stop()

        # Initialization complete, no return value needed
    
    def add_snapshot( self, snapshot: SolutionSnapshot ) -> bool:
        """
        Add snapshot to file-based storage.

        Requires:
            - Manager is initialized
            - snapshot is valid SolutionSnapshot
            - snapshot.question is not empty

        Ensures:
            - Snapshot is written to JSON file
            - Snapshot is added to in-memory indexes
            - Returns True if successful

        Raises:
            - RuntimeError if not initialized
            - ValueError if snapshot invalid
            - IOError if file write fails
        """
        if not self.is_initialized():
            raise RuntimeError( "Manager must be initialized before adding snapshots" )

        if not snapshot or not snapshot.question:
            raise ValueError( "Invalid snapshot: question cannot be empty" )

        try:
            # Persist snapshot to file
            self._persist_snapshot( snapshot )

            # Add to in-memory indexes
            question = self._normalizer.normalize( snapshot.question )
            self._snapshots_by_question[ question ] = snapshot

            # Update synonymous questions index
            for syn_question, similarity_score in snapshot.synonymous_questions.items():
                self._snapshots_by_synonymous_questions[ syn_question ] = ( similarity_score, snapshot )

            # Update gist index
            for gist, similarity_score in snapshot.synonymous_question_gists.items():
                self._snapshots_by_question_gist[ gist ] = ( similarity_score, snapshot )

            if self.debug:
                print( f"✓ Added snapshot for question: {du.truncate_string( snapshot.question, 50 )}" )

            return True

        except Exception as e:
            if self.debug:
                print( f"✗ Failed to add snapshot: {e}" )
            return False

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
            # Search through all snapshots for matching id_hash
            for snapshot in self.solution_snapshots:
                if snapshot.id_hash == snapshot_id:
                    if self.debug:
                        print( f"Found snapshot {snapshot_id}: {snapshot.question[:50]}..." )
                    return snapshot

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
            - Snapshot removed from memory indexes
            - Optionally removes JSON file if delete_physical=True
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
            # Clean up the question string before querying
            question = self._normalizer.normalize( question )

            if not self._question_exists( question ):
                if self.debug:
                    print( f"Snapshot with question [{question}] does not exist!" )
                return False

            snapshot = self._snapshots_by_question[ question ]

            # Optionally delete physical file
            if delete_physical:
                if self.debug:
                    print( f"Deleting snapshot file [{question}]...", end="" )
                file_path = self._generate_file_path( snapshot )
                if os.path.exists( file_path ):
                    os.remove( file_path )
                if self.debug:
                    print( "Done!" )

            # Remove from in-memory indexes
            if self.debug:
                print( f"Deleting snapshot from manager [{question}]...", end="" )
            del self._snapshots_by_question[ question ]

            # Remove from synonymous questions and gists indexes
            # (This is a simplified cleanup - could be more thorough)
            keys_to_remove = []
            for key, ( score, snap ) in self._snapshots_by_synonymous_questions.items():
                if snap.question == question:
                    keys_to_remove.append( key )
            for key in keys_to_remove:
                del self._snapshots_by_synonymous_questions[ key ]

            keys_to_remove = []
            for key, ( score, snap ) in self._snapshots_by_question_gist.items():
                if snap.question == question:
                    keys_to_remove.append( key )
            for key in keys_to_remove:
                del self._snapshots_by_question_gist[ key ]

            if self.debug:
                print( "Done!" )

            return True

        except Exception as e:
            if self.debug:
                print( f"✗ Failed to delete snapshot: {e}" )
            return False
    
    def get_snapshots_by_question( self,
                                  question: str,
                                  question_gist: Optional[str] = None,
                                  threshold_question: float = 100.0,
                                  threshold_gist: float = 100.0,
                                  limit: int = 7,
                                  debug: bool = False ) -> List[Tuple[float, Any]]:
        """
        Search for snapshots by question similarity.

        Requires:
            - Manager is initialized
            - question is non-empty string
            - thresholds are between 0.0 and 100.0

        Ensures:
            - Returns list of (similarity_score, snapshot) tuples
            - Results sorted by similarity descending
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

        monitor = PerformanceMonitor( "find_by_question" )
        monitor.start()

        try:
            # Clean question string
            question = SolutionSnapshot.remove_non_alphanumerics( question )

            # Escape single quotes in the question gist
            if question_gist is not None:
                question_gist = SolutionSnapshot.escape_single_quotes( question_gist )
                if self.debug:
                    du.print_banner( f"Escaped question_gist: [{question_gist}]", prepend_nl=True )

            if self.debug:
                print( f"get_snapshots_by_question( '{question}', '{question_gist}', with threshold_question [{threshold_question}] and threshold_gist [{threshold_gist}] )..." )

            # Check if the question exists in the snapshot dictionary
            if self._question_exists( question ):
                if debug or self.debug:
                    print( f"Exact match: Snapshot with question [{question}] exists!" )
                similar_snapshots = [ (100.0, self._snapshots_by_question[ question ]) ]

            # Check if the question exists in the synonymous questions dictionary
            elif self._synonymous_question_exists( question ) and self._snapshots_by_synonymous_questions[ question ][ 0 ] >= threshold_question:
                score = self._snapshots_by_synonymous_questions[ question ][ 0 ]
                snapshot = self._snapshots_by_synonymous_questions[ question ][ 1 ]
                similar_snapshots = [ (score, snapshot) ]
                if self.debug:
                    print( f"Snapshot with synonymous question for [{question}] exists: [{snapshot.question}] similarity score [{score}] >= [{threshold_question}]" )

            # Check if the gist exists in the gist dictionary
            elif self._question_gist_exists( question_gist ) and self._snapshots_by_question_gist[ question_gist ][ 0 ] >= threshold_gist:
                score = self._snapshots_by_question_gist[ question_gist ][ 0 ]
                snapshot = self._snapshots_by_question_gist[ question_gist ][ 1 ]
                similar_snapshots = [ (score, snapshot) ]
                if self.debug:
                    print( f"Snapshot with gist for [{question}] exists: [{snapshot.question_gist}] similarity score [{score}] >= [{threshold_gist}]" )

            else:
                if self.debug:
                    print( "No exact match, synonymous question or exact gist found, searching for similar questions and gists..." )
                similar_snapshots = self._get_snapshots_by_question_similarity( question, question_gist=question_gist, threshold_question=threshold_question, threshold_gist=threshold_gist, limit=limit )

            if len( similar_snapshots ) > 0:
                if debug or self.debug:
                    print( f"Found [{len( similar_snapshots )}] similar snapshots" )
                    for snapshot in similar_snapshots:
                        print( f"score [{snapshot[ 0 ]}] for [{question}] == [{snapshot[ 1 ].question}]" )
            else:
                if self.debug:
                    print( f"Could NOT find any snapshots similar to Q [{question}] G [{question_gist}]" )

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
                                         limit: int = -1,
                                         debug: bool = False ) -> List[Tuple[float, Any]]:
        """
        Search for snapshots by code similarity.

        Requires:
            - Manager is initialized
            - exemplar_snapshot has valid code_embedding
            - threshold is between 0.0 and 100.0

        Ensures:
            - Returns list of (similarity_score, snapshot) tuples
            - Results sorted by similarity descending
            - Performance metrics included

        Raises:
            - RuntimeError if not initialized
            - ValueError if exemplar_snapshot invalid
        """
        if not self.is_initialized():
            raise RuntimeError( "Manager must be initialized before searching" )

        if not exemplar_snapshot or not exemplar_snapshot.code_embedding:
            raise ValueError( "Exemplar snapshot must have valid code_embedding" )

        if not (0.0 <= threshold <= 100.0):
            raise ValueError( "Threshold must be between 0.0 and 100.0" )

        monitor = PerformanceMonitor( "find_by_code_similarity" )
        monitor.start()

        try:
            original_question = du.truncate_string( exemplar_snapshot.question, max_len=32 )
            similar_snapshots = []

            # Iterate the code in the code list and print it to the console
            if self.debug and self.verbose:
                du.print_banner( f"Source code for [{original_question}]:", prepend_nl=True )
                for line in exemplar_snapshot.code:
                    print( line )
                print()

            for snapshot in self._snapshots_by_question.values():
                similarity_score = snapshot.get_code_similarity( exemplar_snapshot )
                question_truncated = du.truncate_string( snapshot.question, max_len=32 )

                if similarity_score >= threshold:
                    similar_snapshots.append( ( similarity_score, snapshot ) )
                    if self.debug and self.verbose:
                        du.print_banner( f"Code score [{similarity_score}] for snapshot [{question_truncated}] IS similar to the provided code", end="\n" )
                        du.print_list( snapshot.code )
                else:
                    if self.debug:
                        print( f"Code score [{similarity_score}] for snapshot [{question_truncated}] is NOT similar to the provided code", end="\n" )

            # Sort by similarity score, descending
            similar_snapshots.sort( key=lambda x: x[ 0 ], reverse=True )

            if self.debug:
                print()
                for snapshot in similar_snapshots:
                    print( f"Code similarity score [{snapshot[ 0 ]}] for [{original_question}] == [{du.truncate_string( snapshot[ 1 ].question, max_len=32 )}]" )

            if limit == -1:
                return similar_snapshots
            else:
                return similar_snapshots[ :limit ]

        except Exception as e:
            if self.debug:
                print( f"✗ Code similarity search failed: {e}" )
            raise
        finally:
            monitor.stop()
    
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
            gists = list( self._snapshots_by_question_gist.keys() )

            if self.debug:
                print( f"Retrieved {len( gists )} question gists" )

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
            - Includes file count, storage size, etc.

        Raises:
            - RuntimeError if not initialized
        """
        if not self.is_initialized():
            raise RuntimeError( "Manager must be initialized before getting stats" )

        try:
            snapshot_count = len( self._snapshots_by_question )

            # Calculate storage size
            storage_size_mb = 0.0
            if os.path.exists( self.path ):
                for filename in os.listdir( self.path ):
                    if filename.endswith( ".json" ):
                        file_path = os.path.join( self.path, filename )
                        if os.path.isfile( file_path ):
                            storage_size_mb += os.path.getsize( file_path )
                storage_size_mb = storage_size_mb / 1024 / 1024  # Convert to MB

            stats = {
                "total_snapshots": snapshot_count,
                "storage_size_mb": round( storage_size_mb, 2 ),
                "storage_path": self.path,
                "backend_type": "file_based",
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
                "backend_type": "file_based",
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
                "backend_type": "file_based",
                "storage_path": self.path,
                "errors": []
            }

            # Check path accessibility
            if not os.path.exists( self.path ):
                health["errors"].append( f"Storage path does not exist: {self.path}" )
                health["status"] = "unhealthy"
            elif not os.access( self.path, os.R_OK ):
                health["errors"].append( f"Cannot read from storage path: {self.path}" )
                health["status"] = "degraded"
            elif not os.access( self.path, os.W_OK ):
                health["errors"].append( f"Cannot write to storage path: {self.path}" )
                health["status"] = "degraded"

            # Check if initialized and working
            if self.is_initialized():
                try:
                    snapshot_count = len( self._snapshots_by_question )
                    health["snapshot_count"] = snapshot_count
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
                "backend_type": "file_based",
                "errors": [f"Health check failed: {e}"]
            }

    # ======================================================================
    # LOADING METHODS - Manager owns all data loading logic
    # ======================================================================

    def load_snapshots( self ) -> None:
        """
        Load all snapshots from the directory.

        Requires:
            - self.path is set
            - Directory exists

        Ensures:
            - Populates all snapshot dictionaries
            - Initializes embeddings table
            - Prints debug info if enabled

        Raises:
            - None (handles errors internally)
        """
        self._snapshots_by_question = self._load_snapshots_by_question()
        self._snapshots_by_synonymous_questions = self._load_snapshots_by_synonymous_questions( self._snapshots_by_question )
        self._snapshots_by_question_gist = self._load_snapshots_by_gist( self._snapshots_by_question )
        self._question_embeddings_tbl = QuestionEmbeddingsTable()

        if self.debug:
            print( f"FileBasedSolutionManager: {len( self._snapshots_by_question )} snapshots loaded from {self.path}" )
            if self.verbose:
                self._print_snapshots()

    def reload( self ) -> None:
        """
        Reload/refresh snapshots from disk storage.

        Requires:
            - Manager has been previously initialized
            - Storage path is accessible

        Ensures:
            - Refreshes all cached data from disk
            - Updates internal dictionaries with current file contents
            - Reinitializes embeddings table
            - Prints debug info if enabled

        Raises:
            - RuntimeError if manager not initialized
            - PermissionError if cannot read from storage path
            - IOError if file operations fail
        """
        if not self.is_initialized():
            raise RuntimeError( "FileBasedSolutionManager must be initialized before reload" )

        if self.debug:
            print( f"Reloading solution snapshots from {self.path}..." )

        # Use existing load_snapshots method which handles all the reloading logic
        self.load_snapshots()

        if self.debug:
            print( f"✓ Reloaded {len( self._snapshots_by_question )} snapshots" )

    def _load_snapshots_by_question( self ) -> Dict[str, SolutionSnapshot]:
        """
        Load snapshots indexed by question.

        Requires:
            - self.path is a valid directory
            - Directory contains JSON files

        Ensures:
            - Returns dict mapping questions to snapshots
            - Filters out hidden files and non-JSON files

        Raises:
            - None (handles errors internally)
        """
        snapshots_by_question = {}
        if self.debug:
            print( f"Loading snapshots by question from [{self.path}]..." )

        filtered_files = [ file for file in os.listdir( self.path ) if not file.startswith( "._" ) and file.endswith( ".json" ) ]
        if self.debug and self.verbose:
            du.print_list( filtered_files )

        failed_files = []
        for file in filtered_files:
            json_file = os.path.join( self.path, file )
            try:
                snapshot = self._load_snapshot_from_file( json_file )
                snapshots_by_question[ snapshot.question ] = snapshot
            except Exception as e:
                failed_files.append( ( file, str( e ) ) )
                if self.debug:
                    print( f"ERROR: Failed to load snapshot from {file}: {str(e)}" )
                    print( f"       Continuing with remaining snapshots..." )

        if failed_files:
            print( f"WARNING: Failed to load {len(failed_files)} snapshot file(s):" )
            for file, error in failed_files:
                print( f"  - {file}: {error}" )
            print( f"Successfully loaded {len(snapshots_by_question)} snapshots from remaining files." )

        return snapshots_by_question

    def _load_snapshots_by_gist( self, snapshots_by_question: Dict[str, SolutionSnapshot] ) -> Dict[str, Tuple[float, SolutionSnapshot]]:
        """
        Create gist-based index of snapshots.

        Requires:
            - snapshots_by_question is populated

        Ensures:
            - Returns dict mapping gists to (score, snapshot) tuples
            - Includes all synonymous gists

        Raises:
            - None
        """
        snapshots_by_gist = {}
        if self.debug:
            print( f"Loading by gist snapshots from [{self.path}]..." )

        for _, snapshot in snapshots_by_question.items():
            for question, similarity_score in snapshot.synonymous_question_gists.items():
                snapshots_by_gist[ question ] = ( similarity_score, snapshot )

        if self.debug:
            du.print_banner( f"Found [{len( snapshots_by_gist )}] synonymous gists", prepend_nl=True )
            for question_gist in snapshots_by_gist.keys():
                print( f"Q [{snapshots_by_gist[ question_gist ][ 1 ].question}] has synonymous gist [{question_gist}]" )
            print()

        return snapshots_by_gist

    def _load_snapshots_by_synonymous_questions( self, snapshots_by_question: Dict[str, SolutionSnapshot] ) -> Dict[str, Tuple[float, SolutionSnapshot]]:
        """
        Create synonymous question index.

        Requires:
            - snapshots_by_question is populated

        Ensures:
            - Returns dict mapping synonymous questions to (score, snapshot) tuples
            - Includes all synonymous questions from snapshots

        Raises:
            - None
        """
        snapshots_by_synonymous_questions = {}

        for _, snapshot in snapshots_by_question.items():
            for question, similarity_score in snapshot.synonymous_questions.items():
                snapshots_by_synonymous_questions[ question ] = ( similarity_score, snapshot )

        if self.debug:
            du.print_banner( f"Found [{len( snapshots_by_synonymous_questions )}] synonymous questions", prepend_nl=True )
            for question in snapshots_by_synonymous_questions.keys():
                if question != snapshots_by_synonymous_questions[ question ][ 1 ].question:
                    print( f"Snapshot Q [{snapshots_by_synonymous_questions[ question ][ 1 ].question}] has synonymous Q [{question}]" )
            print()

        return snapshots_by_synonymous_questions

    def _print_snapshots( self ) -> None:
        """
        Print all loaded snapshots.

        Requires:
            - Snapshots are loaded

        Ensures:
            - Prints count and questions to console

        Raises:
            - None
        """
        du.print_banner( f"Total snapshots: [{len( self._snapshots_by_question )}]", prepend_nl=True )
        for question, snapshot in self._snapshots_by_question.items():
            print( f"Question: [{question}]" )
        print()

    # ======================================================================
    # SERIALIZATION METHODS - Manager owns all persistence logic
    # ======================================================================

    def _persist_snapshot( self, snapshot: SolutionSnapshot ) -> None:
        """
        Save snapshot to JSON file (replaces snapshot.write_current_state_to_file()).

        Requires:
            - snapshot is valid SolutionSnapshot
            - snapshot.question is not empty

        Ensures:
            - Creates JSON file with snapshot data
            - Generates unique filename if needed
            - Sets file permissions to 0o666

        Raises:
            - OSError if file operations fail
        """
        file_path = self._generate_file_path( snapshot )
        json_data = self._snapshot_to_json( snapshot )

        if self.debug:
            print( f"Persisting snapshot to: {file_path}" )

        with open( file_path, "w" ) as f:
            f.write( json_data )

        # Set the file permissions to world-readable and writable
        os.chmod( file_path, 0o666 )

    def _snapshot_to_json( self, snapshot: SolutionSnapshot ) -> str:
        """
        Convert snapshot to JSON string (replaces snapshot.to_jsons()).

        Requires:
            - snapshot is valid SolutionSnapshot

        Ensures:
            - Returns valid JSON string
            - Excludes non-serializable fields
            - All data preserved for loading

        Raises:
            - JSON serialization errors
        """
        # Fields to exclude from serialization (copied from SolutionSnapshot.to_jsons)
        fields_to_exclude = [
            "prompt_response", "prompt_response_dict", "code_response_dict",
            "phind_tgi_url", "config_mgr", "_embedding_mgr", "_embedding_provider", "websocket_id", "user_id"
        ]
        data = { field: value for field, value in snapshot.__dict__.items() if field not in fields_to_exclude }
        return json.dumps( data )

    def _load_snapshot_from_file( self, json_file: str ) -> SolutionSnapshot:
        """
        Load snapshot from JSON file (replaces SolutionSnapshot.from_json_file()).

        Requires:
            - json_file is valid file path
            - File contains valid JSON data

        Ensures:
            - Returns SolutionSnapshot instance
            - All data properly deserialized

        Raises:
            - FileNotFoundError if file doesn't exist
            - JSONDecodeError if invalid JSON
        """
        if self.debug:
            print( f"Loading snapshot from: {json_file}" )

        with open( json_file, "r" ) as f:
            data = json.load( f )

        return SolutionSnapshot( **data )

    def _generate_file_path( self, snapshot: SolutionSnapshot ) -> str:
        """
        Generate unique file path for snapshot.

        Requires:
            - snapshot.question is not empty

        Ensures:
            - Returns unique file path
            - Creates filename based on question
            - Handles file naming conflicts

        Raises:
            - None
        """
        directory = self.path + "/" if not self.path.endswith( "/" ) else self.path

        # Check if snapshot already has a filename
        if hasattr( snapshot, 'solution_file' ) and snapshot.solution_file:
            return os.path.join( directory, snapshot.solution_file )

        # Generate filename based on the question (logic from write_current_state_to_file)
        question_clean = SolutionSnapshot.remove_non_alphanumerics( snapshot.question, replacement_char="_" )
        filename_base = du.truncate_string( question_clean, max_len=64 ).replace( " ", "-" )

        # Get existing files that start with the filename base
        existing_files = glob.glob( f"{directory}{filename_base}-*.json" )
        file_count = len( existing_files )

        # Generate unique filename
        filename = f"{filename_base}-{file_count}.json"
        return os.path.join( directory, filename )

    # ======================================================================
    # SEARCH METHODS - Manager owns all search logic
    # ======================================================================

    def _question_exists( self, question: str ) -> bool:
        """
        Check if question exists in loaded snapshots.

        Requires:
            - question is a string

        Ensures:
            - Returns True if question found
            - Returns False if not found

        Raises:
            - None
        """
        return question in self._snapshots_by_question

    def _synonymous_question_exists( self, question: str ) -> bool:
        """
        Check if synonymous question exists.

        Requires:
            - question is a string

        Ensures:
            - Returns True if synonymous question found
            - Returns False if not found

        Raises:
            - None
        """
        return question in self._snapshots_by_synonymous_questions

    def _question_gist_exists( self, question_gist: Optional[str] ) -> bool:
        """
        Check if question gist exists.

        Requires:
            - question_gist can be None or string

        Ensures:
            - Returns True if gist found and not None
            - Returns False if gist is None or not found

        Raises:
            - None
        """
        return question_gist is not None and question_gist in self._snapshots_by_question_gist

    def _get_snapshots_by_question_similarity( self, question: str, question_gist: Optional[str] = None, threshold_question: float = 100.0, threshold_gist: float = 100.0, limit: int = 7, exclude_non_synonymous_questions: bool = True ) -> List[Tuple[float, Any]]:
        """
        Find similar snapshots using embeddings.

        Requires:
            - question is a non-empty string
            - thresholds are between 0 and 100
            - limit is positive integer

        Ensures:
            - Returns list of (score, snapshot) tuples
            - Sorted by similarity descending
            - Limited to requested count
            - Excludes blacklisted questions if requested

        Raises:
            - None
        """
        if self.debug:
            print( f"_get_snapshots_by_question_similarity( '{question}' )..." )

        # Generate the embedding for the question if it doesn't already exist
        if not self._question_embeddings_tbl.has( question ):
            question_embedding = self._embedding_provider.generate_embedding( question, content_type="prose" )
            self._question_embeddings_tbl.add_embedding( question, question_embedding )
        else:
            if self.debug:
                print( f"Embedding for question [{question}] already exists!" )
            question_embedding = self._question_embeddings_tbl.get_embedding( question )

        # generate the embedding for the question gist if it doesn't already exist
        question_gist_embedding = []
        if question_gist is not None and not self._question_embeddings_tbl.has( question_gist ):
            question_gist_embedding = self._embedding_provider.generate_embedding( question_gist, content_type="prose" )
            self._question_embeddings_tbl.add_embedding( question_gist, question_gist_embedding )
        elif question_gist is not None:
            if self.debug:
                print( f"Embedding for question gist [{question_gist}] already exists!" )
            question_gist_embedding = self._question_embeddings_tbl.get_embedding( question_gist )
        if self.debug and self.verbose and question_gist_embedding:
            print( f"question_gist_embedding: {question_gist_embedding[0:16]}" )

        similar_snapshots = []

        # Iterate the snapshots and compare the question embeddings
        for snapshot in self._snapshots_by_question.values():

            if exclude_non_synonymous_questions and question in snapshot.non_synonymous_questions:
                if self.debug:
                    du.print_banner( f"Snapshot [{question}] is in the NON synonymous list!", prepend_nl=True )
                    print( f"Snapshot [{question}] has been blacklisted by [{snapshot.question}]" )
                    print( "Continuing to next snapshot..." )
                continue

            similarity_score = SolutionSnapshot.get_embedding_similarity( question_embedding, snapshot.question_embedding )

            # Top-1 + confirm strategy: return ALL results, let caller decide
            similar_snapshots.append( ( similarity_score, snapshot ) )
            if self.debug:
                print( f"Score [{similarity_score:.2f}]% for question [{snapshot.question}] vs [{question}]" )

        # Gist embedding comparison — DISABLED (top-1 + confirm strategy)
        # Gist text still generated for display/logging, but not used for matching
        # if question_gist is not None:
        #     for snapshot in self._snapshots_by_question_gist.values():
        #         similarity_score = SolutionSnapshot.get_embedding_similarity( question_gist_embedding, snapshot[ 1 ].question_embedding )
        #         if similarity_score >= threshold_gist:
        #             similar_snapshots.append( ( similarity_score, snapshot[ 1 ] ) )
        #             if self.debug:
        #                 print( f"Score [{similarity_score:.2f}]% for gist [{snapshot[ 1 ].question_gist}] IS similar enough to [{question_gist}]" )
        #         else:
        #             if self.debug and self.verbose:
        #                 print( f"Score [{similarity_score:.2f}]% for gist [{snapshot[ 1 ].question_gist}] is NOT similar enough to [{question_gist}]" )

        # Sort by similarity score, descending
        similar_snapshots.sort( key=lambda x: x[ 0 ], reverse=True )

        if self.debug:
            print()
            if len( similar_snapshots ) > 0:
                du.print_banner( f"Found [{len( similar_snapshots )}] similar snapshots for question [{question}]", prepend_nl=True )
                for snapshot in similar_snapshots:
                    print( f"Score [{snapshot[ 0 ]:.2f}]% for [{question}] == [{snapshot[ 1 ].question}]" )
            else:
                print( f"Could NOT find any snapshots similar to Q [{question}] G [{question_gist}]" )

        return similar_snapshots[ :limit ]


def quick_smoke_test():
    """Test the file-based manager interface implementation."""
    du.print_banner( "FileBasedSolutionManager Smoke Test", prepend_nl=True )
    
    try:
        # Test configuration validation
        print( "Testing configuration validation..." )
        try:
            manager = FileBasedSolutionManager( {}, debug=False )
            print( "✗ Empty config was accepted" )
        except KeyError:
            print( "✓ Empty config properly rejected" )
        
        # Test with test path
        test_path = du.get_project_root() + "/src/conf/long-term-memory/solutions/"
        config = {"path": test_path}
        
        print( f"\nTesting manager creation with path: {test_path}" )
        manager = FileBasedSolutionManager( config, debug=True, verbose=False )
        print( "✓ FileBasedSolutionManager created successfully" )
        
        # Test health check before initialization
        print( "\nTesting health check (before initialization)..." )
        health = manager.health_check()
        if health["backend_type"] == "file_based" and not health["initialized"]:
            print( "✓ Health check working before initialization" )
        else:
            print( "✗ Health check not working properly" )
        
        # Test initialization
        print( "\nTesting initialization..." )
        try:
            manager.initialize()
            if manager.is_initialized():
                print( f"✓ Initialization successful" )
            else:
                print( "✗ Initialization failed" )
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

        # Test search (if snapshots exist)
        if stats["total_snapshots"] > 0:
            print( "\nTesting question search..." )
            results = manager.get_snapshots_by_question( "what day is today" )
            print( f"✓ Search returned {len( results )} results" )
        else:
            print( "\nSkipping search test (no snapshots available)" )
        
        print( "\n✓ FileBasedSolutionManager smoke test completed successfully" )
        
    except Exception as e:
        print( f"✗ Error during smoke test: {e}" )
        du.print_stack_trace( e, explanation="FileBasedSolutionManager smoke test failed", caller="quick_smoke_test()" )


if __name__ == "__main__":
    quick_smoke_test()