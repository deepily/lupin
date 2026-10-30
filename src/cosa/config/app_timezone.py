"""
The one reader of the `app timezone` key.

The zone comes from configuration and from nowhere else. Nothing here offers a default.
No caller may supply one. A key that is missing, blank or not an IANA zone name stops the caller.
"""
import zoneinfo

APP_TIMEZONE_KEY             = "app timezone"
ARBITER_JOURNAL_TIMEZONE_KEY = "arbiter journal local timezone"


class InvalidAppTimezoneError( ValueError ):
    """Raised when a zone key holds a value that is not an IANA zone name."""


def get_zone_for_key( config_mgr, key ) -> str:
    """
    Read a configured IANA zone name from the given key.

    Requires:
        - config_mgr is a ConfigurationManager
        - key names a zone in the resolved config block

    Ensures:
        - Returns the IANA zone name configured under key
        - Never returns a code default

    Raises:
        - MissingConfigKeyError if the key is absent or blank in the resolved block
        - InvalidAppTimezoneError if the value is not a zone name zoneinfo knows
    """
    name = config_mgr.get_required( key ).strip()
    try:
        zoneinfo.ZoneInfo( name )
    except ( zoneinfo.ZoneInfoNotFoundError, ValueError ) as e:
        raise InvalidAppTimezoneError(
            f"Key [{key}] in block [{config_mgr.config_block_id}] is [{name}], not an IANA zone name: {e}"
        ) from e
    return name


def get_app_timezone( config_mgr ) -> str:
    """
    Read the configured user time zone name.

    Requires:
        - config_mgr is a ConfigurationManager

    Ensures:
        - Returns the IANA zone name configured under `app timezone`

    Raises:
        - MissingConfigKeyError if the key is absent or blank in the resolved block
        - InvalidAppTimezoneError if the value is not a zone name zoneinfo knows
    """
    return get_zone_for_key( config_mgr, APP_TIMEZONE_KEY )


def get_arbiter_journal_timezone( config_mgr ) -> str:
    """
    Read the configured zone the arbiter journal and outreach timestamps use.

    Requires:
        - config_mgr is a ConfigurationManager

    Ensures:
        - Returns the IANA zone name configured under `arbiter journal local timezone`

    Raises:
        - MissingConfigKeyError if the key is absent or blank in the resolved block
        - InvalidAppTimezoneError if the value is not a zone name zoneinfo knows
    """
    return get_zone_for_key( config_mgr, ARBITER_JOURNAL_TIMEZONE_KEY )


def read_arbiter_journal_timezone() -> str:
    """
    Read the arbiter journal zone from the process configuration.

    For callers that hold no config manager, such as a module-level log function.

    Requires:
        - LUPIN_CONFIG_MGR_CLI_ARGS names a loadable configuration

    Ensures:
        - Returns the IANA zone name configured under `arbiter journal local timezone`

    Raises:
        - ValueError if no configuration is loaded
        - MissingConfigKeyError if the key is absent or blank
        - InvalidAppTimezoneError if the value is not a zone name zoneinfo knows
    """
    from cosa.config.configuration_manager import ConfigurationManager
    return get_arbiter_journal_timezone( ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ) )
