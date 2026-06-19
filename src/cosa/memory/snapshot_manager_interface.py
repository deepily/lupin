"""
Abstract interface for solution snapshot storage and retrieval systems.

This module defines the contract that all solution snapshot managers must implement,
enabling swappable backends (file-based, LanceDB, etc.) with identical APIs.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
import time
import psutil
import os

from cosa.memory.solution_snapshot import SolutionSnapshot


@dataclass
class PerformanceMetrics:
    """
    Standardized performance metrics for empirical comparison between implementations.
    
    All implementations collect these metrics to enable objective performance analysis
    and regression detection during migration.
    """
    search_time_ms: float = 0.0
    memory_usage_mb: float = 0.0
    result_count: int = 0
    cache_hit_rate: float = 0.0
    initialization_time_ms: float = 0.0
    operation_type: str = "unknown"
    timestamp: str = field( default_factory=lambda: time.strftime( "%Y-%m-%d @ %H:%M:%S %Z" ) )
    
    def to_dict( self ) -> Dict[str, Any]:
        """Convert metrics to dictionary for serialization."""
        return {
            "search_time_ms": self.search_time_ms,
            "memory_usage_mb": self.memory_usage_mb,
            "result_count": self.result_count,
            "cache_hit_rate": self.cache_hit_rate,
            "initialization_time_ms": self.initialization_time_ms,
            "operation_type": self.operation_type,
            "timestamp": self.timestamp
        }


class PerformanceMonitor:
    """
    Helper class for collecting performance metrics during operations.
    
    Provides consistent timing and memory measurement across all implementations.
    """
    
    def __init__( self, operation_type: str = "unknown" ):
        """
        Initialize performance monitor for a specific operation.
        
        Requires:
            - operation_type is a descriptive string
            
        Ensures:
            - Initializes timing and memory baselines
            - Prepares for metric collection
        """
        self.operation_type = operation_type
        self.start_time = None
        self.start_memory = None
        self.end_time = None
        self.end_memory = None
        
    def start( self ) -> None:
        """Start timing and memory monitoring."""
        self.start_time = time.time()
        self.start_memory = self._get_memory_usage_mb()
        
    def stop( self ) -> None:
        """Stop timing and memory monitoring."""
        self.end_time = time.time()
        self.end_memory = self._get_memory_usage_mb()
        
    def get_metrics( self, result_count: int = 0, cache_hit_rate: float = 0.0 ) -> PerformanceMetrics:
        """
        Generate performance metrics from collected data.
        
        Requires:
            - start() and stop() have been called
            - result_count is non-negative integer
            - cache_hit_rate is between 0.0 and 1.0
            
        Ensures:
            - Returns complete PerformanceMetrics object
            - All timing and memory data included
            
        Raises:
            - ValueError if monitoring wasn't started/stopped properly
        """
        if self.start_time is None or self.end_time is None:
            raise ValueError( "Must call start() and stop() before getting metrics" )
            
        return PerformanceMetrics(
            search_time_ms=( self.end_time - self.start_time ) * 1000,
            memory_usage_mb=max( self.end_memory - self.start_memory, 0 ),  # Avoid negative values
            result_count=result_count,
            cache_hit_rate=cache_hit_rate,
            operation_type=self.operation_type
        )
        
    def _get_memory_usage_mb( self ) -> float:
        """Get current process memory usage in MB."""
        try:
            process = psutil.Process( os.getpid() )
            return process.memory_info().rss / 1024 / 1024  # Convert bytes to MB
        except Exception:
            return 0.0  # Fallback if psutil unavailable


class SolutionSnapshotManagerInterface( ABC ):
    """
    Abstract interface for solution snapshot storage and retrieval.
    
    This interface ensures both file-based and LanceDB implementations
    are truly swappable with identical contracts and testable behaviors.
    
    All implementations must:
    1. Provide identical method signatures and return types
    2. Collect performance metrics for empirical comparison
    3. Handle errors gracefully with consistent error reporting
    4. Support configuration-driven initialization
    """
    
    def __init__( self, config: Dict[str, Any], debug: bool = False, verbose: bool = False ) -> None:
        """
        Initialize manager with configuration dictionary.
        
        Requires:
            - config contains all necessary configuration keys for implementation
            - debug and verbose are booleans
            
        Ensures:
            - Stores configuration and debug settings
            - Prepares for initialization (but doesn't initialize storage)
            - All implementations use same initialization pattern
            
        Raises:
            - KeyError if required config keys missing
            - ValueError if config values invalid
        """
        self.config = config
        self.debug = debug
        self.verbose = verbose
        self._initialized = False
        self._performance_monitoring = config.get( "enable_performance_monitoring", True )
    
    @abstractmethod
    def initialize( self ) -> None:
        """
        Load/initialize storage backend.
        
        Requires:
            - Configuration is valid and complete
            - Storage backend is accessible
            
        Ensures:
            - Storage system is ready for operations
            - Sets _initialized flag to True
            - Can be called multiple times safely
            
        Raises:
            - ConnectionError if storage backend unavailable
            - PermissionError if insufficient access rights
            - ValueError if configuration invalid
        """
        pass

    @abstractmethod
    def reload( self ) -> None:
        """
        Reload/refresh data from storage backend.

        Requires:
            - Storage backend is accessible
            - Manager has been previously initialized

        Ensures:
            - Refreshes all cached data from storage
            - Reconnects to storage backend if needed
            - Updates internal state to reflect current storage contents
            - Can be called multiple times safely

        Raises:
            - ConnectionError if storage backend unavailable
            - PermissionError if insufficient access rights
            - RuntimeError if manager not initialized
        """
        pass

    @abstractmethod
    def save_snapshot( self, snapshot: SolutionSnapshot ) -> bool:
        """
        Save snapshot to storage backend using upsert semantics.

        Performs INSERT for new snapshots or UPDATE for existing ones.

        Requires:
            - snapshot is a valid SolutionSnapshot instance
            - snapshot.question is not empty
            - Storage backend is initialized

        Ensures:
            - Snapshot is stored persistently
            - Returns True if successful, False otherwise
            - Existing snapshot with same question is updated (upsert)
            - Performance metrics collected if monitoring enabled

        Raises:
            - ValueError if snapshot invalid
            - ConnectionError if storage unavailable
        """
        pass
    
    @abstractmethod
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
        pass

    @abstractmethod
    def delete_snapshot( self, question: str, delete_physical: bool = False ) -> bool:
        """
        Delete snapshot by question identifier.
        
        Requires:
            - question is a non-empty string
            - Storage backend is initialized
            
        Ensures:
            - Snapshot removed from storage if exists
            - Returns True if deleted, False if not found
            - Physical storage cleanup if delete_physical=True
            - Performance metrics collected if monitoring enabled
            
        Raises:
            - ValueError if question empty
            - PermissionError if cannot delete physical storage
        """
        pass
    
    @abstractmethod
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
            - question is a non-empty string
            - thresholds are between 0.0 and 100.0
            - limit is positive integer
            - Storage backend is initialized
            
        Ensures:
            - Returns list of (similarity_score, snapshot) tuples
            - Results sorted by similarity descending
            - Limited to requested count
            - Identical behavior across implementations
            
        Raises:
            - ValueError if parameters invalid
            - ConnectionError if storage unavailable
        """
        pass
    
    @abstractmethod
    def get_snapshots_by_code_similarity( self,
                                         exemplar_snapshot: SolutionSnapshot,
                                         threshold: float = 85.0,
                                         limit: int = -1,
                                         debug: bool = False ) -> List[Tuple[float, Any]]:
        """
        Search for snapshots by code similarity.
        
        Requires:
            - exemplar_snapshot has valid code_embedding
            - threshold is between 0.0 and 100.0
            - limit is integer (-1 for unlimited)
            - Storage backend is initialized
            
        Ensures:
            - Returns list of (similarity_score, snapshot) tuples
            - Results sorted by similarity descending
            - Limited to requested count (-1 = no limit)
            - Identical behavior across implementations
            
        Raises:
            - ValueError if exemplar_snapshot invalid or missing code_embedding
            - ConnectionError if storage unavailable
        """
        pass
    
    @abstractmethod
    def get_gists( self ) -> List[str]:
        """
        Return all available question gists.
        
        Requires:
            - Storage backend is initialized
            
        Ensures:
            - Returns list of all unique question gists
            - Empty list if no snapshots exist
            - Consistent ordering across calls
            
        Raises:
            - ConnectionError if storage unavailable
        """
        pass
    
    @abstractmethod
    def get_stats( self ) -> Dict[str, Any]:
        """
        Return storage statistics for monitoring and comparison.
        
        Requires:
            - Storage backend is initialized
            
        Ensures:
            - Returns dictionary with standardized statistics
            - Includes: total_snapshots, storage_size_mb, last_updated
            - Additional implementation-specific stats allowed
            - Consistent format for empirical comparison
            
        Raises:
            - ConnectionError if storage unavailable
        """
        pass
    
    @abstractmethod
    def health_check( self ) -> Dict[str, Any]:
        """
        Return health status and diagnostics.
        
        Requires:
            - Nothing (should work even if not initialized)
            
        Ensures:
            - Returns dictionary with health information
            - Includes: status, initialized, backend_type, errors
            - Status is one of: "healthy", "degraded", "unhealthy"
            - Provides diagnostic information for troubleshooting
            
        Raises:
            - None (should handle all errors gracefully)
        """
        pass
    
    def is_initialized( self ) -> bool:
        """
        Check if manager has been initialized.
        
        Requires:
            - Nothing
            
        Ensures:
            - Returns True if initialize() was called successfully
            - Returns False otherwise
            
        Raises:
            - None
        """
        return getattr( self, '_initialized', False )
    
    def get_implementation_name( self ) -> str:
        """
        Get human-readable name of this implementation.
        
        Requires:
            - Nothing
            
        Ensures:
            - Returns descriptive name (e.g., "FileBased", "LanceDB")
            - Used for logging and comparison reports
            
        Raises:
            - None
        """
        return self.__class__.__name__


def quick_smoke_test():
    """Test the interface definition and helper classes."""
    import cosa.utils.util as du
    
    du.print_banner( "SolutionSnapshotManagerInterface Smoke Test", prepend_nl=True )
    
    try:
        # Test PerformanceMetrics
        print( "Testing PerformanceMetrics..." )
        metrics = PerformanceMetrics(
            search_time_ms=45.2,
            memory_usage_mb=12.5,
            result_count=7,
            cache_hit_rate=0.85,
            operation_type="test_search"
        )
        
        metrics_dict = metrics.to_dict()
        expected_keys = {"search_time_ms", "memory_usage_mb", "result_count", 
                        "cache_hit_rate", "initialization_time_ms", "operation_type", "timestamp"}
        
        if set( metrics_dict.keys() ) == expected_keys:
            print( "✓ PerformanceMetrics created and serialized correctly" )
        else:
            print( f"✗ PerformanceMetrics missing expected keys. Got: {set(metrics_dict.keys())}, Expected: {expected_keys}" )
        
        # Test PerformanceMonitor
        print( "\nTesting PerformanceMonitor..." )
        monitor = PerformanceMonitor( "test_operation" )
        monitor.start()
        time.sleep( 0.01 )  # Small delay for timing test
        monitor.stop()
        
        test_metrics = monitor.get_metrics( result_count=5, cache_hit_rate=0.9 )
        
        if test_metrics.search_time_ms > 0 and test_metrics.operation_type == "test_operation":
            print( "✓ PerformanceMonitor timing and metrics collection working" )
        else:
            print( "✗ PerformanceMonitor not collecting metrics properly" )
        
        # Test interface contract
        print( "\nTesting abstract interface..." )
        try:
            # Should not be able to instantiate abstract class
            interface = SolutionSnapshotManagerInterface( {}, debug=False )
            print( "✗ Abstract class was instantiated (should not happen)" )
        except TypeError:
            print( "✓ Abstract class properly prevents direct instantiation" )
        
        print( "\n✓ SolutionSnapshotManagerInterface smoke test completed successfully" )
        
    except Exception as e:
        print( f"✗ Error during smoke test: {e}" )
        du.print_stack_trace( e, explanation="Interface smoke test failed", caller="quick_smoke_test()" )


if __name__ == "__main__":
    quick_smoke_test()