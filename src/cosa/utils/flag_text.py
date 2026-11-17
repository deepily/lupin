"""
The one reading of a hand-typed on/off setting: true, 1, yes or on, in any case, means on.

An operator types these values into an INI file or an environment variable. Every other text,
and an absent value, means off, so a typo never turns a switch on.
"""

FLAG_ON_WORDS = ( "true", "1", "yes", "on" )


def is_flag_on( raw ) -> bool:
    """
    Return True when `raw` reads as an operator's "on".

    Requires:
        - raw is None, a string, or any value whose str() is its text

    Ensures:
        - returns True only for true, 1, yes or on, in any case, with surrounding blanks ignored
        - None, "", and every other text return False
        - never raises for a value whose str() works
    """
    if raw is None: return False
    return str( raw ).strip().lower() in FLAG_ON_WORDS
