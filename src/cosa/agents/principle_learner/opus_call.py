"""
The learner's Opus twin calls: each Haiku forecast of an ask run again on Opus.

A twin is the same call as its Haiku twin with the model id replaced, so it takes the process's own baseline from ``context_baseline.get_baseline``.
The baseline twin sends the baseline's prompts as they are. The principles twin adds the same principle block the principles forecast gets.
Each twin has its own switch, its own cap gate and its own arm name, and it is never displayed.
A twin makes one call per ask with no retry, and its gate holds one call in flight by default. A card past the cap gets a capped row.
The model id is part of the baseline's ledger key, so a twin is never answered from its Haiku twin's cached reply.
Each result goes to the sibling table, where the per-arm summary lists it beside the arms it is compared with.
"""

import threading

from cosa.agents.prediction_engine.context_baseline import get_baseline
from cosa.agents.prediction_engine.opus_twins import (
    ARM_BASELINE_OPUS, ARM_PRINCIPLES_OPUS, BASELINE_SWITCH_KEY, PRINCIPLES_SWITCH_KEY, baseline_gate, principles_gate, run_baseline_opus, run_principles_opus )
from cosa.agents.prediction_engine.principles_forecast import REASON_SWITCH, STATUS_NOT_RUN, switch_enabled
from cosa.agents.principle_learner.principles_call import provider_embedder, retrieval_versions

_GATES = {}
_LOCK  = threading.Lock()


def get_gate( arm ):
    """
    Return this process's cap gate for one twin, made on first use from that twin's INI cap.

    Requires:
        - arm is ARM_BASELINE_OPUS or ARM_PRINCIPLES_OPUS

    Ensures:
        - one gate per twin per process, so every ask counts against the same cap and the two twins never share a place

    Raises:
        - KeyError if arm is not a twin's arm name
        - MissingConfigKeyError if the cap key is missing or blank
        - ValueError if the cap is not a positive integer
    """
    factories = { ARM_BASELINE_OPUS: baseline_gate, ARM_PRINCIPLES_OPUS: principles_gate }
    with _LOCK:
        if arm not in _GATES: _GATES[ arm ] = factories[ arm ]()
        return _GATES[ arm ]


def reset_gates():
    """Forget this process's twin gates, so the next call reads the caps again."""
    with _LOCK: _GATES.clear()


async def run_baseline_twin( notification_id, session_factory=None, c0=None, gate=None, enabled=None, clock=None ):
    """
    Make the baseline forecast again on Opus for one ask and store its row.

    The row goes under the baseline twin's arm.

    Requires:
        - notification_id names an ask whose notification row is committed
        - session_factory is None (the app's database sessions) or returns a context-managed session
        - c0 and gate are None (this process's own) or stand-ins, for tests
        - enabled is None (read the INI switch) or a bool

    Ensures:
        - with the switch off nothing is read, called or written, and the baseline is not built
        - otherwise it is opus_twins.run_baseline_opus over the baseline from get_baseline, so one Opus call with the baseline's own prompts and no retry
        - returns { status, reason } as run_arm does

    Raises:
        - the errors get_baseline, get_gate and the settings reads raise when the switch is on and a setting is missing
    """
    if not ( switch_enabled( BASELINE_SWITCH_KEY ) if enabled is None else enabled ): return { "status": STATUS_NOT_RUN, "reason": REASON_SWITCH }
    c0   = get_baseline()[ 0 ] if c0 is None else c0
    gate = get_gate( ARM_BASELINE_OPUS ) if gate is None else gate
    if session_factory is None:
        from cosa.rest.db.database import get_db
        session_factory = get_db
    return await run_baseline_opus( session_factory, notification_id, c0, gate, enabled=True, clock=clock )


async def run_principles_twin( notification_id, session_factory=None, c0=None, gate=None, enabled=None, embedder=None, clock=None ):
    """
    Make the principles forecast again on Opus for one ask and store its row.

    The row goes under the principles twin's arm.

    Requires:
        - the arguments of run_baseline_twin; embedder is None (the extractor's own embedding call) or a stand-in with encode( text ), for tests

    Ensures:
        - with the switch off nothing is read, called or written, and neither the baseline nor the embedder is built
        - otherwise it is opus_twins.run_principles_opus, so the baseline's prompts plus the principle block the Haiku forecast gets go to Opus once
        - the principles are those of the encoder and extractor version the settings name now
        - returns { status, reason } as run_arm does

    Raises:
        - the errors get_baseline, get_gate and the settings reads raise when the switch is on and a setting is missing
    """
    if not ( switch_enabled( PRINCIPLES_SWITCH_KEY ) if enabled is None else enabled ): return { "status": STATUS_NOT_RUN, "reason": REASON_SWITCH }
    c0                 = get_baseline()[ 0 ] if c0 is None else c0
    gate               = get_gate( ARM_PRINCIPLES_OPUS ) if gate is None else gate
    embedder           = provider_embedder() if embedder is None else embedder
    encoder, extractor = retrieval_versions()
    if session_factory is None:
        from cosa.rest.db.database import get_db
        session_factory = get_db
    return await run_principles_opus( session_factory, notification_id, c0, embedder, encoder, extractor, gate, enabled=True, clock=clock )
