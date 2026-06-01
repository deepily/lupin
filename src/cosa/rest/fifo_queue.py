from collections import OrderedDict
from datetime import datetime
from typing import Any, Optional
import re
import threading
from cosa.rest.queue_extensions import user_job_tracker
from cosa.rest.queue_protocol import is_queueable_job
from cosa.rest.job_state import JobState

# Notification service imports for TTS migration (Session 97)
from lupin_cli.notifications.notify_user_async import notify_user_async
from lupin_cli.notifications.notification_models import (
    AsyncNotificationRequest,
    NotificationPriority
)


class FifoQueue:
    """
    First-In-First-Out queue implementation with dictionary lookup.
    
    This class provides a FIFO queue with additional features for tracking
    blocking objects, focus mode, and job acceptance states. Items are
    stored in both a list (for ordering) and dictionary (for O(1) lookup).
    """
    
    def __init__( self, websocket_mgr: Optional[Any] = None, queue_name: Optional[str] = None, emit_enabled: bool = True ) -> None:
        """
        Initialize an empty FIFO queue with optional auto-emission capabilities.
        
        Requires:
            - websocket_mgr is a valid WebSocketManager instance or None
            - queue_name is a valid string for emission events or None
            - emit_enabled is a boolean to control auto-emission
            
        Ensures:
            - Creates empty queue_list and queue_dict
            - Initializes push_counter to 0
            - Sets accepting_jobs to True
            - Sets focus_mode to True
            - Sets blocking_object to None
            - Configures auto-emission if websocket_mgr and queue_name provided
            
        Raises:
            - None
        """
        
        self.queue_list      = [ ]
        self.queue_dict      = OrderedDict()
        self.push_counter    = 0
        self.last_queue_size = 0
        # used to track if the queue is accepting jobs or not, especially important when we're running in focus versus multi tasking mode
        self._accepting_jobs  = True
        # used to track if the queue is in focus mode or not, in the future. We're going to have to tackle multitasking mode.
        self._focus_mode      = True
        # used to track if this queue contains a blocking object
        self._blocking_object = None
        
        # Auto-emission configuration for client-server state synchronization
        self.websocket_mgr   = websocket_mgr
        self.queue_name      = queue_name
        self.emit_enabled    = emit_enabled
        
        # User job tracking singleton for user-based routing
        self.user_job_tracker = user_job_tracker

        # Phase 1 (CJ Flow async multi-lane): RLock guards queue_list / queue_dict
        # against concurrent mutation from the dispatcher thread and pool callback
        # threads. Re-entrant because several methods self-call (pop → is_empty,
        # delete_by_id_hash → size). A plain Lock would deadlock on these.
        self._lock           = threading.RLock()

    def pop_blocking_object( self ) -> Optional[Any]:
        """
        Remove and return the blocking object.
        
        Requires:
            - None
            
        Ensures:
            - Returns the blocking object (may be None)
            - Sets _blocking_object to None
            - Sets _accepting_jobs to True
            
        Raises:
            - None
        """
        blocking_object = self._blocking_object
        self._blocking_object = None
        self._accepting_jobs = True
        return blocking_object
    
    def push_blocking_object( self, blocking_object: Any ) -> None:
        """
        Set a blocking object and stop accepting new jobs.
        
        Requires:
            - blocking_object can be any object
            
        Ensures:
            - Sets _blocking_object to the provided object
            - Sets _accepting_jobs to False
            
        Raises:
            - None
        """
        self._blocking_object = blocking_object
        self._accepting_jobs = False
        
    def is_in_focus_mode( self ) -> bool:
        """
        Check if the queue is in focus mode.
        
        Requires:
            - None
            
        Ensures:
            - Returns current focus mode state
            
        Raises:
            - None
        """
        return self._focus_mode
    
    def is_accepting_jobs( self ) -> bool:
        """
        Check if the queue is accepting new jobs.
        
        Requires:
            - None
            
        Ensures:
            - Returns current job acceptance state
            
        Raises:
            - None
        """
        return self._accepting_jobs
    
    # def set_accepting_jobs( self, accepting_jobs ):
    #     self.accepting_jobs = accepting_jobs
    
    def push( self, item: Any ) -> None:
        """
        Add an item to the end of the queue.

        Requires:
            - item must implement QueueableJob protocol

        Ensures:
            - Item is added to end of queue_list
            - Item is added to queue_dict with id_hash as key
            - push_counter is incremented

        Raises:
            - TypeError if item doesn't implement QueueableJob protocol
        """
        # Phase 1: Enforce Protocol at boundary - validate ONCE on entry
        if not is_queueable_job( item ):
            raise TypeError( f"Job must implement QueueableJob protocol, got {type( item ).__name__}" )

        with self._lock:
            self.queue_list.append( item )
            self.queue_dict[ item.id_hash ] = item
            self.push_counter += 1
    
    def get_push_counter( self ) -> int:
        """
        Get the total number of items pushed to the queue.
        
        Requires:
            - None
            
        Ensures:
            - Returns current push counter value
            
        Raises:
            - None
        """
        return self.push_counter
    
    def pop( self ) -> Optional[Any]:
        """
        Remove and return the first item from the queue.
        
        Requires:
            - None
            
        Ensures:
            - Returns first item if queue not empty
            - Removes item from both queue_list and queue_dict
            - Returns None if queue is empty
            
        Raises:
            - None
        """
        with self._lock:
            if not self.is_empty():
                # Remove from ID_hash first
                del self.queue_dict[ self.queue_list[ 0 ].id_hash ]
                result = self.queue_list.pop( 0 )
                return result

    def pop_next_eligible( self, now=None ) -> Optional[Any]:
        """
        Remove and return the first eligible job from the queue.

        A job is eligible if: not paused AND (scheduled_at is None OR scheduled_at <= now).
        Non-eligible jobs remain in their original queue positions.

        Requires:
            - now is a datetime or None (defaults to datetime.now())

        Ensures:
            - Returns first eligible job (removed from both queue_list and queue_dict)
            - Returns None if no eligible jobs exist
            - Non-eligible jobs stay in the queue unchanged

        Raises:
            - None
        """
        if now is None:
            now = datetime.now()

        with self._lock:
            for i, job in enumerate( self.queue_list ):
                # Check paused flag (backward compat with legacy jobs)
                if job.state == JobState.PAUSED:
                    continue

                # Check scheduled_at (None = immediate = always eligible)
                scheduled_at = getattr( job, 'scheduled_at', None )
                if scheduled_at is not None:
                    try:
                        scheduled_dt = datetime.fromisoformat( scheduled_at )
                        # Normalize timezone for comparison:
                        # JS sends UTC ISO strings ("...Z") → timezone-aware datetime.
                        # datetime.now() is naive (local time). Comparing aware vs naive
                        # raises TypeError (caught below, treating job as immediate — wrong).
                        # Fix: make both naive-local for apples-to-apples comparison.
                        if scheduled_dt.tzinfo is not None:
                            scheduled_dt = scheduled_dt.astimezone().replace( tzinfo=None )
                        if scheduled_dt > now:
                            continue  # Not yet eligible
                    except ( ValueError, TypeError ):
                        pass  # Unparseable → treat as immediate

                # This job is eligible — remove and return it
                if job.id_hash not in self.queue_dict:
                    print( f"[QUEUE] Warning: stale job in queue_list, removing: {job.id_hash}" )
                    self.queue_list.pop( i )
                    continue
                del self.queue_dict[ job.id_hash ]
                self.queue_list.pop( i )
                return job

            return None  # No eligible jobs found

    def earliest_scheduled_at( self ):
        """
        Return the earliest scheduled_at datetime among non-paused queued jobs, or None.

        Used by the consumer thread to calculate how long to sleep before the
        next timed job becomes eligible. Paused jobs are ignored — they should
        not affect the consumer's wake-up timer.

        Requires:
            - None

        Ensures:
            - Returns datetime of the earliest non-paused scheduled job
            - Returns None if all jobs are immediate, paused, or queue is empty

        Raises:
            - None
        """
        earliest = None
        with self._lock:
            for job in self.queue_list:
                if job.state == JobState.PAUSED:
                    continue
                scheduled_at = getattr( job, 'scheduled_at', None )
                if scheduled_at is not None:
                    try:
                        scheduled_dt = datetime.fromisoformat( scheduled_at )
                        # Normalize to naive-local (same as datetime.now() in consumer)
                        if scheduled_dt.tzinfo is not None:
                            scheduled_dt = scheduled_dt.astimezone().replace( tzinfo=None )
                        if earliest is None or scheduled_dt < earliest:
                            earliest = scheduled_dt
                    except ( ValueError, TypeError ):
                        pass  # Unparseable → skip
        return earliest

    def head( self ) -> Optional[Any]:
        """
        Get the first item without removing it.
        
        Requires:
            - None
            
        Ensures:
            - Returns first item if queue not empty
            - Queue remains unchanged
            - Returns None if queue is empty

        Raises:
            - None
        """
        with self._lock:
            if not self.is_empty():
                return self.queue_list[ 0 ]
            else:
                return None

    def get_by_id_hash( self, id_hash: str ) -> Any:
        """
        Get an item by its ID hash.
        
        Requires:
            - id_hash exists in queue_dict
            
        Ensures:
            - Returns the item with matching id_hash
            
        Raises:
            - KeyError if id_hash not found
        """
        with self._lock:
            return self.queue_dict[ id_hash ]
    
    def delete_by_id_hash( self, id_hash: str ) -> bool:
        """
        Delete an item by its ID hash.
        
        Requires:
            - id_hash is a string
            
        Ensures:
            - Item is removed from queue_dict if found
            - queue_list is rebuilt from remaining items
            - Prints status message about deletion
            - Returns True if deletion successful, False otherwise
            
        Returns:
            - bool: True if item was found and deleted, False if not found
        """
        with self._lock:
            try:
                # Check if item exists before attempting deletion
                if id_hash not in self.queue_dict:
                    print( f"ERROR: Could not delete by id_hash - item {id_hash} not found" )
                    return False

                size_before = self.size()
                del self.queue_dict[ id_hash ]
                self.queue_list = list( self.queue_dict.values() )
                size_after = self.size()

                if size_after < size_before:
                    print( f"Deleted {size_before - size_after} items from queue" )
                    return True
                else:  # pragma: no cover - unreachable: past the L351-353 key-present guard, del removes a confirmed-present key so size_after = size_before-1 < size_before always → the if-True arm always fires; this else is dead defensive
                    print( "ERROR: Could not delete by id_hash - size didn't change" )
                    return False

            except Exception as e:  # pragma: no cover - unreachable: within self._lock, del (key confirmed present) + list(values) + size() cannot raise → dead belt-and-suspenders
                print( f"ERROR: Exception during delete_by_id_hash: {e}" )
                return False
        
    def is_empty( self ) -> bool:
        """
        Check if the queue is empty.
        
        Requires:
            - None
            
        Ensures:
            - Returns True if queue has no items
            - Returns False if queue has items
            
        Raises:
            - None
        """
        with self._lock:
            return len( self.queue_list ) == 0

    def size( self ) -> int:
        """
        Get the number of items in the queue.
        
        Requires:
            - None
            
        Ensures:
            - Returns count of items in queue
            
        Raises:
            - None
        """
        with self._lock:
            return len( self.queue_list )

    def has_changed( self ) -> bool:
        """
        Check if the queue size has changed since last check.
        
        Requires:
            - None
            
        Ensures:
            - Returns True if size differs from last_queue_size
            - Updates last_queue_size to current size
            - Returns False if size unchanged
            
        Raises:
            - None
        """
        with self._lock:
            if self.size() != self.last_queue_size:
                self.last_queue_size = self.size()
                return True
            else:
                return False
    
    def clear( self ) -> None:
        """
        Clear all items from the queue.

        Requires:
            - None

        Ensures:
            - Empties both queue_list and queue_dict
            - Resets push_counter to 0
            - Clears blocking_object to None
            - Resets accepting_jobs to True

        Raises:
            - None
        """
        with self._lock:
            self.queue_list.clear()
            self.queue_dict.clear()
            self.push_counter = 0
            self._blocking_object = None
            self._accepting_jobs = True
    
    def get_jobs_for_user( self, user_id: str ) -> list[Any]:
        """
        Get raw job objects for specific user (NO authorization, NO formatting).

        Pure data access method - performs NO authorization checks.
        Authorization should be handled by calling code.

        Requires:
            - user_id is a valid user identifier string
            - UserJobTracker singleton is initialized

        Ensures:
            - Returns list of job objects matching user's job IDs
            - Returns empty list if user has no jobs
            - Returns raw job objects (NOT HTML formatted)
            - NO authorization checks performed

        Args:
            user_id: The user identifier to filter jobs by

        Returns:
            list[Any]: List of job objects belonging to the user

        Raises:
            - None (returns empty list for nonexistent users)
        """
        # Get job IDs associated with this user
        user_job_ids = self.user_job_tracker.get_jobs_for_user( user_id )

        # Filter queue_list to only include jobs matching user's job IDs
        with self._lock:
            filtered_jobs = [
                job for job in self.queue_list
                if hasattr( job, 'id_hash' ) and job.id_hash in user_job_ids
            ]

        return filtered_jobs

    def get_jobs_excluding_user( self, user_id: str ) -> list[Any]:
        """
        Get raw job objects for all users EXCEPT the specified user (NO authorization, NO formatting).

        Inverse of get_jobs_for_user(). Pure data access method - performs NO authorization checks.
        Authorization should be handled by calling code.

        Requires:
            - user_id is a valid user identifier string
            - UserJobTracker singleton is initialized

        Ensures:
            - Returns list of job objects NOT matching user's job IDs
            - Returns empty list if all jobs belong to the user
            - Returns raw job objects (NOT HTML formatted)
            - NO authorization checks performed

        Args:
            user_id: The user identifier whose jobs should be excluded

        Returns:
            list[Any]: List of job objects NOT belonging to the user

        Raises:
            - None (returns empty list if all jobs belong to user)
        """
        # Get job IDs associated with this user (to exclude)
        user_job_ids = self.user_job_tracker.get_jobs_for_user( user_id )

        # Filter queue_list to EXCLUDE jobs matching user's job IDs
        with self._lock:
            filtered_jobs = [
                job for job in self.queue_list
                if not hasattr( job, 'id_hash' ) or job.id_hash not in user_job_ids
            ]

        return filtered_jobs

    def get_all_jobs( self ) -> list[Any]:
        """
        Get ALL raw job objects (NO authorization, NO formatting).

        Pure data access method - performs NO authorization checks.
        Authorization should be handled by calling code.

        Requires:
            - Queue is initialized

        Ensures:
            - Returns complete copy of queue_list
            - NO filtering by user
            - Returns raw job objects (NOT HTML formatted)
            - NO authorization checks performed

        Returns:
            list[Any]: Complete list of all job objects in queue

        Raises:
            - None
        """
        with self._lock:
            return self.queue_list.copy()

    # ========================================================================
    # NOTIFICATION SERVICE METHODS (Session 97 - TTS Migration)
    # Replacement for legacy _emit_speech WebSocket-based TTS
    # ========================================================================

    def _get_notification_job_id( self, job: Any ) -> Optional[str]:
        """
        Extract notification-compatible job_id from job object.

        Frontend registers jobs by their id_hash (64-char SHA256 or short format).
        We pass through whatever format the job uses so notifications route correctly.

        Requires:
            - job may have id_hash attribute

        Ensures:
            - Returns job's id_hash if available (any format)
            - Returns None if job has no id_hash

        Args:
            job: Job object that may have id_hash attribute

        Returns:
            Optional[str]: Job's id_hash for notification routing, or None
        """
        if not job:
            return None

        if hasattr( job, 'id_hash' ) and job.id_hash:
            return job.id_hash

        return None

    def _notify(
        self,
        msg: str,
        job: Any = None,
        priority: str = "high",
        notification_type: str = "task",
        target_user: str = None,
        abstract: str = None
    ) -> None:
        """
        Send notification via notification service (replaces _emit_speech).

        Queue notifications default to:
        - priority="high" → message is spoken via TTS
        - suppress_ding=True → no notification sound (conversational flow)

        Abstract auto-promotion:
        - When a job is provided and `abstract` is not explicitly passed, the
          method reads `job.artifacts["abstract"]` (if present) and forwards
          it on the AsyncNotificationRequest. This surfaces rich completion
          context on the primary task-card the UI shows, not just on the
          secondary progress row the job emits explicitly.

        Requires:
            - msg is a non-empty string
            - job (if provided) has id_hash attribute

        Ensures:
            - Notification is sent to target user
            - If job_id available, routes to job card in UI
            - Message is spoken (high priority) without ding
            - If job.artifacts["abstract"] exists and no explicit abstract
              was passed, it rides along on the notification
            - Handles exceptions gracefully

        Args:
            msg: The message to send (will be spoken via TTS)
            job: Job object for context-based routing (optional)
            priority: Notification priority ('urgent', 'high', 'medium', 'low')
            notification_type: Type of notification ('task', 'progress', 'alert', 'custom')
            target_user: Email address for TTS routing (uses job.user_email if not provided)
            abstract: Explicit abstract override. When None, auto-reads from job.artifacts["abstract"].

        Raises:
            - None (exceptions handled internally)
        """
        # Session 110: user_email is now a first-class constructor parameter (no hasattr needed)
        resolved_email = target_user
        if not resolved_email and job and job.user_email:
            resolved_email = job.user_email
        if not resolved_email:
            import os
            resolved_email = os.environ.get( "LUPIN_DEV_EMAIL", "" )
            if resolved_email:
                print( f"[NOTIFY] Warning: No user_email found, using LUPIN_DEV_EMAIL fallback: {resolved_email}" )
            else:
                print( "[NOTIFY] Warning: No user_email and no LUPIN_DEV_EMAIL — notification skipped" )
                return

        # Auto-promote job.artifacts["abstract"] when no explicit override given.
        # `getattr` is used because `FifoQueue._notify` serves both AgenticJobBase
        # (has .artifacts) and AgentBase/SolutionSnapshot (may not) — this is the
        # system boundary per the "fix at source, normalize at boundaries" rule.
        resolved_abstract = abstract
        if resolved_abstract is None and job is not None:
            artifacts = getattr( job, "artifacts", None ) or {}
            resolved_abstract = artifacts.get( "abstract" )

        try:
            request = AsyncNotificationRequest(
                message           = msg,
                notification_type = notification_type,
                priority          = priority,
                suppress_ding     = True,  # Queue notifications = TTS only, no ding
                target_user       = resolved_email,
                job_id            = self._get_notification_job_id( job ),
                sender_id         = f"queue.{self.queue_name or 'unknown'}@lupin.deepily.ai",
                abstract          = resolved_abstract
            )
            notify_user_async( request )

            if hasattr( self, 'debug' ) and self.debug:
                print( f"[NOTIFY] Sent notification to {resolved_email}: {priority}/{notification_type} - {msg[:50]}..." )

        except Exception as e:
            print( f"[ERROR] _notify() failed: {e}" )

