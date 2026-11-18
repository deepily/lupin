"""Confidence calibration for the prediction engine: fit, store, load and apply."""

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression

import cosa.utils.util as cu
from cosa.utils.atomic_json import write_json_atomic

MIN_ROWS_PER_CELL = 50
CALIBRATION_PATH  = "/src/conf/prediction-calibration.json"
FORMAT_VERSION    = 1
STATUS_FIT        = "fit"
STATUS_REFUSED    = "insufficient data"


def cell_key( response_type: str, strategy: str ) -> str:
    """
    Name the calibration cell for a response type and strategy.

    Requires:
        - response_type and strategy are non-empty strings without a pipe character

    Ensures:
        - returns ``"<response_type>|<strategy>"``, the key used in the stored map
    """
    return f"{response_type}|{strategy}"


def fit_cell( confidences: Sequence[float], correct: Sequence[bool] ) -> Dict:
    """
    Fit one isotonic map from confidence to the probability of being correct.

    Requires:
        - confidences and correct are the same length
        - confidences are numbers in [0, 1]; correct are booleans for scored rows

    Ensures:
        - fewer than MIN_ROWS_PER_CELL rows returns ``{ "status": "insufficient data", "n", "needed" }``
          and fits nothing
        - otherwise returns ``{ "status": "fit", "n", "x", "y" }`` where x and y are the
          fitted step points, x ascending and y non-decreasing

    Raises:
        - ValueError if the two sequences differ in length
    """
    if len( confidences ) != len( correct ):
        raise ValueError( f"confidences and correct differ in length: {len( confidences )} vs {len( correct )}" )
    n = len( confidences )
    if n < MIN_ROWS_PER_CELL:
        return { "status": STATUS_REFUSED, "n": n, "needed": MIN_ROWS_PER_CELL }
    model = IsotonicRegression( out_of_bounds="clip" )
    model.fit( np.asarray( confidences, dtype=float ), np.asarray( correct, dtype=float ) )
    return {
        "status" : STATUS_FIT,
        "n"      : n,
        "x"      : [ float( v ) for v in model.X_thresholds_ ],
        "y"      : [ float( v ) for v in model.y_thresholds_ ],
    }


def fit_calibration( rows: Iterable[Tuple[str, str, float, bool]], cohort_sha: str, fit_time: str ) -> Dict:
    """
    Fit one map per ( response type, strategy ) cell from scored rows.

    Requires:
        - rows yields ``( response_type, strategy, confidence, correct )`` for scored rows only
        - cohort_sha names the cohort the rows came from; fit_time is an ISO-8601 string

    Ensures:
        - returns the document stored in the calibration file: version, cohort_sha, fit_time, cells
        - every cell seen has an entry, a fit or an "insufficient data" refusal
    """
    grouped: Dict[str, Tuple[List[float], List[bool]]] = {}
    for response_type, strategy, confidence, was_correct in rows:
        xs, ys = grouped.setdefault( cell_key( response_type, strategy ), ( [], [] ) )
        xs.append( confidence )
        ys.append( was_correct )
    return {
        "version"    : FORMAT_VERSION,
        "cohort_sha" : cohort_sha,
        "fit_time"   : fit_time,
        "cells"      : { key: fit_cell( xs, ys ) for key, ( xs, ys ) in sorted( grouped.items() ) },
    }


def calibrate( cell: Optional[Dict], confidence: float ) -> Optional[float]:
    """
    Map a raw confidence to a calibrated probability of being correct.

    Requires:
        - cell is a fitted cell from fit_cell, a refused cell, or None
        - confidence is a number

    Ensures:
        - returns None when the cell is missing or refused, so the caller decides what to show
        - otherwise returns the step function's value, clipped to the fitted range at both ends
          and always in [0, 1]
    """
    if cell is None or cell[ "status" ] != STATUS_FIT:
        return None
    return float( np.interp( confidence, cell[ "x" ], cell[ "y" ] ) )


def reliability_report( confidences: Sequence[float], correct: Sequence[bool], n_bins: int = 5 ) -> List[Dict]:
    """
    Bin rows by confidence and report each bin's observed correctness rate.

    Requires:
        - confidences and correct are the same length and not empty
        - n_bins is a positive int

    Ensures:
        - returns one ``{ "mean_confidence", "observed_rate" }`` per non-empty bin, low to high,
          from scikit-learn's calibration_curve on equal-width bins over [0, 1]
    """
    observed, predicted = calibration_curve( np.asarray( correct, dtype=int ), np.asarray( confidences, dtype=float ),
                                              n_bins=n_bins, strategy="uniform" )
    return [ { "mean_confidence": float( m ), "observed_rate": float( o ) } for o, m in zip( observed, predicted ) ]


def empty_document() -> Dict:
    """
    Return the calibration document with no fitted cells.

    Ensures:
        - returns the shape committed in the calibration file before the first fit
    """
    return { "version": FORMAT_VERSION, "cohort_sha": None, "fit_time": None, "cells": {} }


def write_calibration( document: Dict, path: Optional[str] = None ) -> str:
    """
    Write a calibration document as JSON.

    Requires:
        - document came from fit_calibration or empty_document

    Ensures:
        - writes sorted, indented JSON ending in a newline to path, or the committed location,
          replacing the file whole
        - returns the path written
    """
    path = path if path is not None else cu.get_project_root() + CALIBRATION_PATH
    write_json_atomic( path, document, indent=2, trailing_newline=True, sort_keys=True )
    return path


def load_calibration( path: Optional[str] = None ) -> Dict:
    """
    Read a calibration document.

    Requires:
        - the file exists and holds a document written by write_calibration

    Ensures:
        - returns the document

    Raises:
        - FileNotFoundError if the file is missing
        - ValueError if the stored version is not FORMAT_VERSION
    """
    path = path if path is not None else cu.get_project_root() + CALIBRATION_PATH
    document = cu.get_file_as_json( path )
    if document.get( "version" ) != FORMAT_VERSION:
        raise ValueError( f"{path} has version {document.get( 'version' )!r}, expected {FORMAT_VERSION}" )
    return document
