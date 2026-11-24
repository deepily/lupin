"""
The forecaster arms, listed once.

``context_arms.ARMS`` names five ways of building the text an ask is embedded under, not forecasters.
This registry names the forecasters and the way each reaches the reply parser.
A guard can then check that every one reads its reply through ``context_baseline.parse_reply``.
A forecaster added to the fleet is added here.
"""

from cosa.agents.prediction_engine import context_baseline, opus_twins, principles_forecast


def own_parse( baseline ):
    """
    Give the parse function a Haiku arm calls.

    Requires:
        - baseline meets principles_forecast's baseline contract

    Ensures:
        - returns baseline.parse, which run_arm calls for the context and principles arms alike
    """
    return baseline.parse


def opus_parse( baseline ):
    """
    Give the parse function an Opus twin calls.

    Requires:
        - baseline meets principles_forecast's baseline contract

    Ensures:
        - returns the parse of the OpusBaseline wrapped around it, which is what run_arm calls for a twin
    """
    return opus_twins.OpusBaseline( baseline, "model-for-a-test" ).parse


FORECASTER_ARMS = {
    context_baseline.ARM           : own_parse,
    principles_forecast.ARM        : own_parse,
    opus_twins.ARM_BASELINE_OPUS   : opus_parse,
    opus_twins.ARM_PRINCIPLES_OPUS : opus_parse,
}
