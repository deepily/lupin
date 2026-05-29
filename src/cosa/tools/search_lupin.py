"""
This object is a wrapper for the KagiSearch object.

Purpose: provide a simple vendor-neutral interface to the KagiSearch and/or other objects.
"""

from cosa.tools.search_kagi import KagiSearch
from cosa.agents.v000.raw_output_formatter import RawOutputFormatter

import cosa.utils.util as du
from typing import Optional, Union, Any

class LupinSearch:
    """
    Vendor-neutral wrapper for web search functionality.
    
    Provides a simple interface to KagiSearch and potentially other search providers.
    """
    def __init__( self, query: Optional[str]=None, url: Optional[str]=None, debug: bool=False, verbose: bool=False ) -> None:
        """
        Initialize the LupinSearch wrapper.
        
        Requires:
            - Either query or url should be provided (not both)
            
        Ensures:
            - Creates KagiSearch instance with provided parameters
            - Initializes results to None
            
        Raises:
            - None
        """
        
        self.debug     = debug
        self.verbose   = verbose
        self.query     = query
        self.url       = url
        self._searcher = KagiSearch( query=query, url=url, debug=debug, verbose=verbose )
        self._results  = None
    
    def search_and_summarize_the_web( self ) -> None:
        """
        Perform web search and summarization.
        
        Requires:
            - Query or URL was provided at initialization
            - KagiSearch instance is initialized
            
        Ensures:
            - Populates self._results with search data
            - Results include meta, data, and summary sections
            
        Raises:
            - KagiSearch errors propagated
        """
        self._results = self._searcher.search_fastgpt()
        
    def get_results( self, scope: str="all" ) -> Optional[Union[dict, str, list]]:
        """
        Get search results by scope.
        
        Requires:
            - search_and_summarize_the_web() has been called
            - scope is one of: 'all', 'meta', 'data', 'summary', 'references'
            
        Ensures:
            - Returns requested portion of results
            - Returns None for invalid scope with error message
            
        Raises:
            - KeyError if results structure is invalid
        """
        if scope == "all":
            return self._results
        elif scope == "meta":
            return self._results[ "meta" ]
        elif scope == "data":
            return self._results[ "data" ]
        elif scope == "summary":
            return self._results[ "data" ][ "output" ]
        elif scope == "references":
            return self._results[ "data" ][ "references" ]
        else:
            du.print_banner( f"ERROR: Invalid scope: {scope}.  Must be { 'all', 'meta', 'data', 'summary', 'references' }", expletive=True )
            return None
        
if __name__ == '__main__':
    
    # query   = "What's the temperature in Washington DC?"
    query    = "is there such thing as a daily cognitive or attention budget?"
    search  = GibSearch( query=query )
    search.search_and_summarize_the_web()
    results = search.get_results( scope="summary" )
    meta    = search.get_results( scope="meta" )
    
    print( results )
    
    formatter = RawOutputFormatter( query, results, routing_command="agent router go to weather", debug=False, verbose=False )
    output    = formatter.run_formatter()
    print( output )
    
    