"""
Queue Extensions for User-Specific Functionality

This module provides extensions to the COSA queue system to support
user-specific job tracking and filtering.
"""

from typing import Dict, List, Optional
from threading import Lock


class UserJobTracker:
    """
    User-scoped job indexing utility for O(1) queue filtering.

    Maintains a reverse index (user_id -> [job_ids]) so that
    FifoQueue.get_jobs_for_user() can filter in O(1) instead of scanning.

    job.user_id is the single source of truth for ownership.
    This class only provides an efficient lookup index.

    Thread-safe singleton, consistent with other COSA singletons
    like GistNormalizer and EmbeddingManager.
    """

    _instance = None
    _lock = Lock()

    def __new__( cls ):
        """
        Create or return singleton instance.

        Requires:
            - Nothing

        Ensures:
            - Returns the single instance of UserJobTracker
            - Thread-safe initialization
            - Instance created only once

        Raises:
            - None
        """
        if cls._instance is None:
            with cls._lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = super().__new__( cls )
                    # Initialize instance attributes
                    cls._instance._initialized = False
        return cls._instance

    def __init__( self ):
        """
        Initialize the tracker if not already initialized.

        Requires:
            - Instance created via __new__

        Ensures:
            - Attributes initialized only once
            - Thread-safe initialization

        Raises:
            - None
        """
        # Prevent re-initialization of singleton
        if self._initialized:
            return

        with self._lock:
            if not self._initialized:
                # Map job_id to user_id (forward index for remove_job cleanup)
                self.job_to_user: Dict[str, str] = {}
                # Map user_id to list of job_ids (reverse index for queue filtering)
                self.user_jobs: Dict[str, List[str]] = {}
                self._initialized = True
                print( "[UserJobTracker] Singleton instance initialized" )

    def register_scoped_job( self, base_hash: str, user_id: str, session_id: str = None ) -> str:
        """
        Atomic operation to generate a user-scoped hash and register the job.

        This is the single write entry point. All code paths that create jobs
        should call this method to scope the ID and index it for filtering.

        Requires:
            - base_hash is a valid job identifier or hash
            - user_id is a valid user identifier

        Ensures:
            - Returns user-scoped hash in format "{base_hash}::{user_id}"
            - Job is indexed for user-based queue filtering
            - Thread-safe operation

        Raises:
            - None
        """
        scoped_id = self.generate_user_scoped_hash( base_hash, user_id )

        with self._lock:
            self.job_to_user[ scoped_id ] = user_id

            if user_id not in self.user_jobs:
                self.user_jobs[ user_id ] = []
            self.user_jobs[ user_id ].append( scoped_id )

        return scoped_id

    def associate_job_with_user( self, job_id: str, user_id: str ) -> None:
        """
        Associate a job with a user (low-level index update).

        Prefer register_scoped_job() for new code. This method exists for
        test setup and cases where the ID is already scoped.

        Requires:
            - job_id is a valid job identifier
            - user_id is a valid user identifier

        Ensures:
            - Job is mapped to user
            - User's job list is updated
            - Thread-safe operation

        Raises:
            - None
        """
        with self._lock:
            self.job_to_user[job_id] = user_id

            if user_id not in self.user_jobs:
                self.user_jobs[user_id] = []
            self.user_jobs[user_id].append( job_id )

    def get_jobs_for_user( self, user_id: str ) -> List[str]:
        """
        Get all job IDs for a user.

        Requires:
            - user_id is a string

        Ensures:
            - Returns list of job IDs for user
            - Returns empty list if user not found
            - Returns copy to prevent external modification
            - Thread-safe read operation

        Raises:
            - None
        """
        with self._lock:
            return self.user_jobs.get( user_id, [] ).copy()

    def generate_user_scoped_hash( self, base_hash: str, user_id: str ) -> str:
        """
        Generate a compound hash unique to question + user.

        Single source of truth for user-scoped job identification.

        Requires:
            - base_hash is the original question/snapshot hash
            - user_id is the authenticated user's ID

        Ensures:
            - Returns compound hash in format "{base_hash}::{user_id}"
            - Same inputs always produce same output (idempotent)
            - Different users get different hashes (no collision)
            - Strips existing scope to prevent double-scoping

        Raises:
            - None
        """
        # Strip any existing user scope to prevent double-scoping on cache replay
        clean_hash = base_hash.split( '::' )[0] if '::' in base_hash else base_hash
        return f"{clean_hash}::{user_id}"

    def remove_job( self, job_id: str ) -> None:
        """
        Remove a job from tracking.

        Requires:
            - job_id is a string

        Ensures:
            - Job removed from job_to_user mapping
            - Job removed from user's job list
            - Empty user job lists are cleaned up
            - Thread-safe operation

        Raises:
            - None
        """
        with self._lock:
            if job_id in self.job_to_user:
                user_id = self.job_to_user[job_id]
                del self.job_to_user[job_id]

                if user_id in self.user_jobs:
                    self.user_jobs[user_id].remove( job_id )
                    if not self.user_jobs[user_id]:
                        del self.user_jobs[user_id]


# Global instance for tracking user jobs
user_job_tracker = UserJobTracker()
