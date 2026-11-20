#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The half-life weight of an old observation.

The trust tracker and the three-way stance predictor share it.
"""

import math

# The natural log of 2 as the trust tracker has always written it. Keeping the rounded figure keeps its
# weights, and every threshold built on them, exactly as they were; the error against the true value
# is about 0.02% per half-life.
TRUST_TRACKER_LN2 = 0.693


def recency_weight( age_seconds, half_life_days ):
    """
    Weight an observation by how long ago it happened.

    Requires:
        - age_seconds is a number of seconds, zero or more
        - half_life_days is a positive number of days

    Ensures:
        - returns exp( -0.693 * age / half_life ), which is 1.0 at age zero and about 0.5 at one half-life
        - the result falls toward zero as the age grows and never rises above 1.0

    Raises:
        - ValueError if half_life_days is not positive
    """
    if half_life_days <= 0: raise ValueError( f"half_life_days must be positive, got {half_life_days!r}" )
    return math.exp( -TRUST_TRACKER_LN2 * age_seconds / ( half_life_days * 86400 ) )
