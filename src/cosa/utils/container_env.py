"""
The one answer to "is this process inside a Lupin container?"

Two signals exist. An operator or the compose file sets the LUPIN_IN_CONTAINER sentinel to 1, true or yes.
The container runtime also writes /.dockerenv. A caller that needs only the sentinel asks container_sentinel_set.
"""
import os

CONTAINER_SENTINEL_VARIABLE = "LUPIN_IN_CONTAINER"
CONTAINER_SENTINEL_WORDS    = ( "1", "true", "yes" )
DOCKERENV_PATH              = "/.dockerenv"


def container_sentinel_set() -> bool:
    """
    Say whether the LUPIN_IN_CONTAINER sentinel is set to a true word.

    Ensures:
        - returns True when the variable reads 1, true or yes, in any case, with surrounding blanks ignored
        - returns False when it is absent, empty or any other text; a falsy sentinel is not a container
    """
    return os.environ.get( CONTAINER_SENTINEL_VARIABLE, "" ).strip().lower() in CONTAINER_SENTINEL_WORDS


def running_in_container() -> bool:
    """
    Say whether this process runs inside a container.

    Ensures:
        - returns True when the sentinel is set to a true word, or when /.dockerenv exists
        - returns False otherwise
    """
    return container_sentinel_set() or os.path.exists( DOCKERENV_PATH )