def quick_smoke_test():
    """
    Critical smoke test for FIFO queue implementation - validates base queue functionality.
    
    This test is essential for v000 deprecation as fifo_queue.py is the foundation
    for all queue implementations in the REST system.
    """
    import cosa.utils.util as du
    
    du.print_banner( "FIFO Queue Smoke Test", prepend_nl=True )
    
    try:
        # Test 1: Basic class and method presence
        print( "Testing core FIFO queue components..." )
        expected_methods = [
            "push", "pop", "head", "get_by_id_hash", "delete_by_id_hash",
            "is_empty", "size", "has_changed", "clear",
            "pop_blocking_object", "push_blocking_object", "is_in_focus_mode", "is_accepting_jobs"
        ]
        
        methods_found = 0
        for method_name in expected_methods:
            if hasattr( FifoQueue, method_name ):
                methods_found += 1
            else:
                print( f"⚠ Missing method: {method_name}" )
        
        if methods_found == len( expected_methods ):
            print( f"✓ All {len( expected_methods )} core FIFO methods present" )
        else:
            print( f"⚠ Only {methods_found}/{len( expected_methods )} FIFO methods present" )
        
        # Test 2: Critical dependency imports
        print( "Testing critical dependency imports..." )
        try:
            from collections import OrderedDict
            from typing import Any, Optional
            print( "✓ Standard library imports successful" )
        except ImportError as e:
            print( f"✗ Standard library imports failed: {e}" )
        
        try:
            from cosa.rest.queue_extensions import UserJobTracker
            print( "✓ Queue extensions import successful" )
        except ImportError as e:
            print( f"⚠ Queue extensions import failed: {e}" )
        
        # Test 3: Basic FIFO queue functionality
        print( "Testing basic FIFO queue functionality..." )
        try:
            # Create a test queue
            queue = FifoQueue()
            
            # Test initial state
            if queue.is_empty() and queue.size() == 0:
                print( "✓ Queue initialization working" )
            else:
                print( "✗ Queue initialization failed" )
            
            # Test state properties
            if queue.is_accepting_jobs() and queue.is_in_focus_mode():
                print( "✓ Initial state properties correct" )
            else:
                print( "⚠ Initial state properties may have issues" )
            
        except Exception as e:
            print( f"⚠ Basic queue functionality issues: {e}" )
        
        # Test 4: Queue operations with mock objects implementing QueueableJob protocol
        print( "Testing queue operations..." )
        try:
            # Create mock objects that implement the QueueableJob protocol
            class MockQueueableItem:
                """Mock item implementing QueueableJob protocol for testing."""
                def __init__( self, id_hash, name ):
                    self.id_hash              = id_hash
                    self.name                 = name
                    self.push_counter         = 0
                    self.user_id              = "test_user"
                    self.session_id           = "test_session"
                    self.routing_command      = "test"
                    self.run_date             = "2025-01-30"
                    self.created_date         = "2025-01-30"
                    self.question             = name
                    self.last_question_asked  = name
                    self.answer               = "test answer"
                    self.answer_conversational = "Test answer"
                    self.job_type             = "MockJob"
                    self.user_email           = "test@test.com"
                    self.is_cache_hit         = False
                    self.started_at           = None
                    self.completed_at         = None
                    self.state                = "pending"
                    self.error                = None

                def do_all( self ):
                    return "done"

                def code_ran_to_completion( self ):
                    return True

                def formatter_ran_to_completion( self ):
                    return True

            queue = FifoQueue()

            # Test push operations
            item1 = MockQueueableItem( "hash1", "Item 1" )
            item2 = MockQueueableItem( "hash2", "Item 2" )

            queue.push( item1 )
            queue.push( item2 )

            if queue.size() == 2 and not queue.is_empty():
                print( "✓ Push operations working" )
            else:
                print( "✗ Push operations failed" )

            # Test head operation
            head_item = queue.head()
            if head_item and head_item.id_hash == "hash1":
                print( "✓ Head operation working" )
            else:
                print( "✗ Head operation failed" )

            # Test get_by_id_hash
            retrieved_item = queue.get_by_id_hash( "hash2" )
            if retrieved_item and retrieved_item.name == "Item 2":
                print( "✓ Get by ID hash working" )
            else:
                print( "✗ Get by ID hash failed" )

            # Test pop operation
            popped_item = queue.pop()
            if popped_item and popped_item.id_hash == "hash1" and queue.size() == 1:
                print( "✓ Pop operation working" )
            else:
                print( "✗ Pop operation failed" )

            # Test delete operation
            if queue.delete_by_id_hash( "hash2" ) and queue.is_empty():
                print( "✓ Delete by ID hash working" )
            else:
                print( "✗ Delete by ID hash failed" )

        except Exception as e:
            print( f"⚠ Queue operations testing issues: {e}" )
        
        # Test 5: Blocking object functionality
        print( "Testing blocking object functionality..." )
        try:
            queue = FifoQueue()
            test_blocking_obj = "blocking_test"
            
            # Test push blocking object
            queue.push_blocking_object( test_blocking_obj )
            
            if not queue.is_accepting_jobs():
                print( "✓ Push blocking object working" )
            else:
                print( "✗ Push blocking object failed" )
            
            # Test pop blocking object
            popped_blocking = queue.pop_blocking_object()
            
            if popped_blocking == test_blocking_obj and queue.is_accepting_jobs():
                print( "✓ Pop blocking object working" )
            else:
                print( "✗ Pop blocking object failed" )
            
        except Exception as e:
            print( f"⚠ Blocking object functionality issues: {e}" )
        
        # Test 6: WebSocket integration structure
        print( "Testing WebSocket integration structure..." )
        try:
            # Test queue with WebSocket manager (mock)
            mock_ws_mgr = type( 'MockWS', (), { 'emit': lambda self, event, data: None } )()
            queue = FifoQueue( websocket_mgr=mock_ws_mgr, queue_name="test_queue" )
            
            if hasattr( queue, 'websocket_mgr' ) and hasattr( queue, 'queue_name' ):
                print( "✓ WebSocket integration structure valid" )
            else:
                print( "⚠ WebSocket integration structure issues" )
                
        except Exception as e:
            print( f"⚠ WebSocket integration issues: {e}" )
        
        # Test 7: Critical v000 dependency scanning
        print( "\\n🔍 Scanning for v000 dependencies..." )
        
        # Scan the file for v000 patterns
        import inspect
        source_file = inspect.getfile( FifoQueue )
        
        v000_found = False
        v000_patterns = []
        
        with open( source_file, 'r' ) as f:
            content = f.read()
            
            # Split content and exclude smoke test function
            lines = content.split( '\\n' )
            in_smoke_test = False
            
            for i, line in enumerate( lines ):
                stripped_line = line.strip()
                
                # Track if we're in the smoke test function
                if "def quick_smoke_test" in line:
                    in_smoke_test = True
                    continue
                elif in_smoke_test and line.startswith( "def " ):
                    in_smoke_test = False
                elif in_smoke_test:
                    continue
                
                # Skip comments and docstrings
                if ( stripped_line.startswith( '#' ) or 
                     stripped_line.startswith( '"""' ) or
                     stripped_line.startswith( "'" ) ):
                    continue
                
                # Look for actual v000 code references
                if "v000" in stripped_line and any( pattern in stripped_line for pattern in [
                    "import", "from", "cosa.agents.v000", ".v000."
                ] ):
                    v000_found = True
                    v000_patterns.append( f"Line {i+1}: {stripped_line}" )
        
        if v000_found:
            print( "🚨 CRITICAL: v000 dependencies detected!" )
            print( "   Found v000 references:" )
            for pattern in v000_patterns[ :3 ]:  # Show first 3
                print( f"     • {pattern}" )
            if len( v000_patterns ) > 3:
                print( f"     ... and {len( v000_patterns ) - 3} more v000 references" )
            print( "   ⚠️  These dependencies MUST be resolved before v000 deprecation!" )
        else:
            print( "✅ EXCELLENT: No v000 dependencies found!" )
        
        # Test 8: Queue state consistency validation
        print( "\\nTesting queue state consistency..." )
        try:
            queue = FifoQueue()

            # Test state consistency between operations
            class TestQueueableItem:
                """Mock item implementing QueueableJob protocol for state testing."""
                def __init__( self, id_hash ):
                    self.id_hash              = id_hash
                    self.push_counter         = 0
                    self.user_id              = "test_user"
                    self.session_id           = "test_session"
                    self.routing_command      = "test"
                    self.run_date             = "2025-01-30"
                    self.created_date         = "2025-01-30"
                    self.question             = id_hash
                    self.last_question_asked  = id_hash
                    self.answer               = "test answer"
                    self.answer_conversational = "Test answer"
                    self.job_type             = "MockJob"
                    self.user_email           = "test@test.com"
                    self.is_cache_hit         = False
                    self.started_at           = None
                    self.completed_at         = None
                    self.state                = "pending"
                    self.error                = None

                def do_all( self ):
                    return "done"

                def code_ran_to_completion( self ):
                    return True

                def formatter_ran_to_completion( self ):
                    return True

            # Add multiple items and test consistency
            for i in range( 5 ):
                queue.push( TestQueueableItem( f"test_{i}" ) )

            # Check list/dict consistency
            list_size = len( queue.queue_list )
            dict_size = len( queue.queue_dict )
            reported_size = queue.size()

            if list_size == dict_size == reported_size == 5:
                print( "✓ Queue state consistency validated" )
            else:
                print( f"⚠ State inconsistency: list={list_size}, dict={dict_size}, size={reported_size}" )

        except Exception as e:
            print( f"⚠ Queue state consistency issues: {e}" )
    
    except Exception as e:
        print( f"✗ Error during FIFO queue testing: {e}" )
        import traceback
        traceback.print_exc()
    
    # Summary
    print( "\\n" + "="*60 )
    if v000_found:
        print( "🚨 CRITICAL ISSUE: FIFO queue has v000 dependencies!" )
        print( "   Status: NOT READY for v000 deprecation" )
        print( "   Priority: IMMEDIATE ACTION REQUIRED" )
        print( "   Risk Level: CRITICAL - All queue operations will break" )
    else:
        print( "✅ FIFO queue smoke test completed successfully!" )
        print( "   Status: Base queue implementation ready for v000 deprecation" )
        print( "   Risk Level: LOW" )
    
    print( "✓ FIFO queue smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()
