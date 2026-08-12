#!/usr/bin/env python3
"""
The DM tutor agent — distills one verbose DM into the shape Rick specified.

    headline (a declaration OR a question)
    supporting statement
    supporting statement
    the most relevant path or URL, when the message carries one

This is the object the DM send path calls, not a research script. Its contract
is FAIL-CLOSED and that is the whole design: `rewrite_dm( body )` returns the
distilled lines, or `None`. `None` always means "deliver the original" — never
"deliver something shorter that might be wrong". A tutor that occasionally
mangles a message is worse than no tutor at all, because the recipient cannot
tell which kind of message they are holding.

WHY THIS EXISTS AS AN AGENT AND NOT A SCRIPT. The prompt was proven on 2026-08-11
by calling the LLM client directly, deliberately bypassing `AgentBase` — the only
agent available then validated against a schema requiring a `compressed` field
this prompt never produces, so good answers were being discarded. `DmTutorResponse`
removes that reason. Going through the standard path also fixes the envelope
problem by construction: `PromptTemplateProcessor` appends the `</stop>` sentinel
the vLLM stop list is configured to catch (`prompt_template_processor.py:130`,
`lupin-app.ini` `dm_tutor/phi_4_params`), which a hand-rolled prompt never did.

⚠️ THE SENTINEL DID NOT CAUSE THE 2026-08-11 RESULT, AND THE RECORD SHOULD SAY SO.
That run came back clean on all four bands WITHOUT it — `dm.txt` contains no
mention of `stop`, and the harness substituted its example bare. The five-slot
scaffold is what made it work; the sentinel is a separate, independently measured
win (3,004 words / 56.2s → 114 / 3.2s on a 250+ message). Promoting to `AgentBase`
therefore ADDS a real change rather than preserving one, which is why this class
carries `include_stop_sentinel` — so the two can be measured apart instead of
being credited to each other.
"""

import cosa.utils.util as du

from cosa.agents.agent_base            import AgentBase
from cosa.agents.dm_tutor.xml_models   import DmTutorResponse


class DmTutorAgent( AgentBase ):
    """
    Rewrites one DM body into a headline, two supporting statements, a pointer.

    Shaped after `DmCompressionAgent` — the minimal `AgentBase` form used by the
    sibling arm — and carrying its two hard-won constraints: no synchronous
    retry, and `.replace()` instead of `.format()`.
    """

    ROUTING_COMMAND = "dm tutor rewrite"

    # 🔴 NO SYNCHRONOUS RETRY. Inherited from the compression arm, where it was
    # measured rather than assumed: of 1,066s of total model time, 894s (83.9%)
    # went to attempts that delivered nothing, and failing calls averaged 49.1s
    # against 3.8s for successful ones. A malformed response is not a transient
    # fault — asking the same model the same question again mostly buys the same
    # answer, slower. This sits between a sender and a recipient; a failed
    # rewrite costs nothing but the original message, and a retry costs delay.

    def __init__( self, dm_body: str="", include_stop_sentinel: bool=True,
                  question: str="", question_gist: str="",
                  last_question_asked: str="", push_counter: int=-1,
                  routing_command: str=ROUTING_COMMAND,
                  user_id: str="ricardo_felipe_ruiz_6bdc", user_email: str="",
                  session_id: str="", debug: bool=False, verbose: bool=False,
                  auto_debug: bool=False, inject_bugs: bool=False ) -> None:
        """
        Initialize the tutor for one DM body.

        Requires:
            - dm_body is a non-empty string
            - the routing command is registered in MODEL_MAPPING, in
              agent_model_map, and in the INI (all four sites — see §3.4 of the
              plan; a miss in any one ships a silently broken prompt)

        Ensures:
            - self.prompt holds the template with the DM body substituted
            - self.prompt carries no unresolved {dm} or {{PYDANTIC_XML_EXAMPLE}}
            - self.xml_response_tag_names matches DmTutorResponse's tags
            - the </stop> sentinel is present unless include_stop_sentinel=False

        Raises:
            - ValueError if dm_body is empty
            - KeyError if the routing command's config is missing
        """
        if not dm_body or not dm_body.strip():
            raise ValueError( "dm_body is empty — there is nothing to distill" )

        # AgentBase requires a question or a last_question_asked and raises
        # without one. There is no user question here — the "question" IS the
        # message being distilled — so the body stands in for it. The prompt is
        # built from dm_body directly below regardless; this only satisfies the
        # base class's own precondition.
        if not question and not last_question_asked:
            question = dm_body

        super().__init__(
            df_path_key=None, question=question, question_gist=question_gist,
            last_question_asked=last_question_asked, routing_command=routing_command,
            push_counter=push_counter, user_id=user_id, user_email=user_email,
            session_id=session_id, debug=debug, verbose=verbose,
            auto_debug=auto_debug, inject_bugs=inject_bugs
        )

        self.dm_body               = dm_body
        self.include_stop_sentinel = include_stop_sentinel

        template = self.prompt_template

        # The experiment's control arm. `PromptTemplateProcessor` appended
        # "</stop>" to the injected example during super().__init__(); removing
        # it here reproduces exactly the prompt shape that ran on 2026-08-11, so
        # the two arms differ in the sentinel and nothing else.
        if not include_stop_sentinel:
            template = template.replace( "</stop>", "" )

        # ⚠️ .replace(), NOT .format().
        #
        # DM bodies carry literal braces of their own — code fences, dict
        # literals, f-strings, [[Lnn]]-style markers. `str.format` reads every
        # brace as a field and raises KeyError on the first one it cannot
        # resolve. The compression arm hit exactly this (compressor.py:110).
        self.prompt = template.replace( "{dm}", dm_body )

        self.xml_response_tag_names = list( DmTutorResponse.TAG_FOR_FIELD.values() )

    def rewrite( self ) -> str:
        """
        Call the model and return the lines a recipient would see.

        FAIL-CLOSED. Every failure mode — an unreachable model, malformed XML, a
        dropped required slot, a validation error — returns None, and None means
        the caller delivers the original message unchanged.

        Requires:
            - self.prompt is built (the constructor guarantees it)

        Ensures:
            - returns the headline, both supporting statements, and the pointer
              when present, newline-joined
            - returns None on ANY failure, having raised nothing
            - self.response holds the parsed DmTutorResponse on success, None
              otherwise

        Raises:
            - nothing
        """
        self.response = None
        self.error    = None

        try:
            fields        = self.run_prompt()
            self.response = DmTutorResponse( **fields )
            return self.response.to_delivery()
        except Exception as e:
            # Deliberately broad. This sits in the DM delivery path, where the
            # correct answer to every unexpected condition is the same: send the
            # original. The reason is kept for the harness and for diagnosis —
            # discarded reasons are what made the 2026-08-11 failures
            # unanswerable.
            self.error = f"{type( e ).__name__}: {e}"
            if self.debug: print( f"[dm-tutor] rewrite failed — {self.error}" )
            return None

    def restore_from_serialized_state( self, file_path: str ) -> None:
        """
        Not implemented — this agent holds no state worth restoring.

        Requires:
            - file_path points to a JSON file

        Ensures:
            - raises NotImplementedError

        Raises:
            - NotImplementedError always
        """
        raise NotImplementedError( "DmTutorAgent.restore_from_serialized_state() not implemented" )


