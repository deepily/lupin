#!/usr/bin/env python3
"""
Errors raised by the decision proxy's configuration.

Kept in a module of its own so a caller can name the error without importing the
configuration factory that raises it.
"""


class InvalidTrustModelError( ValueError ):
    """
    Raised when the trust model key names a model the tracker does not have.

    Requires:
        - the message names the offending value and the accepted values

    Ensures:
        - is a ValueError, so existing handlers of ValueError still see it
        - lets the orchestrator refuse this one bad key without refusing every ValueError
    """
