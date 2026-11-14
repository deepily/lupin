#!/usr/bin/env python3
"""
Number readers for the string fields of the XML models.

A model field holds what the LLM wrote, so a number arrives as text that may be blank or junk.
One float-or-zero parser, its integer twin and one 0-to-1 clamp serve every model that reads such a field.
"""


def float_or_zero( text ):
    """
    Read a number out of a string field.

    Requires:
        - text is any value; a model field holds a string, but None and junk are expected

    Ensures:
        - returns float( text ) when that works
        - returns 0.0 for None, a blank string, text that is not a number, or any other type float() refuses
        - never raises
    """
    try:
        return float( text )
    except ( ValueError, TypeError ):
        return 0.0


def int_or_zero( text ):
    """
    Read a whole number out of a string field.

    Requires:
        - text is any value; a model field holds a string, but None and junk are expected

    Ensures:
        - returns int( float( text ) ), so "30" and "30.9" both give 30 and a negative stays negative
        - returns 0 for None, a blank string, text that is not a number, nan, infinity, or any other type float() refuses
        - never raises
    """
    try:
        return int( float( text ) )
    except ( ValueError, TypeError, OverflowError ):
        return 0


def clamp_unit( value ):
    """
    Pin a number to the range 0.0 to 1.0.

    Requires:
        - value is a number

    Ensures:
        - returns value when it lies in the range, 0.0 below it and 1.0 above it
        - never raises for a number
    """
    return max( 0.0, min( 1.0, value ) )