def rewrite_dm( dm_body: str, include_stop_sentinel: bool=True,
                debug: bool=False, verbose: bool=False ) -> str:
    """
    The DM send path's entry point: one body in, distilled lines or None out.

    A free function rather than a method so a caller needs to know nothing about
    agent construction, and so CONSTRUCTION failures fail closed too — a missing
    INI key or an unregistered routing command must deliver the original
    message, not raise into the sender's call stack.

    Requires:
        - dm_body is a string

    Ensures:
        - returns the distilled lines on success
        - returns None on any failure, including an empty body and any
          construction error, having raised nothing

    Raises:
        - nothing
    """
    try:
        agent = DmTutorAgent(
            dm_body=dm_body, include_stop_sentinel=include_stop_sentinel,
            debug=debug, verbose=verbose
        )
    except Exception as e:
        if debug: print( f"[dm-tutor] construction failed — {type( e ).__name__}: {e}" )
        return None

    return agent.rewrite()


def quick_smoke_test():
    """Construct the agent and inspect the prompt it would send. No model call."""
    du.print_banner( "DmTutorAgent smoke test" )

    body = (
        "I spent the morning tracing the leak and I am fairly confident it sits "
        "at src/cosa/rest/queue.py:412, which is the line that shipped in f4e0370 "
        "last Tuesday. Have a look when you get a moment and tell me whether you "
        "read it the same way that I do."
    )

    try:
        agent = DmTutorAgent( dm_body=body, debug=False, verbose=False )
    except Exception as e:
        print( f"  ✗ construction failed: {type( e ).__name__}: {e}" )
        print( "    (check the four registration sites — see §3.4 of the plan)" )
        return

    prompt = agent.prompt

    # Every check here guards a failure that is SILENT without it. An
    # unprocessed template does not raise: AgentBase swallows the processor's
    # exception (agent_base.py:161) and ships the template as-is.
    checks = [
        ( "body substituted",         "queue.py:412" in prompt ),
        ( "no unresolved {dm}",       "{dm}" not in prompt ),
        ( "XML example injected",     "{{PYDANTIC_XML_EXAMPLE}}" not in prompt ),
        ( "</stop> sentinel present", "</stop>" in prompt ),
        ( "CDATA taught",             "CDATA" in prompt ),
        ( "path slot taught",         "file-path-or-url-if-present" in prompt ),
    ]

    for label, ok in checks:
        print( f"  {label:<28} {'✓' if ok else '✗'}" )

    # The control arm must differ in the sentinel and NOTHING else.
    control = DmTutorAgent( dm_body=body, include_stop_sentinel=False )
    delta   = len( agent.prompt ) - len( control.prompt )
    print()
    print( f"  control arm (no sentinel)    {'✓' if '</stop>' not in control.prompt else '✗'}"
           f"  · differs by {delta} chars (expected {len( '</stop>' )})" )

    print()
    print( f"  prompt length: {len( prompt ):,} chars" )
    print( f"  tag names    : {agent.xml_response_tag_names}" )


if __name__ == "__main__":
    quick_smoke_test()
