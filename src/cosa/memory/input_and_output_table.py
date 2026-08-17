import cosa.utils.util as du
from cosa.memory.embedding_manager import EmbeddingManager
from cosa.memory.embedding_provider import get_embedding_provider

from cosa.memory.question_embeddings_table import QuestionEmbeddingsTable
from cosa.memory.solution_snapshot import SolutionSnapshot as ss
from cosa.config.configuration_manager import ConfigurationManager
from cosa.utils.util_stopwatch import Stopwatch

from threading import Lock
from typing import Optional, Any

# @singleton
class InputAndOutputTable():
    """
    Manages input/output data storage in Postgres.

    Handles storage and retrieval of conversation history, including
    embeddings for semantic search. Storage and search run through
    InputAndOutputRepository on a short-lived get_db() session per call;
    query-embedding generation stays here in the memory layer.
    """
    def __init__( self, debug: bool=False, verbose: bool=False ) -> None:
        """
        Initialize the input/output table.

        Requires:
            - LUPIN_CONFIG_MGR_CLI_ARGS environment variable is set or defaults available

        Ensures:
            - Initializes the question embeddings table (generates input embeddings)
            - Opens no connection of its own; storage sessions are per-call

        Raises:
            - ConfigurationManager errors propagated
        """

        self.debug          = debug
        self.verbose        = verbose
        self._config_mgr    = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

        # Bug 574fd1dc Defect 2 — async-drop accounting. The async embedding
        # path drops a row on any failure; before this, the loss was
        # unquantified BY CONSTRUCTION (no counter existed, so "how many rows
        # have we lost" had no answer). These make the loss countable.
        self.async_failure_count = 0
        self.last_async_failure  = None
        self._async_failure_lock = Lock()
        self._embedding_mgr      = EmbeddingManager( debug=debug, verbose=verbose )
        self._embedding_provider = get_embedding_provider( debug=debug, verbose=verbose )

        # Get standardized embedding dimension from config
        self._embedding_dim = int( self._config_mgr.get( "embedding dimensions", default="768" ) )

        # The question-embedding cache table generates query/input embeddings.
        self._question_embeddings_tbl = QuestionEmbeddingsTable( debug=self.debug, verbose=self.verbose )

    def insert_io_row( self, date: str=du.get_current_date(), time: str=du.get_current_time( include_timezone=False ),
        input_type: str="", input: str="", input_embedding: list[float]=[], output_raw: str="", output_final: str="", output_final_embedding: list[float]=[], solution_path_wo_root: Optional[str]=None, async_embedding: bool=None
    ) -> None:
        """
        Insert a new row into the input/output table.
        
        Requires:
            - All string parameters are non-None
            - Embeddings are lists of floats or empty
            - async_embedding is boolean or None
            
        Ensures:
            - Row is added to table with provided data
            - Missing embeddings are generated if not provided (sync or async)
            - Returns immediately if async_embedding is True
            - Table row count is incremented
            
        Args:
            async_embedding: If True, generate embeddings asynchronously.
                           If None, use value from configuration.
                           If False, generate embeddings synchronously.
            
        Raises:
            - None (handles errors gracefully)
        """
        
        # ¡OJO! The embeddings are optional. If not provided, they will be generated.
        # In this case the only embedding that we are caching is the one that corresponds to the query/input, otherwise known
        # as the 'question' in the solution snapshot object and the 'query' in the self._question_embeddings_tbl object.
        # TODO: Make consistent the use of the terms 'input', 'query' and 'question'. While they are synonymous that's not necessarily clear to the casual reader.
        # Get debug text truncation length from config first (needed for timer message)
        debug_truncate_len = self._config_mgr.get( "debug text truncation length", default=48, return_type="int" )
        timer = Stopwatch( msg=f"insert_io_row( '{input[ :debug_truncate_len ]}...' )", silent=True )
        
        # Check if we should generate embeddings asynchronously
        if async_embedding is None:
            # Get from configuration, default to True
            async_embedding = self._config_mgr.get( "async embedding generation", default=True, return_type="boolean" )
            if self.debug and self.verbose: print( f"Got async_embedding from config: {async_embedding}" )
        
        # Generate embeddings based on async setting
        if async_embedding and (not input_embedding or not output_final_embedding):
            # Async mode: generate embeddings in background thread, then insert complete row
            if self.debug and self.verbose: print( "Using async embedding generation..." )
            timer.print( "Method returning immediately (async embedding generation started)", use_millis=True, end="\n" )
            
            # Start background thread to generate embeddings and insert row
            def generate_embeddings_and_insert():
                async_timer = Stopwatch( msg=f"Async embedding generation for '{input[:debug_truncate_len]}...'", silent=not (self.debug and self.verbose) )
                try:
                    # Generate missing embeddings with cache hit detection
                    if not input_embedding:
                        if self.debug and self.verbose: print( f"  Generating input embedding for: '{input[:debug_truncate_len]}...'" )
                        # Check if it's in cache by trying the has() method first
                        input_cache_hit = self._question_embeddings_tbl.has( input )
                        if self.debug and self.verbose: print( f"  Input embedding cache {'HIT' if input_cache_hit else 'MISS'}" )
                        final_input_embedding = self._question_embeddings_tbl.get_embedding( input )
                    else:
                        final_input_embedding = input_embedding
                        if self.debug and self.verbose: print( f"  Input embedding provided (skipping generation)" )
                    
                    if not output_final_embedding:
                        output_str = str(output_final) if output_final else ""
                        if self.debug and self.verbose: print( f"  Generating output embedding for: '{output_str[:debug_truncate_len]}...'" )
                        # Note: EmbeddingManager handles its own cache hit detection internally
                        final_output_embedding = self._embedding_provider.generate_embedding( output_final, content_type="prose" )
                    else:
                        final_output_embedding = output_final_embedding
                        if self.debug and self.verbose: print( f"  Output embedding provided (skipping generation)" )
                    
                    # Create complete row with all embeddings
                    new_row = [ {
                        "date"                             : date,
                        "time"                             : time,
                        "input_type"                       : input_type,
                        "input"                            : input,
                        "input_embedding"                  : final_input_embedding,
                        "output_raw"                       : output_raw,
                        "output_final"                     : output_final,
                        "output_final_embedding"           : final_output_embedding,
                        "solution_path_wo_root"            : solution_path_wo_root
                    } ]
                    
                    # Insert complete row (backend-dispatched storage leaf)
                    self._store_io_row( new_row[ 0 ] )

                    async_timer.print( f"Async completion! I/O table now has {self._row_count()} rows", use_millis=True )
                    
                    if self.debug:
                        print( f"  Input embedding dimensions: {len(final_input_embedding)}" )
                        print( f"  Output embedding dimensions: {len(final_output_embedding)}" )
                        
                except Exception as e:
                    # Bug 574fd1dc Defect 2: this handler used to print and return,
                    # so a failed row vanished with NO counter and NO record. The
                    # caller already returned "success" the moment the work was
                    # queued, so nothing upstream ever learns the write was lost —
                    # the only evidence was a console banner someone had to read by
                    # eye, which is exactly how this surfaced. The drop is still a
                    # drop (no dead-letter store yet), but it is now COUNTED, so
                    # "how many rows have we lost" stops being unanswerable.
                    self._record_async_failure( input, e )
                    async_timer.print( f"FAILED after", use_millis=True )
                    du.print_banner( f"ASYNC EMBEDDING GENERATION FAILED", expletive=True )
                    print( f"Failed to generate embeddings and insert row for input: '{input[:debug_truncate_len]}...'" )
                    print( f"Error: {e}" )
                    print( f"Rows dropped by this failure path since process start: {self.async_failure_count}" )
                    du.print_stack_trace( e, explanation="Async embedding generation failed", caller="insert_io_row async thread" )
            
            # Submit to the shared bounded pool (bug 81854972) instead of spawning
            # an unbounded daemon thread per call. The pool caps GLOBAL embedding
            # concurrency so the asyncio event loop is never starved, and bounds the
            # backlog so a sustained burst can't grow memory without limit. A full
            # backlog drops the work (backpressure) — the caller never blocks.
            from cosa.memory.embedding_pool import get_embedding_pool
            get_embedding_pool( self._config_mgr, debug=self.debug ).submit( generate_embeddings_and_insert )
            
        else:
            # Sync mode: generate embeddings before inserting (original behavior)
            if self.debug and self.verbose: print( "Using synchronous embedding generation..." )
            
            new_row = [ {
                "date"                             : date,
                "time"                             : time,
                "input_type"                       : input_type,
                "input"                            : input,
                "input_embedding"                  : input_embedding if input_embedding else self._question_embeddings_tbl.get_embedding( input ),
                "output_raw"                       : output_raw,
                "output_final"                     : output_final,
                "output_final_embedding"           : output_final_embedding if output_final_embedding else self._embedding_provider.generate_embedding( output_final, content_type="prose" ),
                "solution_path_wo_root"            : solution_path_wo_root
            } ]
            self._store_io_row( new_row[ 0 ] )
            timer.print( f"Done! I/O table now has {self._row_count()} rows", use_millis=True, end="\n" )

    def _record_async_failure( self, input_text: str, error: Exception ) -> None:
        """
        Count one dropped row from the async embedding path (bug `574fd1dc`).

        The row itself is still lost — this does NOT retry or dead-letter it.
        What it changes is that the loss becomes COUNTABLE. Before this, the
        handler printed a banner and returned, so the only record of a dropped
        row was a console line in a container log, and "how many have we lost"
        was unanswerable by construction.

        Called from the embedding-pool worker thread, so the increment is
        locked: the pool runs several workers concurrently and a bare `+= 1`
        on a shared int is a read-modify-write that can silently lose counts —
        which would make the instrument understate exactly the quantity it
        exists to measure.

        Requires:
            - input_text is the row's input string (may be empty)
            - error is the exception that killed the insert

        Ensures:
            - async_failure_count increments by exactly one per call
            - last_async_failure holds ( truncated input, exception type, str(error) )
              for the MOST RECENT failure
            - never raises — a failure in the failure recorder must not mask
              the original error
        """
        with self._async_failure_lock:
            self.async_failure_count += 1
            self.last_async_failure   = (
                input_text[ :100 ] if input_text else "",
                type( error ).__name__,
                str( error )
            )

    def _store_io_row( self, row: dict ) -> None:
        """
        Storage leaf for one I/O row.

        Requires:
            - row is a dict of input_and_output column → value

        Ensures:
            - inserts the row via InputAndOutputRepository
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.input_and_output_repository import InputAndOutputRepository
        with get_db() as session:
            InputAndOutputRepository( session ).insert_io_row( **row )

    def _row_count( self ) -> int:
        """
        Row count for the input_and_output store.

        Ensures:
            - returns InputAndOutputRepository.count()
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.input_and_output_repository import InputAndOutputRepository
        with get_db() as session:
            return InputAndOutputRepository( session ).count()

    # ----------------------------------------------------------------------- #
    # Reads. Query-embedding generation stays in the memory layer (via the
    # question-embedding cache); the repository does the dot search + scans.
    # ----------------------------------------------------------------------- #
    def get_knn_by_input( self, search_terms: str, k: int=10 ) -> list[dict]:
        """
        Get k-nearest neighbors by input embedding.

        Requires:
            - search_terms is a non-empty string
            - k is a positive integer

        Ensures:
            - Returns up to k most similar inputs, dot-product ranked
            - Each record carries input, output_final, input_embedding, _distance
            - Returns empty list if the query embedding is unavailable

        Raises:
            - None
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.input_and_output_repository import InputAndOutputRepository

        search_terms_embedding = self._question_embeddings_tbl.get_embedding( search_terms )
        if not search_terms_embedding:
            du.print_banner( "SKIPPING KNN SEARCH - NO EMBEDDINGS" )
            print( "Cannot perform similarity search without embeddings" )
            print( "Returning empty results" )
            return []

        with get_db() as session:
            hits = InputAndOutputRepository( session ).get_knn_by_input( search_terms_embedding, k=k )
            # Mirror the LanceDB record shape: input, output_final, input_embedding, _distance
            # (_distance = 1 - dot; similarity_pct = dot * 100 → _distance = 1 - pct/100).
            return [
                {
                    "input":           entity.input,
                    "output_final":    entity.output_final,
                    "input_embedding": list( entity.input_embedding ) if entity.input_embedding is not None else [],
                    "_distance":       1.0 - ( similarity_pct / 100.0 ),
                }
                for similarity_pct, entity in hits
            ]

    def get_all_io( self, max_rows: int=1000 ) -> list[dict]:
        """
        Get all input/output pairs up to max_rows.

        Requires:
            - max_rows is a positive integer

        Ensures:
            - Returns a bounded list of dicts with date, time, input_type, input, output_final

        Raises:
            - None
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.input_and_output_repository import InputAndOutputRepository
        with get_db() as session:
            rows = InputAndOutputRepository( session ).get_all_io( max_rows=max_rows )
            return [ self._io_row_to_dict( r ) for r in rows ]

    def get_io_stats_by_input_type( self, max_rows: int=1000 ) -> dict[str, int]:
        """
        Get statistics grouped by input_type.

        Requires:
            - max_rows is a positive integer

        Ensures:
            - Returns a dictionary mapping input_type to count

        Raises:
            - None
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.input_and_output_repository import InputAndOutputRepository
        with get_db() as session:
            return InputAndOutputRepository( session ).get_io_stats_by_input_type( max_rows=max_rows )

    def get_all_qnr( self, max_rows: int=50 ) -> list[dict]:
        """
        Get all questions and responses for agent router commands.

        Requires:
            - max_rows is a positive integer

        Ensures:
            - Returns agent-router interactions as 5-key dicts, bounded by max_rows

        Raises:
            - None
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.input_and_output_repository import InputAndOutputRepository
        with get_db() as session:
            rows = InputAndOutputRepository( session ).get_all_qnr( max_rows=max_rows )
            return [ self._io_row_to_dict( r ) for r in rows ]

    @staticmethod
    def _io_row_to_dict( entity ) -> dict:
        """Project an InputAndOutput entity to the 5-key record shape callers expect."""
        return {
            "date":         entity.date,
            "time":         entity.time,
            "input_type":   entity.input_type,
            "input":        entity.input,
            "output_final": entity.output_final,
        }


