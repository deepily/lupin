"""
Build an LLM client for a class that can run without one.

The two DM quality judges, the answer verifier and the script matcher each built their client
in the same try block. It made a factory, asked it for the client, and printed a ready line or
an unavailable line. Each class then went on in a degraded mode when the build failed.
"""


def init_llm_client( factory_class, llm_spec_key, tag, debug=False, verbose=False ):
    """
    Build the client for a model key, or report that none is available.

    Requires:
        - factory_class is LlmClientFactory, looked up by the caller so a test can patch it there
        - llm_spec_key is a model key the factory resolves
        - tag is the caller's log tag, without brackets

    Ensures:
        - returns ( client, True ) when the factory built a client
        - returns ( None, False ) when building raised any exception, after printing
          "[<tag>] LLM client unavailable: <error>"
        - prints "[<tag>] LLM client ready (<key>)" on success when debug is set
        - never raises
    """
    try:
        factory = factory_class( debug=debug, verbose=verbose )
        client  = factory.get_client( llm_spec_key, debug=debug, verbose=verbose )
        if debug: print( f"[{tag}] LLM client ready ({llm_spec_key})" )
        return client, True
    except Exception as e:
        print( f"[{tag}] LLM client unavailable: {e}" )
        return None, False
