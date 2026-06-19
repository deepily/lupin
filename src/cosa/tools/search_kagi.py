from kagiapi import KagiClient
# import requests

import cosa.utils.util as du

from cosa.utils.util_stopwatch import Stopwatch
from typing import Optional, Any

class KagiSearch:
    """
    Wrapper for Kagi search API functionality.
    
    Provides FastGPT search and URL summarization capabilities.
    """
    def __init__( self, query: Optional[str]=None, url: Optional[str]=None, debug: bool=False, verbose: bool=False ) -> None:
        """
        Initialize KagiSearch client.
        
        Requires:
            - Kagi API key available through du.get_api_key()
            - Either query or url provided for search/summarization
            
        Ensures:
            - Creates KagiClient with API key
            - Sets query or url for operations
            
        Raises:
            - KeyError if API key not found
        """
        
        self.debug    = debug
        self.verbose  = verbose
        self.query    = query
        self.url      = url
        self._key     = du.get_api_key( "kagi" )
        self._kagi    = KagiClient( du.get_api_key( "kagi" ) )
        
    # def search_fastgpt_req( self ):
    #
    #     base_url = 'https://kagi.com/api/v0/fastgpt'
    #     data = {
    #         "query": self.query,
    #     }
    #     headers = { 'Authorization': f'Bot {self._key}' }
    #
    #     timer = Stopwatch( "Kagi FastGPT: via requests.post" )
    #     response = requests.post( base_url, headers=headers, json=data )
    #     timer.print( "Done!", use_millis=True)
    #
    #     return response.json()
    
    def search_fastgpt( self ) -> dict[str, Any]:
        """
        Perform FastGPT search with query.
        
        Requires:
            - self.query is set and non-empty
            - Kagi client is initialized
            
        Ensures:
            - Returns dict with 'meta' and 'data' sections
            - 'data' contains 'output' with search results
            - Prints timing information
            
        Raises:
            - KagiAPI errors propagated
        """
        timer    = Stopwatch( f"Kagi FastGPT query: [{self.query}]" )
        response = self._kagi.fastgpt( query=self.query )
        timer.print( "Done!", use_millis=True )
        
        return response
    
    # def get_summary_req( self ):
    #
    #     import requests
    #
    #     base_url = 'https://kagi.com/api/v0/summarize'
    #     params = {
    #         "url"         : self.url,
    #         "summary_type": "summary",
    #         "engine"      : "agnes"
    #     }
    #     headers = { 'Authorization': f'Bot {self._key}' }
    #
    #     timer = Stopwatch( "Kagi: Summary: Request" )
    #     response = requests.get( base_url, headers=headers, params=params )
    #     timer.print( "Done!", use_millis=True )
    #
    #     return response.json()
    
    def get_summary( self ) -> dict[str, Any]:
        """
        Get summary of URL content.
        
        Requires:
            - self.url is set and valid
            - Kagi client is initialized
            
        Ensures:
            - Returns dict with summary data
            - Uses 'agnes' engine for summarization
            - Prints timing information
            
        Raises:
            - KagiAPI errors propagated
        """
        timer = Stopwatch( "Kagi: Summarize" )
        if self.debug: print( f"Kagi: Summarize: URL: [{self.url}]" )
        response = self._kagi.summarize( url=self.url, engine="agnes", summary_type="summary" )
        timer.print( "Done!", use_millis=True )
        
        return response
    
if __name__ == '__main__':
    
    # url  = "https://weather.com/weather/tenday/l/Washington+DC?canonicalCityId=4c0ca6d01716c299f53606df83d99d5eb96b2ee0efbe3cd15d35ddd29dee93b2"
    # kagi = KagiSearch( url=url )
    
    # summary = kagi.get_summary_req()
    # # summary = kagi.get_summary()
    # du.print_banner( "Kagi: Summary: Meta" )
    # print( summary[ "meta" ] )
    # du.print_banner( "Kagi: Summary: Data" )
    # print( summary[ "data" ] )
    
    date     = du.get_current_date()
    time     = du.get_current_time()
    
    # question = "The current date and time is {date} at {time}. What's the current temperature in Washington DC?"
    question = "Ask perplexity if there’s any such a thing as a daily cognitive or attention budget"
    # question = "What's the weather forecast for Washington DC?"
    # question = "What's the weather forecast for Puerto Rico?"
    kagi     = KagiSearch( query=question )

    # fastgpt = kagi.search_fastgpt_req()
    fastgpt = kagi.search_fastgpt()

    # du.print_banner( "Kagi: FastGPT: Meta" )
    # print( fastgpt[ "meta" ] )
    #
    # du.print_banner( "Kagi: FastGPT: Data" )
    # print( fastgpt[ "data" ] )
    
    du.print_banner( "Kagi: FastGPT: Output" )
    print( fastgpt[ "data" ][ "output" ] )
    
    # du.print_banner( "Kagi: FastGPT: References" )
    # references = fastgpt[ "data" ][ "references" ]
    # for reference in references:
    #     print( reference )
    
    
    