def quick_smoke_test():
    """Run comprehensive smoke test for InputAndOutputTable with async support."""
    du.print_banner( "InputAndOutputTable Smoke Test", prepend_nl=True )
    
    import time
    
    try:
        # Initialize table
        print( "Test 1: InputAndOutputTable initialization..." )
        io_table = InputAndOutputTable( debug=True, verbose=True )
        print( "✓ InputAndOutputTable initialized successfully" )
        
        initial_rows = io_table._row_count()
        print( f"Initial table rows: {initial_rows}" )
        
        # Helper function to wait for async completion
        def wait_for_async_completion( expected_rows, timeout_seconds=30 ):
            """Poll database until expected rows appear or timeout"""
            start_time = time.time()
            while time.time() - start_time < timeout_seconds:
                current_rows = io_table._row_count()
                if current_rows >= expected_rows:
                    return True, current_rows
                time.sleep( 0.1 )  # Poll every 100ms
            return False, io_table._row_count()
        
        # Test 2: Synchronous insertion
        print( f"\nTest 2: Synchronous insertion..." )
        sync_input = "What time is it?"
        sync_output = "The current time is 3:30 PM."
        
        io_table.insert_io_row(
            input_type="smoke_test_sync",
            input=sync_input,
            output_raw=sync_output,
            output_final=sync_output,
            async_embedding=False  # Force sync mode
        )
        
        sync_rows = io_table._row_count()
        print( f"✓ Sync insertion completed. Rows: {initial_rows} → {sync_rows}" )
        
        # Test 3: Asynchronous insertion
        print( f"\nTest 3: Asynchronous insertion..." )
        async_input = "How is the weather today?"
        async_output = "The weather is sunny with a temperature of 75°F."
        expected_async_rows = sync_rows + 1
        
        io_table.insert_io_row(
            input_type="smoke_test_async",
            input=async_input,
            output_raw=async_output,
            output_final=async_output,
            async_embedding=True  # Force async mode
        )
        
        print( f"Method returned immediately. Waiting for async completion..." )
        async_success, final_async_rows = wait_for_async_completion( expected_async_rows )
        
        if async_success:
            print( f"✓ Async insertion completed. Rows: {sync_rows} → {final_async_rows}" )
        else:
            print( f"✗ Async insertion timed out or failed. Rows: {sync_rows} → {final_async_rows}" )
        
        # Test 4: Configuration-based async (default behavior)
        print( f"\nTest 4: Configuration-based async behavior..." )
        config_input = "Tell me a joke"
        config_output = "Why don't scientists trust atoms? Because they make up everything!"
        expected_config_rows = final_async_rows + 1
        
        io_table.insert_io_row(
            input_type="smoke_test_config",
            input=config_input,
            output_raw=config_output,
            output_final=config_output
            # async_embedding=None - uses config default
        )
        
        print( f"Method returned (using config default). Waiting for completion..." )
        config_success, final_config_rows = wait_for_async_completion( expected_config_rows )
        
        if config_success:
            print( f"✓ Config-based insertion completed. Rows: {final_async_rows} → {final_config_rows}" )
        else:
            print( f"✗ Config-based insertion timed out. Rows: {final_async_rows} → {final_config_rows}" )
        
        # Test 5: Cache hit testing
        print( f"\nTest 5: Cache hit testing..." )
        cache_input = sync_input  # Reuse same input to trigger cache hit
        cache_output = "It's still 3:30 PM (from cache test)."
        expected_cache_rows = final_config_rows + 1
        
        print( f"Inserting duplicate input to test cache hits: '{cache_input[:32]}...'" )
        io_table.insert_io_row(
            input_type="smoke_test_cache",
            input=cache_input,
            output_raw=cache_output,
            output_final=cache_output,
            async_embedding=True
        )
        
        cache_success, final_cache_rows = wait_for_async_completion( expected_cache_rows )
        
        if cache_success:
            print( f"✓ Cache hit test completed. Rows: {final_config_rows} → {final_cache_rows}" )
        else:
            print( f"✗ Cache hit test timed out. Rows: {final_config_rows} → {final_cache_rows}" )
        
        # Test 6: Debug truncation configuration
        print( f"\nTest 6: Debug truncation configuration..." )
        current_truncate_len = io_table._config_mgr.get( "debug text truncation length", default=48, return_type="int" )
        print( f"Current debug truncation length: {current_truncate_len}" )
        
        long_input = "This is a very long input message that should be truncated in debug output to test the configurable truncation length feature we just implemented."
        long_output = "This is a correspondingly long output message that should also be truncated appropriately."
        
        io_table.insert_io_row(
            input_type="smoke_test_truncation",
            input=long_input,
            output_raw=long_output,
            output_final=long_output,
            async_embedding=True
        )
        print( f"✓ Debug truncation test completed (check output above for truncation)" )
        
        # Test 7: KNN search functionality
        print( f"\nTest 7: Semantic search (KNN) functionality..." )
        try:
            search_results = io_table.get_knn_by_input( "time", k=3 )
            print( f"Found {len(search_results)} similar results for 'time'" )
            
            if search_results:
                print( f"Result structure keys: {list(search_results[0].keys())}" )
                
                for i, result in enumerate( search_results[:2] ):  # Show first 2
                    input_text = result.get('input', 'N/A')[:40]
                    output_text = result.get('output_final', 'N/A')[:40]
                    distance = result.get('_distance', 'N/A')
                    
                    # Handle distance formatting
                    if isinstance(distance, (int, float)):
                        distance_str = f"{distance:.3f}"
                    else:
                        distance_str = str(distance)
                    
                    print( f"  {i+1}. '{input_text}...' → '{output_text}...' (distance: {distance_str})" )
                
                print( f"✓ KNN search working" )
            else:
                print( f"✗ KNN search returned no results" )
                
        except Exception as search_error:
            print( f"✗ KNN search failed: {search_error}" )
            print( f"  Error type: {type(search_error).__name__}" )
        
        # Final summary
        final_total_rows = io_table._row_count()
        rows_added = final_total_rows - initial_rows
        print( f"\n✓ Smoke test summary:" )
        print( f"  Initial rows: {initial_rows}" )
        print( f"  Final rows: {final_total_rows}" )
        print( f"  Rows added: {rows_added}" )
        print( f"  Tests completed: 7/7" )
        
    except Exception as e:
        print( f"✗ Error during smoke test: {e}" )
        du.print_stack_trace( e, explanation="Smoke test failed", caller="quick_smoke_test()" )
    
    print( "\n✓ InputAndOutputTable smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()
    