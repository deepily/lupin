#!/usr/bin/env python3
"""
dot_topk refuses an unknown metric before it touches the session.

The session is a MagicMock whose only job is to prove it was never queried.
Without the early refusal, a typo in a metric name would order results by the wrong distance.
"""

from unittest.mock import MagicMock

import pytest

from cosa.rest.db.repositories.vector_search import dot_topk


@pytest.mark.parametrize( "metric", [ "euclidean", "", "COSINE", None ] )
def test_unknown_metric_raises_value_error_naming_the_metric_and_never_queries( metric ):
    session = MagicMock()

    with pytest.raises( ValueError, match="metric must be 'dot' or 'cosine'" ) as excinfo:
        dot_topk( session, MagicMock(), MagicMock(), [ 0.1, 0.2 ], limit=3, metric=metric )

    assert repr( metric ) in str( excinfo.value )     # the message echoes the offending value
    session.query.assert_not_called()                 # refused before any query was built
