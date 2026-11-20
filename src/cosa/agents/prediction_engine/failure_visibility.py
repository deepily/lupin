#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Silent prediction failures become named abstention reasons.

A missing embedding, a failed forecast write and a swallowed store error each leave a named
reason on the forecast row. Each also writes one log line starting with FAILURE_LOG_PREFIX.
Everything here is pure naming and logging. The engine decides when to call it, behind the
INI key "prediction engine failure visibility enabled", which is off by default.
"""

from typing import Optional

FAILURE_LOG_PREFIX        = "[PREDICTION-FAILURE]"

REASON_EMBEDDING_MISSING  = "embedding_missing"
REASON_STORE_WRITE_FAILED = "store_write_failed"
REASON_STORE_ERROR_PREFIX = "store_error: "

# The reason the predictor already wrote for a missing embedding, and the name this phase gives it.
LEGACY_NO_EMBEDDING       = "no_embedding"
LEGACY_NO_SIMILAR_CASES   = "no_similar_cases"


def name_failure( reason: Optional[str], store_error_class: Optional[str] = None ) -> Optional[str]:
    """
    Give a predictor's abstention reason its failure name.

    Requires:
        - reason is the predictor's reason string, or None
        - store_error_class is the class name of a swallowed embedding-store exception, or None

    Ensures:
        - "no_embedding" becomes "embedding_missing"
        - "no_similar_cases" with a store_error_class becomes "store_error: <class>"
        - any other reason, and None, comes back unchanged
    """
    if reason == LEGACY_NO_EMBEDDING: return REASON_EMBEDDING_MISSING
    if reason == LEGACY_NO_SIMILAR_CASES and store_error_class is not None:
        return f"{REASON_STORE_ERROR_PREFIX}{store_error_class}"
    return reason


def is_failure_reason( reason: Optional[str] ) -> bool:
    """
    Say whether a stored abstention reason is one of the three failure kinds.

    Requires:
        - reason is a string or None

    Ensures:
        - True for embedding_missing, store_write_failed and any "store_error: <class>"
        - False for everything else, None included
    """
    if reason is None: return False
    return reason in ( REASON_EMBEDDING_MISSING, REASON_STORE_WRITE_FAILED ) or reason.startswith( REASON_STORE_ERROR_PREFIX )


def log_failure( notification_id: Optional[str], reason: str, detail: Optional[str] = None ) -> str:
    """
    Print one failure line and return it.

    Requires:
        - reason is a failure reason from this module
        - notification_id may be None when the failure has no notification (a failed answer-case write)

    Ensures:
        - prints exactly one line beginning with FAILURE_LOG_PREFIX
        - returns the line printed
    """
    line = f"{FAILURE_LOG_PREFIX} notification={notification_id} reason={reason}"
    if detail: line += f" detail={detail}"
    print( line )
    return line
