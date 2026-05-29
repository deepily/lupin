import json
from typing import Any

from cosa.agents.agent_base import AgentBase


class CalendaringAgent( AgentBase ):
    """
    Agent for handling calendar-related queries and operations.
    
    This agent processes questions about events, dates, and scheduling
    using a DataFrame of calendar event data.
    """
    
    def __init__( self, question: str="", last_question_asked: str="", question_gist: str="", routing_command: str="agent router go to calendar", push_counter: int=-1, user_id: str="ricardo_felipe_ruiz_6bdc", user_email: str="", session_id: str="", debug: bool=False, verbose: bool=False, auto_debug: bool=False, inject_bugs: bool=False ) -> None:
        """
        Initialize calendaring agent with events data.
        
        Requires:
            - df_path_key 'path to events df wo root' exists in config
            - Events CSV file contains 'event_type' column
            - Calendar routing command exists in config
            
        Ensures:
            - Loads events DataFrame from configured path
            - Initializes prompt with calendar metadata
            - Sets up XML response tags for calendar operations
            
        Raises:
            - FileNotFoundError if events CSV file missing
            - KeyError if required config keys missing
        """
        
        super().__init__( df_path_key="path to events df wo root", question=question, question_gist=question_gist, last_question_asked=last_question_asked, routing_command=routing_command, push_counter=push_counter, user_id=user_id, user_email=user_email, session_id=session_id, debug=debug, verbose=verbose, auto_debug=auto_debug, inject_bugs=inject_bugs )

        self.prompt = self._get_prompt()
        
        self.xml_response_tag_names = [ "question", "thoughts", "code", "example", "returns", "explanation" ]
        
    def _get_prompt( self ) -> str:
        """
        Generate prompt with calendar data metadata.
        
        Requires:
            - self.last_question_asked is set
            - Events DataFrame is loaded
            - self.prompt_template exists
            
        Ensures:
            - Returns formatted prompt with question and metadata
            - Includes column names, event types, and sample data
            
        Raises:
            - None
        """
        
        column_names, unique_event_types, head = self._get_metadata()
        
        return self.prompt_template.format( question=self.last_question_asked, column_names=column_names, unique_event_types=unique_event_types, head=head )
    
    def _get_metadata( self ) -> tuple[list[str], list[str], str]:
        """
        Extract metadata from events DataFrame.
        
        Requires:
            - self.df is loaded with events data
            - DataFrame has 'event_type' column
            
        Ensures:
            - Returns tuple of (column_names, unique_event_types, xml_sample)
            - XML sample includes first 2 and last 2 rows
            - XML is formatted with 'events' root tag
            
        Raises:
            - AttributeError if DataFrame not properly initialized
        """
        
        column_names = self.df.columns.tolist()
        unique_event_types = self.df[ "event_type" ].unique().tolist()
        
        head = self.df.head( 2 ).to_xml( index=False )
        head = head + self.df.tail( 2 ).to_xml( index=False )
        head = head.replace( "data>", "events>" ).replace( "<?xml version='1.0' encoding='utf-8'?>", "" )
        
        return column_names, unique_event_types, head
        
    def restore_from_serialized_state( self, file_path: str ) -> None:
        """
        Restore calendaring agent state from JSON file.
        
        Requires:
            - file_path points to valid JSON file
            
        Ensures:
            - Raises NotImplementedError (not implemented)
            
        Raises:
            - NotImplementedError always
        """
        
        raise NotImplementedError( f"CalendaringAgent.restore_from_serialized_state( file_path={file_path} ) not implemented" )
    
def quick_smoke_test():
    """Quick smoke test to validate CalendaringAgent functionality."""
    import cosa.utils.util as du
    
    du.print_banner( "CalendaringAgent Smoke Test", prepend_nl=True )
    
    # Test with a single question for completion
    question = "What events do I have this week?"
    
    try:
        print( f"Testing question: '{question}'" )
        cal_agent = CalendaringAgent( 
            question=question,
            last_question_asked=question,
            question_gist=question,
            debug=True,
            verbose=False,
            auto_debug=False
        )
        print( "✓ CalendaringAgent created successfully" )
        
        # Run through the complete agent workflow
        print( "Running prompt..." )
        cal_agent.run_prompt()
        print( "✓ Prompt execution completed" )
        
        if cal_agent.is_code_runnable():
            print( "Running code..." )
            cal_agent.run_code()
            print( "✓ Code execution completed" )
            
            print( "Running formatter..." )
            cal_agent.run_formatter()
            print( "✓ Formatter execution completed" )
            
            print( f"✓ Final response: {cal_agent.answer_conversational}" )
        else:
            print( "⚠ No runnable code generated" )
        
    except Exception as e:
        print( f"✗ Error during agent execution: {e}" )
    
    print( "\n✓ CalendaringAgent smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()