"""
The learner's second call per ask: the principles forecast, made by the learner.

The baseline job already forecasts the card. This call is the same job with one block of principles added.
It takes the baseline from ``context_baseline.get_baseline``, so the model, the timeout, the prompts and the parser are the baseline's own.
Its result goes to the sibling table under its own arm name, never to ``prediction_log``.

It has its own switch and its own cap gate, both read by ``principles_forecast``.
So it cannot take a slot from the baseline, and a card past its cap gets a row with the capped reason.
The gate is made once per process, so two asks share one cap.
The call never selects, prefills or submits anything on the card.
The notify route starts it beside the baseline job, through ``run_quietly``.
"""

import threading
from types import SimpleNamespace

from cosa.agents.prediction_engine.context_baseline import get_baseline
from cosa.agents.prediction_engine.principles_forecast import (
    REASON_SWITCH, STATUS_NOT_RUN, CapGate, concurrency_cap, principles_forecast_enabled, run_b1 )
from cosa.agents.principle_learner import extractor_job
from cosa.agents.principle_learner.extractor_prompt import extractor_version_of
from cosa.config.configuration_manager import ConfigurationManager

_GATE = None
_LOCK = threading.Lock()


def get_gate():
    """
    Return this process's cap gate for the principles forecast.

    The gate is made on first use from the INI cap.

    Ensures:
        - one gate per process, so every ask counts against the same cap

    Raises:
        - MissingConfigKeyError if the cap key is missing or blank
        - ValueError if the cap is not a positive integer
    """
    global _GATE
    with _LOCK:
        if _GATE is None: _GATE = CapGate( concurrency_cap() )
        return _GATE


def reset_gate():
    """Forget this process's gate, so the next call reads the cap again."""
    global _GATE
    with _LOCK: _GATE = None


def provider_embedder():
    """
    Make the object run_b1 embeds a card's text with.

    Ensures:
        - returns an object whose encode( text ) is the extractor's own embedding call, so card and principle vectors share one encoder
    """
    return SimpleNamespace( encode=lambda text: extractor_job.default_embed( text ) )


def retrieval_versions():
    """
    Name the encoder and extractor versions the principles are read under.

    Ensures:
        - returns ( encoder version, extractor version ): the extractor's own stored encoder string, and the settings' extractor model with the prompt version

    Raises:
        - MissingConfigKeyError if a needed INI key is absent
    """
    config = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    return extractor_job.encoder_version(), extractor_version_of( config.get_required( extractor_job.MODEL_KEY ) )


async def run_quietly( notification_id, run=None ):
    """
    Run the principles forecast for one ask, and never let a failure reach the ask.

    Requires:
        - notification_id names a committed ask
        - run is None (run_principles_forecast) or a stand-in with its signature, for tests

    Ensures:
        - returns the call's { status, reason }
        - a failure of the call is printed and not raised, and the return is then None
    """
    try:
        return await ( run_principles_forecast if run is None else run )( notification_id )
    except Exception as call_error:
        print( f"[PRINCIPLES] ⚠️ Call for {notification_id} raised (non-fatal): {call_error}" )
        return None


async def run_principles_forecast( notification_id, session_factory=None, c0=None, gate=None, enabled=None, embedder=None, clock=None ):
    """
    Make the principles forecast for one ask and store its row under the principles arm.

    Requires:
        - notification_id names an ask whose notification row is committed
        - session_factory is None (the app's database sessions) or returns a context-managed session
        - c0, gate and embedder are None (this process's own) or stand-ins, for tests
        - enabled is None (read the INI switch) or a bool

    Ensures:
        - with the switch off nothing is read, called or written, and neither the baseline nor the embedder is built
        - otherwise it is principles_forecast.run_b1 over the baseline from get_baseline, so the prompt is the baseline's plus the principle block
        - the principles are those of the encoder and extractor version the settings name now
        - returns { status, reason } as run_b1 does

    Raises:
        - the errors get_baseline, get_gate and the settings reads raise when the switch is on and a setting is missing
    """
    if not ( principles_forecast_enabled() if enabled is None else enabled ): return { "status": STATUS_NOT_RUN, "reason": REASON_SWITCH }
    c0                 = get_baseline()[ 0 ] if c0 is None else c0
    gate               = get_gate() if gate is None else gate
    embedder           = provider_embedder() if embedder is None else embedder
    encoder, extractor = retrieval_versions()
    if session_factory is None:
        from cosa.rest.db.database import get_db
        session_factory = get_db
    return await run_b1( session_factory, notification_id, c0, embedder, encoder, extractor, gate, enabled=True, clock=clock )
