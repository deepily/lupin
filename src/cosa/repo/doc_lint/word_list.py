"""
The English word list behind the ALL-CAPS predicate (rule 4).

An ALL-CAPS token is emphasis when its lowercase form is a word. The list is the one lupin
already vendors for the DM tutor. Entry points that run in a bare interpreter (the pre-commit
gate) call configure_root with the working tree. So this module needs no third-party imports.
lupin-mobile's vendored copy passes its own set to the rule functions instead.
"""

WORD_LIST_REL = "/src/conf/dm-tutor-lowercase-words.txt"

_state = { "root": None, "words": None }


def configure_root( root ):
    """
    Point the word list at a working tree and drop any list already read.

    Requires:
        - root is a directory that holds WORD_LIST_REL

    Ensures:
        - the next default_words call reads the list under root

    Raises:
        - nothing
    """
    _state[ "root" ]  = str( root )
    _state[ "words" ] = None


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
    Return the word list, read once until configure_root is called again.

    Requires:
        - configure_root was called, or LUPIN_ROOT names a tree that holds WORD_LIST_REL

    Ensures:
        - returns a frozenset of lowercase words
        - later calls return the same object

    Raises:
        - OSError when the list is missing
    """
    if _state[ "words" ] is None:
        root = _state[ "root" ]
        if root is None:
            import cosa.utils.util as cu
            root = cu.get_project_root()
        _state[ "words" ] = load_words( root + WORD_LIST_REL )
    return _state[ "words" ]
