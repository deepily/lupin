from cosa.memory.embedding_manager import EmbeddingManager
from cosa.memory.embedding_provider import get_embedding_provider

from cosa.config.configuration_manager import ConfigurationManager


class QuestionEmbeddingsTable():
    """
    Manages question embeddings storage in Postgres+pgvector.

    Caches embeddings for questions to avoid regenerating them.
    Supports embedding lookup and storage; storage runs through
    QuestionEmbeddingRepository on a short-lived get_db() session per call,
    while embedding generation on a cache miss stays here (the memory layer
    owns generation).
    """
    def __init__( self, debug: bool=False, verbose: bool=False, *args, **kwargs ) -> None:
        """
        Initialize the question embeddings table.

        Requires:
            - LUPIN_CONFIG_MGR_CLI_ARGS environment variable is set or defaults available

        Ensures:
            - Reads the standardized embedding dimension from configuration
            - Opens no connection of its own; storage sessions are per-call

        Raises:
            - ConfigurationManager errors propagated
        """

        self.debug               = debug
        self.verbose             = verbose
        self._config_mgr         = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self._embedding_mgr      = EmbeddingManager( debug=debug, verbose=verbose )
        self._embedding_provider = get_embedding_provider( debug=debug, verbose=verbose )

        # Get standardized embedding dimension from config
        self._embedding_dim = int( self._config_mgr.get( "embedding dimensions", default="768" ) )

    def has( self, question: str ) -> bool:
        """
        Check if a question exists in the embeddings store.

        Requires:
            - question is a non-empty string

        Ensures:
            - Returns True if question exists in the store
            - Returns False if question not found
            - Performs exact string match

        Raises:
            - Repository/session errors propagated
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.question_embedding_repository import QuestionEmbeddingRepository
        with get_db() as session:
            return QuestionEmbeddingRepository( session ).has( question )

    def get_embedding( self, question: str ) -> list[float]:
        """
        Get the embedding for the given question string.

        Requires:
            - question is a non-empty string

        Ensures:
            - Returns the cached embedding when present
            - Generates a new embedding on a miss, and does NOT store it

        Raises:
            - Repository/session errors propagated
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.question_embedding_repository import QuestionEmbeddingRepository
        with get_db() as session:
            cached = QuestionEmbeddingRepository( session ).get_embedding( question )
        if cached is not None:
            return cached
        return self._embedding_provider.generate_embedding( question, content_type="prose" )

    def add_embedding( self, question: str, embedding: list[float] ) -> None:
        """
        Add a question and its embedding to the store.

        Requires:
            - question is a non-empty string
            - embedding is a list of floats of the configured dimension

        Ensures:
            - Appends a question → embedding row to the store

        Raises:
            - Repository/session errors propagated
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.question_embedding_repository import QuestionEmbeddingRepository
        with get_db() as session:
            QuestionEmbeddingRepository( session ).add_embedding( question, embedding )


if __name__ == '__main__':

    question_embeddings_tbl = QuestionEmbeddingsTable()
    question_1 = "what time is it"
    print( f"'{question_1}': in embeddings table [{question_embeddings_tbl.has( question_1 )}]" )
    question_2 = "well how did I get here"
    print( f"'{question_2}': in embeddings table [{question_embeddings_tbl.has( question_2 )}]" )

    embedding = question_embeddings_tbl.get_embedding( question_1 )
    print( f"embedding length: {len( embedding )}" )
