"""
Compact UTC timestamp for file and folder names.

The result sorts as text and holds no character a filesystem refuses, for example
`20261111T225539Z`. Run folders, backup folders and WIP-commit labels all use this shape.
"""

from datetime import datetime, timezone

UTC_COMPACT_FORMAT = "%Y%m%dT%H%M%SZ"


def utc_compact_stamp( now=None ) -> str:
    """
    Return `now`, or the present UTC moment, as `YYYYMMDDTHHMMSSZ`.

    Requires:
        - now is None or a datetime

    Ensures:
        - returns a 16-character string ending in Z
        - formats `now` as given, with no zone conversion, so a caller passes a UTC datetime
        - reads the clock only when `now` is None
    """
    moment = now if now is not None else datetime.now( timezone.utc )
    return moment.strftime( UTC_COMPACT_FORMAT )
