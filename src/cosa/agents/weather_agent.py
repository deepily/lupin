from typing import Any, Optional

import cosa.utils.util as du

from cosa.agents.agent_base import AgentBase
from cosa.tools.search_lupin_v010 import LupinSearch
from cosa.memory.solution_snapshot import SolutionSnapshot as ss


class WeatherAgent( AgentBase ):
    """
    Agent that answers weather-related questions using web search.
    
    This agent uses the LupinSearch tool to fetch current weather information
    from the web and format it for the user.
    """
    
    def __init__( self, prepend_date_and_time: bool=True, question: str="", question_gist: str="", last_question_asked: str="", push_counter: int=-1, routing_command: str="agent router go to weather", user_id: str="ricardo_felipe_ruiz_6bdc", user_email: str="", session_id: str="", debug: bool=False, verbose: bool=False, auto_debug: bool=False, inject_bugs: bool=False ) -> None:
        """
        Initialize the weather agent.
        
        Requires:
            - LupinSearch tool is available
            - last_question_asked is a weather-related query
            
        Ensures:
            - Prepends current date/time to queries for cache freshness
            - Initializes without DataFrame (uses web search instead)
            - Sets up empty XML response tags (not used)
            
        Raises:
            - ImportError if LupinSearch not available
        """
        
        # Prepend a date and time to force the cache to update on an hourly basis
        if prepend_date_and_time:
            self.reformulated_last_question_asked = f"It's {du.get_current_time( format='%I:00 %p' )} on {du.get_current_date( return_prose=True )}. {last_question_asked}"
        else:
            self.reformulated_last_question_asked = last_question_asked
        
        super().__init__( df_path_key=None, question=question, question_gist=question_gist, last_question_asked=last_question_asked, routing_command=routing_command, push_counter=push_counter, user_id=user_id, user_email=user_email, session_id=session_id, debug=debug, verbose=verbose, auto_debug=auto_debug, inject_bugs=inject_bugs )
        
        self.prompt                   = None
        self.xml_response_tag_names   = []
    
        # self.serialize_prompt_to_json = self.config_mgr.get( "agent_weather_serialize_prompt_to_json", default=False, return_type="boolean" )
        # self.serialize_code_to_json   = self.config_mgr.get( "agent_weather_serialize_code_to_json",   default=False, return_type="boolean" )
    
    def restore_from_serialized_state( self, file_path: str ) -> None:
        """
        Restore agent from serialized state (not implemented).
        
        Requires:
            - file_path is a valid path
            
        Ensures:
            - Raises NotImplementedError
            
        Raises:
            - NotImplementedError always
        """
        
        raise NotImplementedError( "WeatherAgent.restore_from_serialized_state() not implemented" )
    
    def run_code( self, auto_debug: Optional[bool]=None, inject_bugs: Optional[bool]=None ) -> dict[str, Any]:
        """
        Search the web for weather information.
        
        Requires:
            - self.reformulated_last_question_asked is set
            - LupinSearch tool is available
            
        Ensures:
            - Performs web search for weather info
            - Returns code_response_dict with output and return_code
            - Sets self.answer on success
            - Sets self.error on failure
            
        Raises:
            - Catches all exceptions and returns error in response dict
        """
        
        try:
            search   = LupinSearch( query=self.reformulated_last_question_asked, debug=self.debug, verbose=self.verbose)
            search.search_and_summarize_the_web()
            response = search.get_results( scope="summary" )
            
            self.code_response_dict = {
                "output": response.replace( "\n\n", " " ).replace( "\n", " " ),
                "return_code": 0
            }
            self.answer = response
            
        except Exception as e:
            
            self.code_response_dict = {
                "output"     : e,
                "return_code": -1
            }
            self.error = e
        
        return self.code_response_dict
    
    def run_prompt( self, **kwargs ) -> None:
        """
        Run prompt (not implemented for weather agent).
        
        Requires:
            - None
            
        Ensures:
            - Raises NotImplementedError
            
        Raises:
            - NotImplementedError always
        """
        
        raise NotImplementedError( "WeatherAgent.run_prompt() not implemented" )
    
    def is_code_runnable( self ) -> bool:
        """
        Check if agent has runnable code.
        
        Requires:
            - None
            
        Ensures:
            - Always returns True (web search is always runnable)
            
        Raises:
            - None
        """
        
        return True
    
    def is_prompt_executable( self ) -> bool:
        """
        Check if agent has executable prompt.
        
        Requires:
            - None
            
        Ensures:
            - Always returns False (no LLM prompt used)
            
        Raises:
            - None
        """
        
        return False
    
    def do_all( self ) -> str:
        """
        Execute complete weather query workflow.
        
        Requires:
            - self.reformulated_last_question_asked is set
            - LupinSearch tool is available
            
        Ensures:
            - Runs web search for weather data
            - Formats response conversationally
            - Returns final answer
            
        Raises:
            - May propagate exceptions from run_code or run_formatter
        """
        
        # No prompt to run just yet!
        # self.run_prompt()
        self.run_code()
        self.run_formatter()
        
        return self.answer_conversational
    
def quick_smoke_test():
    """Quick smoke test to validate WeatherAgent functionality."""
    import cosa.utils.util as du
    
    du.print_banner( "WeatherAgent Smoke Test", prepend_nl=True )
    
    # Test with a weather question for completion
    question = "What's the temperature in Washington DC?"
    
    try:
        print( f"Testing question: '{question}'" )
        weather_agent = WeatherAgent( 
            question=ss.remove_non_alphanumerics( question ), 
            last_question_asked=question, 
            debug=True, 
            verbose=False, 
            auto_debug=False 
        )
        print( "✓ WeatherAgent created successfully" )
        
        # Run through the complete agent workflow
        print( "Running web search for weather data..." )
        weather_response = weather_agent.do_all()
        print( "✓ Weather search and formatting completed" )
        
        print( f"✓ Final response: {weather_response[:100]}..." if len( weather_response ) > 100 else f"✓ Final response: {weather_response}" )
        
    except Exception as e:
        print( f"✗ Error during weather agent execution: {e}" )
    
    print( "\n✓ WeatherAgent smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()