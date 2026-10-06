"""
CJ Flow v2 router call, decoupled from TodoFifoQueue.

Building a `TodoFifoQueue` drags in Gister, GistNormalizer, Normalizer, QueryLogTable and an
embedding provider. That is the machinery v2 exists to shed. The routing body lives in the
module-level `get_routing_command( question, config_mgr, llm_factory, debug, verbose )`, and
the `TodoFifoQueue` method delegates to it. This client calls that function with only what
the router needs, a config_mgr and an LlmClientFactory. It never constructs a TodoFifoQueue.
"""

from cosa.rest.todo_fifo_queue import get_routing_command
from cosa.agents.llm_client_factory import LlmClientFactory


class RouterClient:
    """
    Turns a question into a ( command, args ) routing decision without a TodoFifoQueue.

    Requires:
        - config_mgr exposes .get( "prompt template for agent router" ) and
          .get( "llm spec key for agent router" )

    Ensures:
        - route() returns the same ( command, args ) the v1 path would, by
          delegating to the module-level get_routing_command
        - Construction builds only an LlmClientFactory — none of the gister /
          normalizer / query-log / embedding machinery TodoFifoQueue drags in
    """

    def __init__( self, config_mgr, debug=False, verbose=False ):
        """
        Build the router client.

        Requires:
            - config_mgr is a valid ConfigurationManager

        Ensures:
            - Holds config_mgr + an LlmClientFactory; constructs no TodoFifoQueue
        """
        self.config_mgr  = config_mgr
        self.debug       = debug
        self.verbose     = verbose
        self.llm_factory = LlmClientFactory( debug=debug, verbose=verbose )

    def route( self, question ):
        """
        Route a question to a ( command, args ) pair through the LoRA router.

        Requires:
            - question is a non-empty string

        Ensures:
            - Returns a ( command, args ) tuple of strings
            - Returns ( "unknown", "" ) on any router XML parse failure (the
              module-level get_routing_command's contract)

        Args:
            question: The user's utterance to route.

        Returns:
            ( str, str ): ( command, args )
        """
        return get_routing_command(
            question, self.config_mgr, self.llm_factory,
            debug=self.debug, verbose=self.verbose
        )
