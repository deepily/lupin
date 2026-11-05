"""
The optional need expander of the candidate stage.

The INI switch `reuse candidate need expansion enabled` turns it on. One text-only model call turns the need into three paraphrases and five identifier words.
The candidate stage searches each of them too and fuses every list into the same shortlist.
The model sees the need sentence and nothing else: tools are off and no repository file is read.
The prompt and the reader are expansion_replay's, so a live lookup asks what the measured replay asked.
"""
import asyncio
import concurrent.futures

from cosa.repo.doc_lint import model_transport
from lupin_mcp.reuse_needset import expansion_replay as ex

EXPANSION_MODEL = "claude-fable-5-1"      # the model the measured replay's expansions came from (draft.DRAFTER_MODEL)


def ask_model( model, system, user ):
    """
    Send one prompt to the model and return its reply text.

    Requires:
        - model is a model id; the call may come from a thread that already runs an event loop

    Ensures:
        - the call runs on a worker thread of its own, so it never meets the caller's event loop
        - returns the reply text, never empty

    Raises:
        - model_transport.ModelCallError when the call fails, times out or returns no text
        - model_transport.CallBudgetExceeded when a cap on the model is spent
    """
    with concurrent.futures.ThreadPoolExecutor( max_workers=1 ) as pool:
        return pool.submit( lambda: asyncio.run( model_transport.complete( model, system, user ) ) ).result()


def make_expander( ask=None, model=EXPANSION_MODEL, out=print ):
    """
    Build the function the candidate stage calls for each lookup.

    Requires:
        - ask is None for the real model, or a function taking ( system, user ) and returning reply text, as the tests pass
        - out takes one line of text

    Ensures:
        - the returned function takes the ranking text and returns { paraphrases, identifiers } with three paraphrases and one to five identifier words
        - it returns None, after one line to out, when the model call fails or its reply is not that shape, so the lookup runs as it would without expansion
        - the model is shown the ranking text only
    """
    def expand( ranking_text ):
        """Ensures: returns the need's expansion, or None when the model gave none."""
        try:
            reply = ask( ex.SYSTEM, ex.expansion_prompt( ranking_text ) ) if ask is not None else ask_model( model, ex.SYSTEM, ex.expansion_prompt( ranking_text ) )
        except ( model_transport.ModelCallError, model_transport.CallBudgetExceeded ) as error:
            out( f"[need expansion] the model call failed, searching without expansion: {type( error ).__name__}: {error}" )
            return None
        found = ex.parse_expansion( reply )
        if found is None: out( "[need expansion] the reply was not three paraphrases and one to five identifier words, searching without expansion" )
        return found
    return expand
