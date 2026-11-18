#!/usr/bin/env python3
"""
Shared loader and vector builder for the preference replay leak tests.

Three test files read the same committed synthetic fixture. This module holds
the two helpers they all need, so none of them keeps its own copy.
"""

import json
from pathlib import Path

from cosa.rest.db.vector_store_models import EMBEDDING_DIM

FIXTURE_PATH = Path( __file__ ).parent.parent / "unit" / "fixtures" / "preference_replay_leaks" / "leak_fixtures.json"


def load_fixture():
    """
    Load the committed synthetic leak fixture.

    Requires:
        - FIXTURE_PATH exists

    Ensures:
        - returns the parsed fixture dict
    """
    return json.loads( FIXTURE_PATH.read_text() )


def basis_vector( axis, norm ):
    """
    Build a vector that is one basis axis times a norm.

    Requires:
        - 0 <= axis < EMBEDDING_DIM and norm > 0

    Ensures:
        - returns a list of EMBEDDING_DIM floats
    """
    vector = [ 0.0 ] * EMBEDDING_DIM
    vector[ axis ] = norm
    return vector
