"""
Prove a guard fires: call a function and require it to raise.

Two smoke tests (the Vertex logging canary law and the DM judge extraction controls) each
kept a private copy; this is the one they share.
"""


def expect_raises( exception_type, fn, *args, **kwargs ):
    """
    Assert that `fn` fails loud with `exception_type`.

    A guard never seen to fire is not a proven guard. A smoke test uses this so that "the guard works" is an observation, not a claim.

    Requires:
        - exception_type is an exception class; fn is callable

    Ensures:
        - returns the raised exception when fn raises exception_type

    Raises:
        - AssertionError when fn does not raise; a guard that stayed silent is a failure
    """
    try:
        fn( *args, **kwargs )
    except exception_type as raised:
        return raised
    raise AssertionError( f"{fn.__name__} did NOT raise {exception_type.__name__} — the guard is asleep." )
