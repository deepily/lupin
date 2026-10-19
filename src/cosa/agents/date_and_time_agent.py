from cosa.agents.agent_base import AgentBase, run_agent_smoke

class DateAndTimeAgent( AgentBase ):
    """
    Agent for handling date and time related queries.
    
    This agent processes questions about current time, time zones, dates,
    and temporal calculations using code generation.
    """
    
    def __init__( self, question: str="", question_gist: str="", last_question_asked: str="", push_counter: int=-1, routing_command: str="agent router go to datetime", user_id: str="ricardo_felipe_ruiz_6bdc", user_email: str="", session_id: str="", debug: bool=False, verbose: bool=False, auto_debug: bool=False, inject_bugs: bool=False ) -> None:
        """
        Initialize date and time agent.
        
        Requires:
            - Date and time routing command exists in config
            - Valid prompt template for date/time queries
            
        Ensures:
            - Initializes with date and time routing
            - Sets up prompt with question
            - Defines expected XML response tags
            
        Raises:
            - KeyError if required config missing
        """
        
        super().__init__( df_path_key=None, question=question, question_gist=question_gist, last_question_asked=last_question_asked, routing_command=routing_command, push_counter=push_counter, user_id=user_id, user_email=user_email, session_id=session_id, debug=debug, verbose=verbose, auto_debug=auto_debug, inject_bugs=inject_bugs )
        
        # The container clock is UTC; the user is not. Name the zone in the prompt so the
        # generated code reads the RIGHT clock — same `app timezone` key the notification
        # queue and the arbiter journal already read. A named zone, never a fixed offset:
        # an offset is wrong for half the year, which is exactly the bug this closes.
        self.timezone = self.config_mgr.get( "app timezone", default="America/New_York" )
        self.prompt   = self.prompt_template.format( question=self.question, timezone=self.timezone )
        self.xml_response_tag_names   = [ "thoughts", "brainstorm", "evaluation", "code", "example", "returns", "explanation" ]
    
        # self.serialize_prompt_to_json = self.config_mgr.get( "agent todo list serialize prompt to json", default=False, return_type="boolean" )
        # self.serialize_code_to_json   = self.config_mgr.get( "agent todo list serialize code to json",   default=False, return_type="boolean" )
    
    def restore_from_serialized_state( self, file_path: str ) -> None:
        """
        Restore date and time agent state from JSON file.
        
        Requires:
            - file_path points to valid JSON file
            
        Ensures:
            - Raises NotImplementedError (not implemented)
            
        Raises:
            - NotImplementedError always
        """
        
        raise NotImplementedError( "DateAndTimeAgent.restore_from_serialized_state() not implemented" )
    
    
def quick_smoke_test():
    """Quick smoke test to validate DateAndTimeAgent functionality."""
    run_agent_smoke( DateAndTimeAgent, "What time is it in Washington DC?", "DateAndTimeAgent", "agent execution" )

if __name__ == "__main__":
    quick_smoke_test()