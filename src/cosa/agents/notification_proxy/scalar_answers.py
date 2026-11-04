"""
Scalar guard for predicted batch answers.

A prediction whose per-question answer is a non-scalar, an object or a list, must never
be stamped as a high-confidence answer on the user's behalf. When `String( value )`
reaches the client, it renders "[object Object]" for an object and "a,b,c" for a list.
It puts that text in the input and presents it as a >= 0.9-confidence answer.

The rule is to drop the entry, not to coerce it. A dropped header becomes a question the
user actually gets asked. A coerced one is a wrong answer submitted for them. The
producers that build predicted answers already return None on an empty map. Dropping the
last non-scalar therefore degrades cleanly to "ask the user".

Two producers build and stamp predicted answers, and both call this guard:
    - notification_proxy/strategies/expediter_rules.py
    - notification_proxy/strategies/llm_script_matcher.py
The client guard in notifications.js (_batchPredictedAnswers) stays as a second layer
for any producer not listed here.
"""


def drop_non_scalar_answers( answers, context ):
    """
    Keep only scalar header-to-value answers; drop the rest and never coerce them.

    Requires:
        - answers is a dict mapping header (str) -> value, or any other value
          (a non-dict is treated as "no usable answers")
        - context is a short str naming the call site, used in the drop log

    Ensures:
        - returns a new dict; the input is never mutated
        - keeps an entry only when its value is str / int / float / bool;
          numbers and bools are stringified so the payload is uniformly str
        - a non-dict `answers` yields an empty dict
        - every dropped entry is logged loudly (header, value type, context) so a
          non-scalar prediction is visible, not silent

    Args:
        answers: candidate answers map { header -> value }
        context: short call-site label for the drop log line

    Returns:
        dict: { header -> str } holding only the scalar answers
    """
    if not isinstance( answers, dict ): return {}

    kept = {}
    for header, value in answers.items():
        # bool is a subclass of int — test it first so True/False keep as-is.
        if isinstance( value, bool ):
            kept[ header ] = str( value )
        elif isinstance( value, ( int, float ) ):
            kept[ header ] = str( value )
        elif isinstance( value, str ):
            kept[ header ] = value
        else:
            print( f"[drop_non_scalar_answers] DROPPED non-scalar answer '{header}' (type={type( value ).__name__}) at {context}" )

    return kept


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """Exercise drop_non_scalar_answers across its branches."""
    import cosa.utils.util as cu
    cu.print_banner( "scalar_answers smoke test", prepend_nl=True )

    try:
        # 1) A scalar-only map survives, with numbers/bools stringified.
        out = drop_non_scalar_answers( { "A": "yes", "B": 3, "C": 1.5, "D": True }, "smoke" )
        assert out == { "A": "yes", "B": "3", "C": "1.5", "D": "True" }, f"scalars must survive stringified: {out}"
        print( "✓ scalars kept (numbers + bool stringified)" )

        # 2) Non-scalar values are dropped, scalars in the same map are kept.
        out = drop_non_scalar_answers( { "A": "keep", "B": { "x": 1 }, "C": [ 1, 2 ] }, "smoke" )
        assert out == { "A": "keep" }, f"non-scalars must drop: {out}"
        print( "✓ object + list dropped, scalar kept" )

        # 3) An all-non-scalar map degrades to empty → producer returns None upstream.
        out = drop_non_scalar_answers( { "B": { "x": 1 } }, "smoke" )
        assert out == {}, f"all-non-scalar must empty: {out}"
        print( "✓ all-non-scalar degrades to empty (upstream returns None)" )

        # 4) A non-dict input yields empty, never raises.
        assert drop_non_scalar_answers( None, "smoke" ) == {}, "None must yield {}"
        assert drop_non_scalar_answers( "not a dict", "smoke" ) == {}, "str must yield {}"
        print( "✓ non-dict input yields empty, no raise" )

        print( "\n✓ ALL scalar_answers smoke tests passed" )
    except AssertionError as e:
        print( f"\n✗ smoke test FAILED: {e}" )
        raise


if __name__ == "__main__":
    quick_smoke_test()
