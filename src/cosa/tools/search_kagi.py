from kagiapi import KagiClient
from requests.exceptions import RequestException

import cosa.utils.util as du

from cosa.utils.bounded_retry import RetryPolicy, retry_call
from cosa.utils.util_stopwatch import Stopwatch
from typing import Optional, Any

# HTTP statuses worth a second attempt: the upstream is momentarily unwell, not
# refusing us on the merits. A 401/403/404 is a standing answer — retrying it
# burns the user's wait and changes nothing — so it surfaces on the first attempt
# with its status line intact for whoever reads the refusal.
RETRYABLE_HTTP_STATUSES = frozenset( { 408, 425, 429, 500, 502, 503, 504 } )


def kagi_error_is_transient( error ) -> bool:
    """
    Decide whether a Kagi failure is the kind another attempt could survive.

    Requires:
        - error is an exception raised by the kagiapi client

    Ensures:
        - returns True for a transport-level failure (no response at all: connection
          reset, DNS, read timeout) — nothing about it says the request was rejected
        - returns True for an HTTP status in RETRYABLE_HTTP_STATUSES
        - returns False for every other status, so an authentication or not-found
          answer reaches the caller immediately instead of after three waits

    Raises:
        - None
    """
    response = getattr( error, "response", None )
    if response is None: return True
    return response.status_code in RETRYABLE_HTTP_STATUSES

class KagiSearch:
    """
    Wrapper for Kagi search API functionality.
    
    Provides FastGPT search and URL summarization capabilities.
    """
    def __init__( self, query: Optional[str]=None, url: Optional[str]=None, debug: bool=False, verbose: bool=False, max_attempts: int=3, retry_backoff: float=1.0 ) -> None:
        """
        Initialize KagiSearch client.

        Requires:
            - Kagi API key available through du.get_api_key()
            - Either query or url provided for search/summarization
            - max_attempts >= 1 and retry_backoff >= 0

        Ensures:
            - Creates KagiClient with API key
            - Sets query or url for operations
            - Records the retry bound that search_fastgpt spends

        Raises:
            - KeyError if API key not found

        Args:
            max_attempts : total FastGPT attempts including the first
            retry_backoff: seconds before the second attempt; doubles thereafter
        """

        self.debug         = debug
        self.verbose       = verbose
        self.query         = query
        self.url           = url
        self.max_attempts  = max_attempts
        self.retry_backoff = retry_backoff
        self._key          = du.get_api_key( "kagi" )
        self._kagi         = KagiClient( du.get_api_key( "kagi" ) )
        
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
        Perform FastGPT search with query, retrying a transient upstream failure.

        WHY THE RETRY (row 3598c1d3). This was a bare single call. kagiapi ends
        fastgpt() with response.raise_for_status(), so one momentary blip anywhere in
        Kagi's stack became a user-visible weather failure with certainty — nothing
        stood between them. On 2026-08-19 at 18:54 EDT it did exactly that, and what
        the status was is permanently unknown because the exception died with it.

        Requires:
            - self.query is set and non-empty
            - Kagi client is initialized

        Ensures:
            - Returns dict with 'meta' and 'data' sections
            - 'data' contains 'output' with search results
            - retries a TRANSIENT failure (transport error, or 408/425/429/5xx) up to
              self.max_attempts times with exponential backoff
            - raises a non-transient answer (401, 403, 404 ...) on the FIRST attempt —
              no waiting for a verdict that will not change
            - re-raises the LAST exception UNCHANGED when every attempt is spent. The
              weather agent's refusal is asserted to name its own status code
              (src/tests/unit/test_weather_agent_search_failure.py); a retry that
              summarised the final failure would silently revert that and make the
              next occurrence undiagnosable again
            - Prints timing information

        Raises:
            - KagiAPI / requests errors propagated, unchanged, after the last attempt
        """
        timer  = Stopwatch( f"Kagi FastGPT query: [{self.query}]" )
        policy = RetryPolicy(
            max_attempts    = self.max_attempts,
            initial_backoff = self.retry_backoff,
            max_backoff     = self.retry_backoff * 4,
            retry_on        = ( RequestException, ),
            retry_if_error  = kagi_error_is_transient
        )
        response = retry_call( lambda: self._kagi.fastgpt( query=self.query ),
                               policy=policy, on_retry=self._announce_retry )
        timer.print( "Done!", use_millis=True )

        return response

    def _announce_retry( self, attempt: int, error: Exception, delay: float ) -> None:
        """
        Print one line per retry so a recovered blip leaves a trace.

        Requires:
            - attempt is the 1-based number of the attempt that just failed

        Ensures:
            - prints the attempt number, the failure and the wait — a search that
              quietly succeeded on its second try would otherwise be indistinguishable
              from one that never had trouble, and the next investigation would start
              with no record that Kagi wobbled at all

        Raises:
            - None
        """
        print( f"[KagiSearch] FastGPT attempt {attempt}/{self.max_attempts} failed "
               f"({type( error ).__name__}: {error}) — retrying in {delay:.1f}s" )
    
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
    
    
    