"""
Queue the silent extractor after an owner answer, then the review-card sweep.

The answer door calls enqueue_after_answer once per answered ask.
Two INI keys steer it. One switch, read through is_enabled, turns the enqueue on.
The other decides whether the jobs show in the owner's queue listing.
The extractor never speaks. The sweep is the only job that may send a card, so it is queued only after the extractor ends.
"""

import threading
import time

from cosa.agents.principle_learner.extractor_job import PrincipleExtractorJob
from cosa.agents.principle_learner.review_card_sweep import sweep_job_after
from cosa.agents.prediction_engine.review_card import is_review_card
from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest.job_state import TERMINAL_STATES

ENABLE_KEY    = "prediction learner enqueue extractor on answer"
SHOW_KEY      = "prediction learner extractor jobs show in queue"
POLL_SECONDS  = 2
GIVE_UP_AFTER = 3600


def _flag( key ):
    """
    Read one boolean INI key.

    Requires:
        - key is present in the INI file

    Ensures:
        - returns the key's value as a bool

    Raises:
        - MissingConfigKeyError if the key is absent
    """
    return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get_required( key, return_type="boolean" )


def is_enabled():
    """
    Say whether the answer door should queue the extractor at all.

    Requires:
        - the enable key is present in the INI file

    Ensures:
        - returns the enable key's value, read on each call so a flip needs no restart

    Raises:
        - MissingConfigKeyError if the key is absent
    """
    return _flag( ENABLE_KEY )


def register_job( queue, job, show ):
    """
    Give the job its user-scoped id so the owner's queue listing can find it, or leave it out.

    Requires:
        - queue is the todo queue; job has id_hash, user_id and session_id

    Ensures:
        - with show True, job.id_hash becomes the scoped id the listings filter on
        - with show False, the id is left bare, so no listing of the owner's jobs names it
    """
    if show: job.id_hash = queue.user_job_tracker.register_scoped_job( job.id_hash, str( job.user_id ), job.session_id )


def _push_sweep_after( queue, extractor, sweep, show, poll_seconds, give_up_after, sleep ):
    """
    Wait for the extractor to end, then queue the sweep, on this thread.

    Requires:
        - extractor is already on the queue; sweep is built and not yet queued

    Ensures:
        - the sweep is queued once the extractor reaches a terminal state, whether it worked or failed
        - after give_up_after seconds with no end the sweep is queued anyway, because it reads only the database
    """
    waited = 0
    while extractor.state not in TERMINAL_STATES and waited < give_up_after:
        sleep( poll_seconds )
        waited += poll_seconds
    register_job( queue, sweep, show )
    queue.push( sweep )


def enqueue_after_answer( queue, notification_id, owner_id, owner_email, response_options, poll_seconds=POLL_SECONDS,
                          give_up_after=GIVE_UP_AFTER, sleep=time.sleep, start=None ):
    """
    Queue one extractor job for an owner's answer, and the sweep behind it.

    Requires:
        - queue is the todo queue with push and user_job_tracker
        - the answer came through the answer door, which has already checked the caller is the addressee
        - response_options is the card schema stored on the ask, or None
        - start is None or a callable taking a thread, a test stand-in for starting it

    Ensures:
        - returns { "queued": bool, "reason": str, "job_id": str or None }
        - when the ask is a review card, nothing is queued
        - otherwise exactly one extractor job is queued now and exactly one sweep job after it ends
        - neither job sends the owner a notification, progress card or voice line
        - the show key decides whether the owner's listing names the jobs

    Raises:
        - MissingConfigKeyError if a key is absent
    """
    if is_review_card( response_options ): return { "queued": False, "reason": "review_card", "job_id": None }
    show      = _flag( SHOW_KEY )
    extractor = PrincipleExtractorJob( notification_id, owner_id, owner_email )
    sweep     = sweep_job_after( extractor )
    register_job( queue, extractor, show )
    queue.push( extractor )
    thread = threading.Thread( target=_push_sweep_after, args=( queue, extractor, sweep, show, poll_seconds, give_up_after, sleep ), daemon=True )
    if start is None: thread.start()
    else: start( thread )
    return { "queued": True, "reason": "queued", "job_id": extractor.id_hash }
