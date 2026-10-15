"""
The labelled set of the verdict layer (candidate-stage plan, Phase 3).

The uncertain band is set from measured repeat jitter and may not be narrower than MIN_BAND.
decide() takes any band it is given, since it is a pure function of its policy. The step that
records a fitted policy refuses a band under the floor through check_band.
"""

MIN_BAND = 0.05      # the plan's exit gate: the band is at least 0.05


def check_band( band ):
    """
    Return the band when it may be recorded.

    Requires:
        - band is a real number

    Ensures:
        - returns band unchanged when it is at least MIN_BAND

    Raises:
        - ValueError naming the floor when band is under MIN_BAND
    """
    if band < MIN_BAND: raise ValueError( f"band {band} is under the floor {MIN_BAND}; the plan sets it from measured repeat jitter and at least {MIN_BAND}" )
    return band
