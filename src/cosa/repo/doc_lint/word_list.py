"""
The English word list behind the ALL-CAPS predicate (rule 4).

An ALL-CAPS token is emphasis when its lowercase form is a word. The list is the one lupin
already vendors for the DM tutor; lupin-mobile's vendored copy of the linters passes its own
set to the rule functions instead of calling this module.
"""

import cosa.utils.util as cu

WORD_LIST_REL = "/src/conf/dm-tutor-lowercase-words.txt"

_cache = {}


def load_words( path ):
    """
    Read a word list, one lowercase word per line.

    Requires:
        - path names a UTF-8 text file

    Ensures:
        - returns a frozenset of the non-blank stripped lines

    Raises:
        - OSError when the file cannot be read; an unreadable list must not silently turn rule 4 off
    """
    with open( path, encoding="utf-8" ) as handle:
        return frozenset( line.strip() for line in handle if line.strip() )


def default_words():
    """
    Return the vendored word list, read once per process.

    Requires:
        - LUPIN_ROOT names a tree that holds WORD_LIST_REL

    Ensures:
        - returns a frozenset of lowercase words
        - later calls return the same object

    Raises:
        - OSError when the list is missing
    """
    if "words" not in _cache:
        _cache[ "words" ] = load_words( cu.get_project_root() + WORD_LIST_REL )
    return _cache[ "words" ]
