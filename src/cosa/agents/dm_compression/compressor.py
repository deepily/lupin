#!/usr/bin/env python3
"""
The DM compression agent — the rewriter half of arm 4.

Takes a FROZEN message body (placeholders already substituted by Phase 1's
freeze protocol), asks the local Phi-4 to shorten it, and hands back the model's
output still holding its placeholders. It does NOT restore, validate, or decide
what to deliver — `pipeline.py` does that, using Phase 1's machinery unchanged.

WHY A LOCAL MODEL. The original plan spent its §2 hunting for a hosted endpoint
cheap enough to pay for itself — a $1.70/M blended ceiling, a Flash-class target,
a table showing Opus loses money. Rick's direction closed that question by
pointing at the Phi-4-14B already serving on :3001. A local vLLM has no
per-token cost, so the only remaining budget is LATENCY, because this sits in
the DM delivery path.
"""

import time

import cosa.utils.util as du

from cosa.agents.agent_base import AgentBase


class DmCompressionAgent( AgentBase ):
    """
    Rewrites one frozen DM body into a shorter one, preserving its placeholders.

    Shaped after `MathAgent` — the minimal canonical `AgentBase` form — with a
    bounded retry loop borrowed from `DmQualityJudge`, because the base class
    does not have one and a transient vLLM hiccup should not cost a message its
    compression.
    """

    ROUTING_COMMAND = "dm compression rewrite"

    # Retry shape copied from the judge. Three attempts total; a failure after
    # that is not an error condition — the caller simply delivers the original.
    MAX_ATTEMPTS  = 3
    RETRY_BACKOFF = ( 0.5, 1.0 )

    def __init__( self, frozen_text: str="", question: str="", question_gist: str="",
                  last_question_asked: str="", push_counter: int=-1,
                  routing_command: str=ROUTING_COMMAND,
                  user_id: str="ricardo_felipe_ruiz_6bdc", user_email: str="",
                  session_id: str="", debug: bool=False, verbose: bool=False,
                  auto_debug: bool=False, inject_bugs: bool=False ) -> None:
        """
        Initialize the compression agent for one frozen message body.

        Requires:
            - frozen_text is a non-empty string carrying [[Lnn]] placeholders
            - the routing command is registered in MODEL_MAPPING, in
              agent_model_map, and in the INI (see the module docstring of
              xml_models.py and §4 of the Phase 2 plan)

        Ensures:
            - self.prompt holds the template with the frozen body substituted
            - self.xml_response_tag_names matches DmCompressionResponse

        Raises:
            - ValueError if frozen_text is empty
            - KeyError if the routing command's config is missing
        """
        if not frozen_text or not frozen_text.strip():
            raise ValueError( "frozen_text is empty — there is nothing to compress" )

        # AgentBase requires a question or a last_question_asked and raises
        # without one. There is no user question here — the "question" IS the
        # message being compressed — so the frozen body stands in for it. The
        # prompt is built from frozen_text directly below regardless; this only
        # satisfies the base class's own precondition.
        if not question and not last_question_asked:
            question = frozen_text

        super().__init__(
            df_path_key=None, question=question, question_gist=question_gist,
            last_question_asked=last_question_asked, routing_command=routing_command,
            push_counter=push_counter, user_id=user_id, user_email=user_email,
            session_id=session_id, debug=debug, verbose=verbose,
            auto_debug=auto_debug, inject_bugs=inject_bugs
        )

        self.frozen_text = frozen_text

        # ⚠️ .replace(), NOT .format().
        #
        # The frozen text is full of `[[L00]]` placeholders and DM bodies carry
        # literal braces of their own — code fences, dict literals, f-strings.
        # `str.format` reads every brace as a field and raises KeyError on the
        # first one it cannot resolve. The judge hit exactly this and documents
        # it at judge.py:748.
        self.prompt = self.prompt_template.replace( "{dm_body}", frozen_text )

        self.xml_response_tag_names = [ "thoughts", "compressed" ]

    def run_prompt( self, **kwargs ):
        """
        Call the model, with a bounded retry on transient failure.

        Requires:
            - self.prompt is populated

        Ensures:
            - returns the parsed response dict on success
            - retries at most MAX_ATTEMPTS times with the configured backoff
            - re-raises the LAST exception when every attempt fails, so the
              caller can fall back to delivering the original

        Raises:
            - whatever the underlying LLM client raised on the final attempt
        """
        last_error = None

        for attempt in range( self.MAX_ATTEMPTS ):
            try:
                return super().run_prompt( **kwargs )
            except Exception as e:
                last_error = e
                if self.debug: print( f"[dm-compression] attempt {attempt + 1}/{self.MAX_ATTEMPTS} failed: {e}" )
                if attempt < len( self.RETRY_BACKOFF ): time.sleep( self.RETRY_BACKOFF[ attempt ] )

        raise last_error

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
        raise NotImplementedError( "DmCompressionAgent.restore_from_serialized_state() not implemented" )


def quick_smoke_test():
    """Construct the agent and inspect the prompt it would send. No model call."""
    du.print_banner( "DmCompressionAgent smoke test" )

    frozen = (
        "I spent the morning tracing the leak and I am fairly confident it sits at "
        "[[L00]], which is the line that shipped in [[L01]] last Tuesday. Have a "
        "look at [[L02]] when you get a moment and tell me whether you read it the "
        "same way that I do."
    )

    try:
        agent = DmCompressionAgent( frozen_text=frozen, debug=False, verbose=False )
    except Exception as e:
        print( f"  ✗ construction failed: {type( e ).__name__}: {e}" )
        print( "    (check the two registries and the INI keys — see §4 of the plan)" )
        return

    prompt = agent.prompt

    checks = [
        ( "body substituted",        "[[L00]]" in prompt ),
        ( "no unresolved {dm_body}", "{dm_body}" not in prompt ),
        ( "XML example injected",    "{{PYDANTIC_XML_EXAMPLE}}" not in prompt ),
        ( "</stop> sentinel present", "</stop>" in prompt ),
        ( "CDATA taught",            "CDATA" in prompt ),
    ]

    for label, ok in checks:
        print( f"  {label:<26} {'✓' if ok else '✗'}" )

    print()
    print( f"  prompt length: {len( prompt ):,} chars" )
    print( f"  tag names    : {agent.xml_response_tag_names}" )


if __name__ == "__main__":
    quick_smoke_test()
