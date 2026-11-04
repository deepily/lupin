"""
Identifier splitting for the candidate stage.

A name, a file path and a signature all break into the same lowercase words.
So a need written as "user profile" meets `getUserProfile` and `get_user_profile`.
"""
import re

WORD = re.compile( r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+|[^\W\d_]+" )


def split_identifier( text ):
    """
    Split text into lowercase words.

    Requires:
        - text is a string

    Ensures:
        - breaks on every character that is not a letter or a digit, so underscores, dots and path separators split
        - breaks a word at a lower-to-upper change, so getUserProfile gives get, user, profile
        - keeps an acronym whole up to its last capital, so HTTPServer gives http, server
        - makes each run of digits its own word, so utf8 gives utf, 8
        - returns the words in text order, lowercased, with repeats kept
    """
    return [ word.lower() for word in WORD.findall( text ) ]
