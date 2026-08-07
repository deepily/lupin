#!/usr/bin/env python3
"""
The two halves joined: freeze → rewrite → validate → restore, or the original.

Phase 1 built the safety kernel. Phase 2 built the rewriter. This is the only
place they meet, and it is deliberately thin — every decision it makes was
already made and tested somewhere else.

    freeze( body )  ──bypass?──────────────────────────────► original
          │
          └─► agent.run_prompt() ─► validate() ──ok?──► restore ─► compressed
                                   │
                                   └──not ok──────────────► original

🔑 The failure posture, stated once: **every path that is not a clean success
delivers the original.** A model that times out, returns malformed XML, drops a
placeholder, mangles a delimiter, alters a bare integer, or gets truncated at
`max_tokens` all land in the same place — "no compression on this message". The
worst case is a message that did not get shorter, never a message that got
corrupted.
"""

import cosa.utils.util as du

from cosa.agents.dm_compression.freeze import freeze, validate, compress_or_original


# The floor a rewrite must clear to be worth delivering. Below this, the message
# is delivered unchanged: the latency was already spent either way, but a
# recipient should not receive a rewrite that bought nothing.
MIN_USEFUL_GAIN = 0.05


def compress_dm( body, agent_factory=None, debug=False ):
    """
    Compress one DM body, or return it unchanged.

    Requires:
        - body is a string
        - agent_factory, when given, is a callable taking frozen_text and
          returning an object with .run_prompt() -> dict carrying a
          "compressed" key. That is AgentBase's real invocation method — there
          is no .run(). A stub exposing .run() will pass every unit test and
          fail against the live agent, which is exactly what happened once.

    Ensures:
        - returns ( text_to_deliver, fallback_reason )
        - fallback_reason is None only when a compressed body is being delivered
        - the returned text NEVER contains an unrestored placeholder
        - never raises — every failure becomes a fallback with a reason

    Raises:
        - nothing
    """
    frozen = freeze( body )

    # Nothing worth sending to a model: mostly literals, or too little prose to
    # compress. Phase 1 already decided this; do not re-litigate it here.
    if frozen.should_bypass:
        return body, f"bypass: {frozen.bypass_reason}"

    if agent_factory is None:
        from cosa.agents.dm_compression.compressor import DmCompressionAgent
        agent_factory = lambda frozen_text: DmCompressionAgent( frozen_text=frozen_text, debug=debug )

    try:
        agent    = agent_factory( frozen.frozen_text )
        response = agent.run_prompt()
    except Exception as e:
        # Includes the retry loop having exhausted itself, a truncated response
        # whose XML will not parse, and a validator on the model side refusing
        # an empty body. All the same answer: send the original.
        return body, f"model call failed: {type( e ).__name__}: {e}"

    rewritten = response.get( "compressed" ) if isinstance( response, dict ) else None
    if not rewritten:
        return body, "model returned no compressed body"

    # compress_or_original() runs the full validator and restores only on a
    # clean verdict. It is Phase 1's fail-closed decision point and it never
    # raises — see freeze.py.
    delivered, reason = compress_or_original( rewritten, frozen )
    if reason is not None: return delivered, reason

    # 🔴 Did it actually get shorter?
    #
    # Nothing above asks this. Every structural check can pass on a rewrite that
    # is LONGER than what went in, and the live run produced exactly that: three
    # messages came back at -0.3%, -0.3% and -0.5% and were delivered as
    # "compressed". Paying 3.6 seconds of delivery latency to make a message
    # bigger is the worst outcome available, and it was invisible because
    # "valid" and "shorter" are different questions and only one was being asked.
    gain = 1 - ( len( delivered ) / len( body ) ) if body else 0.0
    if gain < MIN_USEFUL_GAIN:
        return body, f"no useful compression: {gain:.1%} (min {MIN_USEFUL_GAIN:.0%})"

    return delivered, None


def quick_smoke_test():
    """Exercise the pipeline with a stub model. No network, no GPU."""
    du.print_banner( "dm_compression.pipeline smoke test" )

    body = (
        "I spent the morning tracing the leak and I am fairly confident it sits at "
        "judge.py:572, which is the line that shipped in d256e25a last Tuesday. The "
        "consumer thread returns before the pool callback has run, so the job stays "
        "in the running queue even though the work behind it finished perfectly "
        "cleanly. Have a look at src/cosa/rest/queue.py when you get a moment."
    )

    class _Stub:
        """Stands in for Phi-4: shortens the prose, leaves the tokens alone."""
        def __init__( self, frozen_text ): self.frozen_text = frozen_text
        def run_prompt( self ):
            out = self.frozen_text.replace(
                "I spent the morning tracing the leak and I am fairly confident it sits at",
                "Leak at" )
            return { "thoughts": "cut the preamble", "compressed": out }

    class _Breaks( _Stub ):
        """Stands in for a model that drops a placeholder."""
        def run_prompt( self ):
            out = super().run_prompt()[ "compressed" ]
            return { "compressed": out.replace( "[[L00]]", "" ) }

    class _Dies( _Stub ):
        def run_prompt( self ): raise RuntimeError( "vLLM unreachable" )

    for label, factory in [
        ( "good rewrite",  _Stub ),
        ( "dropped token", _Breaks ),
        ( "model down",    _Dies ),
        ( "short message", _Stub ),
    ]:
        source = "too short to bother" if label == "short message" else body
        text, reason = compress_dm( source, agent_factory=factory )

        shorter = len( text ) < len( source )
        print( f"  {label:<15} delivered={'compressed' if reason is None else 'ORIGINAL'}"
               f"  shorter={shorter}" )
        if reason: print( f"                   reason: {reason[ :90 ]}" )

        assert "[[L" not in text, "an unrestored placeholder escaped — this must never happen"
        if reason is not None: assert text == source, "fallback must deliver the source byte-exact"

    print()
    print( "  ✓ no path delivered an unrestored placeholder" )


if __name__ == "__main__":
    quick_smoke_test()
