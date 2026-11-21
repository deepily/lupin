"""
The two Opus twins: each forecast of the learner run again on Opus.

Rick checked the scope and cap on 19 Nov: both Haiku arms get an Opus twin. A twin makes one call per
ask, with no retry and at most one call in flight, under its own switch. It is never displayed.

A twin is the same code path as the principles forecast, ``principles_forecast.run_arm``, with a different arm name,
switch, version suffix and principle block. The baseline job's prompts and parser are used unchanged, and only the
model id differs. So a difference between a twin and its Haiku arm is a difference of model and nothing else.

Both twins wait on the baseline job, which has not landed. Without it they read the blocked reason and write nothing.
Each result goes to ``prediction_arm_forecast`` under its own arm name, never to ``prediction_log``.
"""

from cosa.agents.prediction_engine.principles_forecast import CapGate, DEFAULT_K, VERSION_SUFFIX, read_cap, run_arm, switch_enabled
from cosa.config.configuration_manager import ConfigurationManager

ARM_BASELINE_OPUS     = "C0-opus"
ARM_PRINCIPLES_OPUS   = "B1-opus"
MODEL_KEY             = "prediction learner opus twin model"
BASELINE_SWITCH_KEY   = "prediction learner opus twin baseline enabled"
BASELINE_CAP_KEY      = "prediction learner opus twin baseline max concurrent"
PRINCIPLES_SWITCH_KEY = "prediction learner opus twin principles forecast enabled"
PRINCIPLES_CAP_KEY    = "prediction learner opus twin principles forecast max concurrent"
OPUS_SUFFIX           = "+opus"


class OpusBaseline:
    """The baseline job's contract with its model id replaced by Opus's. Nothing else changes."""

    def __init__( self, c0, model ):
        """
        Wrap a baseline so it calls Opus.

        Requires:
            - c0 meets the baseline contract in principles_forecast's module docstring
            - model is a non-empty model id string

        Ensures:
            - model is the id given; every other contract member is the baseline's own, so its prompts, parser, timeout,
              error classes and version are unchanged

        Raises:
            - ValueError if model is not a non-empty string
        """
        if not ( isinstance( model, str ) and model.strip() ): raise ValueError( f"model must be a non-empty string, got {model!r}" )
        self.model             = model
        self.timeout_seconds   = c0.timeout_seconds
        self.errors            = c0.errors
        self.predictor_version = c0.predictor_version
        self.build_prompts     = c0.build_prompts
        self.parse             = c0.parse
        self.complete          = c0.complete


def opus_model():
    """
    Read the Opus model id the twins call.

    Requires:
        - the INI file carries the key named by MODEL_KEY

    Ensures:
        - returns the id as a non-empty string

    Raises:
        - MissingConfigKeyError if the key is missing or blank, so a twin never falls back to another model
    """
    return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get_required( MODEL_KEY, return_type="str" )


def baseline_gate():
    """
    Make the cap gate of the baseline twin from its INI setting.

    Ensures:
        - returns a CapGate that lets in as many calls as the key says, one by default

    Raises:
        - the errors read_cap raises for a missing or non-positive setting
    """
    return CapGate( read_cap( BASELINE_CAP_KEY ) )


def principles_gate():
    """
    Make the cap gate of the principles twin from its INI setting.

    Ensures:
        - returns a CapGate that lets in as many calls as the key says, one by default

    Raises:
        - the errors read_cap raises for a missing or non-positive setting
    """
    return CapGate( read_cap( PRINCIPLES_CAP_KEY ) )


async def _run_twin( arm, switch_key, version_suffix, use_principles, session_factory, notification_id, c0, embedder, encoder_version, extractor_version,
                     gate, enabled, model, k, clock, limits=None ):
    """
    Run one twin through the shared arm path with the baseline's model swapped for Opus's.

    Requires:
        - the arguments of run_arm; model is None to read the INI id, or an id string

    Ensures:
        - the Opus id is read only when the switch is on and a baseline exists, so an off twin never touches that key
        - returns run_arm's result
    """
    on   = switch_enabled( switch_key ) if enabled is None else enabled
    twin = None if ( c0 is None or not on ) else OpusBaseline( c0, model if model is not None else opus_model() )
    return await run_arm( arm, switch_key, version_suffix, use_principles, session_factory, notification_id, twin, embedder, encoder_version,
                          extractor_version, gate, enabled=on, k=k, clock=clock, limits=limits )


async def run_baseline_opus( session_factory, notification_id, c0, gate, enabled=None, model=None, clock=None ):
    """
    Make the baseline forecast again on Opus for one ask, and store its row.

    Requires:
        - session_factory returns a context-managed session; notification_id names an ask
        - c0 is the baseline contract, or None while the baseline job has not landed
        - gate is a CapGate; enabled is None (read the INI switch) or a bool; model is None (read the INI id) or an id string

    Ensures:
        - returns { status, reason } as run_arm does
        - with the switch off, or with c0 None, nothing is read, called or written
        - otherwise the baseline's own prompts, with no principle block, go to Opus once with no retry
        - the row is for the baseline twin's arm, displayed false, with the baseline's version plus the Opus suffix
        - a card past the cap gets a row with the capacity reason and no call
    """
    return await _run_twin( ARM_BASELINE_OPUS, BASELINE_SWITCH_KEY, OPUS_SUFFIX, False, session_factory, notification_id, c0, None, None, None,
                            gate, enabled, model, DEFAULT_K, clock )


async def run_principles_opus( session_factory, notification_id, c0, embedder, encoder_version, extractor_version, gate, enabled=None, model=None,
                               k=DEFAULT_K, clock=None, limits=None ):
    """
    Make the principles forecast again on Opus for one ask, and store its row.

    Requires:
        - the arguments of principles_forecast.run_b1; gate is the twin's own CapGate; model is None (read the INI id) or an id string

    Ensures:
        - returns { status, reason } as run_arm does
        - with the switch off, or with c0 None, nothing is read, called or written
        - otherwise the baseline's prompts plus the same principle block the Haiku arm gets go to Opus once with no retry
        - the row is for the principles twin's arm, displayed false, with the baseline's version plus both suffixes
        - a card past the cap gets a row with the capacity reason and no call
    """
    return await _run_twin( ARM_PRINCIPLES_OPUS, PRINCIPLES_SWITCH_KEY, VERSION_SUFFIX + OPUS_SUFFIX, True, session_factory, notification_id, c0,
                            embedder, encoder_version, extractor_version, gate, enabled, model, k, clock, limits )
