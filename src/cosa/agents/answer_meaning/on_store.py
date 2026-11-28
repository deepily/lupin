"""
Label an answer as it is stored, behind a switch that ships off.

The answer door calls record_after_answer once per answered ask. With the switch off nothing is read, written or printed.
With it on, the model call runs on a daemon thread, so the answer is never held up by it.
"""
import threading

from cosa.agents.answer_meaning import runner
from cosa.config.configuration_manager import ConfigurationManager
from cosa.config.switch_reader import read_switch

STORE_KEY = "prediction learner answer meaning on store enabled"


def is_enabled():
    """
    Say whether the answer door should label answers as they arrive.

    Ensures:
        - returns the switch's value, read on each call so a flip needs no restart
        - returns False, naming the error, when the switch cannot be read
    """
    return read_switch( ConfigurationManager, STORE_KEY, False, lambda error: f"[MEANING] ⚠️ cannot read '{STORE_KEY}', treated as off: {error}" )


def _record( notification_id, session_scope ):
    """
    Label one answer and print what happened.

    Ensures:
        - writes the meaning row through runner.record_one with the configured model
        - any failure is printed and swallowed, since the answer is already stored
    """
    try:
        annotator, label = runner.bound_labeller()
        report           = runner.record_one( session_scope, notification_id, annotator, label )
        print( f"[MEANING] {notification_id}: {report[ 'status' ]}" )
    except Exception as error:
        print( f"[MEANING] ⚠️ {notification_id}: labelling failed (non-fatal): {error}" )


def record_after_answer( notification_id, session_scope, start=None ):
    """
    Queue the labelling of one answered ask.

    Requires:
        - notification_id is the UUID string of an ask whose answer is already committed
        - session_scope returns a context manager yielding a session
        - start is None, or a callable taking the thread, a test stand-in for starting it

    Ensures:
        - with the switch off, returns { "queued": False, "reason": "disabled" } and does nothing else
        - with it on, starts one daemon thread and returns { "queued": True, "reason": "queued" }
    """
    if not is_enabled(): return { "queued": False, "reason": "disabled" }
    thread = threading.Thread( target=_record, args=( notification_id, session_scope ), daemon=True )
    if start is None: thread.start()
    else: start( thread )
    return { "queued": True, "reason": "queued" }
