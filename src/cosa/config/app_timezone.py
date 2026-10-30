"""
The one reader of the `app timezone` key.

The zone comes from configuration and from nowhere else. Nothing here offers a default.
No caller may supply one. A key that is missing, blank or not an IANA zone name stops the caller.
"""
import zoneinfo

APP_TIMEZONE_KEY = "app timezone"


class InvalidAppTimezoneError( ValueError ):
    """Raised when `app timezone` holds a value that is not an IANA zone name."""


def get_app_timezone( config_mgr ) -> str:
    """
    Read the configured user time zone name.

    Requires:
        - config_mgr is a ConfigurationManager

    Ensures:
        - Returns the IANA zone name configured under `app timezone`
        - Never returns a code default

    Raises:
        - MissingConfigKeyError if the key is absent or blank in the resolved block
        - InvalidAppTimezoneError if the value is not a zone name zoneinfo knows
    """
    name = config_mgr.get_required( APP_TIMEZONE_KEY ).strip()
    try:
        zoneinfo.ZoneInfo( name )
    except ( zoneinfo.ZoneInfoNotFoundError, ValueError ) as e:
        raise InvalidAppTimezoneError(
            f"Key [{APP_TIMEZONE_KEY}] in block [{config_mgr.config_block_id}] is [{name}], not an IANA zone name: {e}"
        ) from e
    return name
