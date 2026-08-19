import os
import random
import re
import pandas as pd
from xmlschema import XMLSchema
from typing import Optional, Any

import cosa.utils.util as du
import cosa.utils.util_xml as dux
from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.training.xml_prompt_generator import XmlPromptGenerator
from cosa.training.xml_response_validator import XmlResponseValidator

class XmlCoordinator:
    """
    Coordinates prompt generation and response validation for XML-based fine-tuning.
    
    This class combines the functionality of XmlPromptGenerator and XmlResponseValidator,
    providing a unified interface for working with XML-based prompts and responses.
    
    Responsibilities:
    - Generate and format prompts using various templates
    - Run validation on model responses
    - Calculate and report performance metrics
    - Generate training/testing data splits
    """
    
    def __init__( self, path_prefix: str=du.get_project_root(), tgi_url: str="http://172.17.0.4:3000", debug: bool=False, verbose: bool=False, silent: bool=False, init_prompt_templates: bool=True ) -> None:
        self.debug                = debug
        self.verbose              = verbose
        self.silent               = silent
        self.path_prefix          = path_prefix
        self.tgi_url              = tgi_url
        
        # Initialize the component classes
        self.prompt_generator     = XmlPromptGenerator( path_prefix=path_prefix, debug=debug, verbose=verbose, silent=silent )
        self.response_validator   = XmlResponseValidator( debug=debug, verbose=verbose )
        
        # Counters and state
        self._call_counter        = 0
        self.last_ms_per_item     = 0.0
        
        # For backward compatibility - provide direct access to key properties
        if init_prompt_templates:
            self.interjections    = self.prompt_generator.interjections
            self.salutations      = self.prompt_generator.salutations
            self._xml_schema      = self.response_validator._xml_schema
    
    # Public methods from XmlPromptGenerator
    def get_interjections( self, requested_length: Optional[int]=None ) -> list:
        """
        Gets a list of interjections for more natural language generation.
        
        Requires:
            - requested_length is None or positive integer
            
        Ensures:
            - Returns list of interjection phrases
            - Length matches requested_length if specified
        """
        return self.prompt_generator.get_interjections( requested_length )
    
    def get_salutations( self, requested_length: int=500 ) -> list:
        """
        Gets randomized salutations with computer names.
        
        Requires:
            - requested_length is positive integer
            
        Ensures:
            - Returns list of formatted salutations
            - Length matches requested_length
        """
        return self.prompt_generator.get_salutations( requested_length )
    
    def insert_interjection( self, text: str, interjections: Optional[list]=None ) -> tuple[str, str]:
        """
        Inserts a random interjection into the provided text.
        
        Requires:
            - text is a non-empty string
            - interjections is None or list of strings
            
        Ensures:
            - Returns tuple with inserted interjection and modified text
            - Modified text contains the interjection
        """
        return self.prompt_generator.insert_interjection( text, interjections )
    
    def prepend_salutation( self, text: str, salutations: Optional[list]=None ) -> tuple[str, str]:
        """
        Prepends a random salutation to the given text.
        
        Requires:
            - text is a non-empty string
            - salutations is None or list of strings
            
        Ensures:
            - Returns tuple with chosen salutation and modified text
            - Modified text starts with the salutation
        """
        return self.prompt_generator.prepend_salutation( text, salutations )
    
    def get_prompt_template( self, name: str ) -> str:
        """
        Returns a formatted prompt template for the specified command type.
        
        Requires:
            - name is a valid command type string
            
        Ensures:
            - Returns formatted prompt template
            - Template corresponds to specified command type
            
        Raises:
            - ValueError if unknown template name
        """
        return self.prompt_generator.get_prompt_template( name )
    
    def serialize_prompt( self, prompt: str, prompt_path: str ) -> None:
        """
        Writes a prompt to a file.
        
        Requires:
            - prompt is a non-empty string
            - prompt_path is a valid file path
            
        Ensures:
            - Prompt written to specified file
            - File exists after operation
        """
        self.prompt_generator.serialize_prompt( prompt, prompt_path )
    
    def serialize_prompts( self, prompt_path_prefix: str ) -> None:
        """
        Writes all prompt templates to files.
        
        Requires:
            - prompt_path_prefix is a valid directory path
            
        Ensures:
            - All prompt templates written to files
            - Files created in specified directory
        """
        self.prompt_generator.serialize_prompts( prompt_path_prefix )
    
    # Public methods from XmlResponseValidator
    def is_valid_xml( self, xml_str: str ) -> bool:
        """
        Checks if XML is valid according to schema.
        
        Requires:
            - xml_str is a string
            
        Ensures:
            - Returns True if valid XML
            - Returns False otherwise
        """
        return self.response_validator.is_valid_xml( xml_str )
    
    def contains_valid_xml_tag( self, xml_str: str, tag_name: str ) -> bool:
        """
        Checks if XML contains a specific tag.
        
        Requires:
            - xml_str is a string
            - tag_name is a non-empty string
            
        Ensures:
            - Returns True if tag exists
            - Returns False otherwise
        """
        return self.response_validator.contains_valid_xml_tag( xml_str, tag_name )
    
    def is_response_exact_match( self, response: str, answer: str ) -> bool:
        """
        Checks if response exactly matches expected answer.
        
        Requires:
            - response is a string
            - answer is a string
            
        Ensures:
            - Returns True if exact match
            - Returns False otherwise
        """
        return self.response_validator.is_response_exact_match( response, answer )
    
    def contains_correct_response_values( self, response: str, answer: str ) -> bool:
        """
        Check if the most common formatting error (```xml) is hiding a correct response.
        
        Requires:
            - response is a string
            - answer is a string
            
        Ensures:
            - Returns True if response contains correct values
            - Returns False otherwise
        """
        return self.response_validator.contains_correct_response_values( response, answer )
    
    def tag_values_are_equal( self, response: str, answer: str, tag_name: str="command" ) -> bool:
        """
        Checks if a specific tag's value in response matches the value in answer.
        
        Requires:
            - response is a string
            - answer is a string
            - tag_name is a non-empty string
            
        Ensures:
            - Returns True if tag values match
            - Returns False otherwise
        """
        return self.response_validator.tag_values_are_equal( response, answer, tag_name )
    
    # Shared methods for generating and validating prompts
    def reset_call_counter( self ) -> None:
        """
        Resets the internal call counter to zero.
        
        Requires:
            - None
            
        Ensures:
            - Call counter set to zero
        """
        self._call_counter = 0
    
    def build_compound_vox_cmd_training_prompts( self, sample_size_per_command: int=2000 ) -> pd.DataFrame:
        """
        Builds training prompts for compound voice commands.

        Requires:
            - sample_size_per_command is positive integer

        Ensures:
            - Generates prompts for all compound commands
            - Returns DataFrame with prompts
            - DataFrame contains expected columns
        """
        instructions, inputs, outputs, prompts, commands = self._get_5_empty_lists()

        # For each browser command, load the corresponding file and generate prompts
        for compound_command in self.prompt_generator.vox_cmd_compound_commands.keys():

            du.print_banner( f"Building prompts for compound VOX command [{compound_command}]", prepend_nl=True, end="\n" )
            counter = 1
            # The first 100 lines are properly spelled
            raw_lines = du.get_file_as_list( self.path_prefix + self.prompt_generator.vox_cmd_compound_commands[ compound_command ], clean=True, skip_empty=True, skip_comments=True )[ 0:100 ]

            # Determine which kind of compound synthetically created lines we need to build prompts for
            if compound_command.startswith( "search " ):
                arguments   = self.prompt_generator.get_search_terms( len( raw_lines ) )
                placeholder = "SEARCH_TERMS"
            elif compound_command.startswith( "go to " ):
                arguments   = self.prompt_generator.get_domain_names( len( raw_lines ) )
                placeholder = "DOMAIN_NAME"
            else:
                raise Exception( f"Unknown voice command [{compound_command}]" )

            for raw_line in raw_lines:

                for args in arguments:

                    voice_command = raw_line.replace( placeholder, args )

                    instruction = self.prompt_generator.vox_cmd_instruction_template.format( command_choices=self.prompt_generator.vox_cmd_commands )
                    human_says  = self.prompt_generator.common_human_says_template.format( voice_command=voice_command )
                    input_text  = self.prompt_generator.common_input_template.format( human_says=human_says, response_format=self.prompt_generator.common_response_format )
                    output      = self.prompt_generator.common_output_template.format( command=compound_command, args=args )
                    prompt      = self.prompt_generator._get_prompt_instruction_format( instruction, input_text )

                    instructions.append( instruction )
                    inputs.append( input_text )
                    outputs.append( output )
                    prompts.append( prompt )
                    commands.append( compound_command )

                    self._do_conditional_print( counter, voice_command )
                    counter += 1

            print()

        compound_qna_df = pd.DataFrame( {"command": commands, "instruction": instructions, "input": inputs, "output": outputs, "prompt": prompts} )
        compound_qna_df = self._prune_duplicates_and_sample( compound_qna_df, sample_size=( sample_size_per_command * len( self.prompt_generator.vox_cmd_compound_commands ) ), sample_size_per_command=sample_size_per_command )

        return compound_qna_df
    
    def build_simple_vox_cmd_training_prompts( self, sample_size_per_command: int=400 ) -> pd.DataFrame:
        """
        Builds training prompts for simple voice commands.

        Requires:
            - sample_size_per_command is positive integer

        Ensures:
            - Generates prompts for all simple commands
            - Returns DataFrame with prompts
            - DataFrame contains expected columns
        """
        instructions, inputs, outputs, prompts, commands = self._get_5_empty_lists()

        for simple_command in self.prompt_generator.vox_cmd_simple_commands.keys():

            du.print_banner( f"Building prompts for simple VOX command [{simple_command}]", prepend_nl=True, end="\n" )
            counter = 1

            raw_lines = du.get_file_as_list( self.path_prefix + self.prompt_generator.vox_cmd_simple_commands[ simple_command ], clean=True, skip_empty=True, skip_comments=True )

            for raw_line in raw_lines:

                _, raw_line = self.prompt_generator.insert_interjection( raw_line, self.prompt_generator.interjections )
                _, raw_line = self.prompt_generator.prepend_salutation( raw_line, self.prompt_generator.salutations )

                instruction = self.prompt_generator.vox_cmd_instruction_template.format( command_choices=self.prompt_generator.vox_cmd_commands )
                human_says  = self.prompt_generator.common_human_says_template.format( voice_command=raw_line )
                input_text  = self.prompt_generator.common_input_template.format( human_says=human_says, response_format=self.prompt_generator.common_response_format )
                output      = self.prompt_generator.common_output_template.format( command=simple_command, args="" )
                prompt      = self.prompt_generator._get_prompt_instruction_format( instruction, input_text )

                instructions.append( instruction )
                inputs.append( input_text )
                outputs.append( output )
                prompts.append( prompt )
                commands.append( simple_command )

                self._do_conditional_print( counter, raw_line )
                counter += 1

        simple_command_qna_df = pd.DataFrame( {"command": commands, "instruction": instructions, "input": inputs, "output": outputs, "prompt": prompts} )
        simple_command_qna_df = self._prune_duplicates_and_sample( simple_command_qna_df, sample_size=( sample_size_per_command * len( self.prompt_generator.vox_cmd_simple_commands ) ), sample_size_per_command=sample_size_per_command )

        return simple_command_qna_df
    
    def build_compound_agent_router_training_prompts( self, sample_size_per_command: int=2000 ) -> pd.DataFrame:
        """
        Builds training prompts for compound agent router commands.

        Requires:
            - sample_size_per_command is positive integer

        Ensures:
            - Generates prompts for all compound router commands
            - Returns DataFrame with prompts
            - DataFrame contains expected columns
        """
        instructions, inputs, outputs, prompts, commands = self._get_5_empty_lists()

        # For each browser command, load the corresponding file and generate prompts
        # The REGISTRY decides which commands get rows and in what order (row 95924f2d,
        # step 4); the JSON only says where each command's phrasings live. The loop
        # variable is therefore a registry string, so the row's answer below is too.
        for compound_command in self.prompt_generator.registry_ordered_training_commands( self.prompt_generator.agent_router_compound_commands ):

            du.print_banner( f"Building prompts for compound AGENT ROUTER command [{compound_command}]", prepend_nl=True, end="\n" )
            counter = 1

            raw_lines = du.get_file_as_list( self.path_prefix + self.prompt_generator.agent_router_compound_commands[ compound_command ], clean=True, skip_empty=True, skip_comments=True, randomize=True )[ 0:100 ]

            if compound_command in [ "agent router go to weather", "agent router go to datetime" ]:
                arguments   = self.prompt_generator.get_cities_and_countries( len( raw_lines ) )
                placeholder = "GEOGRAPHIC_LOCATION"
            elif compound_command == "agent router go to receptionist":
                arguments   = self._get_receptionist_titles( len( raw_lines ) )
                placeholder = "RECEPTIONIST_TITLE"
            elif compound_command == "agent router go to calendar":
                arguments   = self._get_events_values( len( raw_lines ) )
                placeholder = ""
            else:
                raise Exception( f"Unknown voice command [{compound_command}]" )

            for raw_line in raw_lines:

                for args in arguments:

                    if compound_command == "agent router go to calendar":
                        voice_command = raw_line.replace( "PLACE", "" )
                        for key in args.keys():
                            voice_command = voice_command.replace( key, args[ key ] )
                        # Reset args to an empty string, NOT a dictionary
                        args = ""
                    else:
                        voice_command = raw_line.replace( placeholder, args )

                    _, voice_command = self.prompt_generator.insert_interjection( voice_command, self.prompt_generator.interjections )
                    _, voice_command = self.prompt_generator.prepend_salutation( voice_command, self.prompt_generator.salutations )

                    instruction   = self.prompt_generator.agent_router_instruction_template.format( command_choices=self.prompt_generator.agent_router_commands )
                    human_says    = self.prompt_generator.common_human_says_template.format( voice_command=voice_command )
                    input_text    = self.prompt_generator.common_input_template.format( human_says=human_says, response_format=self.prompt_generator.common_response_format )
                    output        = self.prompt_generator.common_output_template.format( command=compound_command, args=args )
                    prompt        = self.prompt_generator._get_prompt_instruction_format( instruction, input_text )

                    instructions.append( instruction )
                    inputs.append( input_text )
                    outputs.append( output )
                    prompts.append( prompt )
                    commands.append( compound_command )

                    self._do_conditional_print( counter, voice_command )
                    counter += 1

            print()

        compound_agent_router_qna_df = pd.DataFrame( {"command": commands, "instruction": instructions, "input": inputs, "output": outputs, "prompt": prompts} )
        compound_agent_router_qna_df = self._prune_duplicates_and_sample( compound_agent_router_qna_df, sample_size=( sample_size_per_command * len( self.prompt_generator.agent_router_compound_commands ) ), sample_size_per_command=sample_size_per_command )

        return compound_agent_router_qna_df
    
    def build_compound_function_mapping_training_prompts( self, sample_size_per_command: int=2000, analyze_bigrams: bool=False, max_questions: int=2 ) -> Optional[pd.DataFrame]:
        """
        Builds training prompts for function mapping.

        Requires:
            - sample_size_per_command is positive integer
            - max_questions is positive integer

        Ensures:
            - Processes function mapping commands
            - Generates QnR pairs for .txt files
            - Returns None in current implementation
        """
        instructions, inputs, outputs, prompts, commands = self._get_5_empty_lists()
        
        # For each function mapping entry, load the corresponding file and generate prompts
        for routing_key in self.prompt_generator.agent_function_mapping_compound_commands.keys():
            
            du.print_banner( f"Building prompts for compound FUNCTION MAPPING [{routing_key}]", prepend_nl=True, end="\n" )
            
            path     = self.path_prefix + self.prompt_generator.agent_function_mapping_compound_commands[ routing_key ]
            boundary = "<!-- QnR Boundary -->"
            if path.endswith( ".txt" ):
                
                print( f"Loading RAW question data from [{path}]..." )
                raw_lines = du.get_file_as_list( path, clean=True, skip_empty=True, skip_comments=True, randomize=True )
                if analyze_bigrams: self._analyze_bigrams( raw_lines, "DEFAULT_LOCATION" )
                
                locations = self.prompt_generator.get_cities_and_countries( requested_length=None )
                placeholders_and_values = {"DEFAULT_LOCATION": locations}
                
                questions = self._build_function_mapping_questions( raw_lines, placeholders_and_values )
                responses = self._generate_function_mapping_response_objects( questions, max_questions=max_questions )
                count     = len( responses )
                counter   = 0
                
                # Write the responses to an XML file of the same name
                output_path = path.replace( ".txt", ".xml" )
                with open( output_path, "w", encoding="utf-8" ) as f:
                    
                    f.write( "<qnrs>\n" )
                    for response in responses:
                        if self.debug and self.verbose:
                            print( f"Writing '{response[ 'last_question_asked' ]}'..." )
                        elif self.debug:
                            print( ".", end="" )
                        f.write( "<qnr>\n" )
                        f.write( "<question>" + response[ "last_question_asked" ] + "</question>\n" )
                        f.write( response[ "xml_response" ] + "\n" )
                        f.write( "</qnr>\n" )
                        counter += 1
                        # Don't write a boundary after the last question
                        if counter < count: f.write( f"{boundary}\n" )
                    f.write( "</qnrs>\n" )
                
                if self.debug and not self.verbose: print()
                print( f"Saved {counter} QnRs to [{output_path}]" )
                
            elif path.endswith( ".xml" ):
                
                msg = f"Loading XML QnR data from [{path}]..."
                print( msg )
                xml_data = du.get_file_as_string( path )
                qnrs     = xml_data.split( boundary )
                msg      = f"{msg} Done! Loaded {len( qnrs )} QnR pairs."
                print( msg )
                
            else:
                
                extension = path.split( "." )[ -1 ]
                raise Exception( f"Unknown function mapping file type [*.{extension}] for routing_key [{routing_key}]" )

        return None
    
    def _analyze_bigrams( self, raw_lines: list, placeholder: str ) -> None:
        """
        Analyzes bigrams in raw lines.
        
        Requires:
            - raw_lines is list of strings
            - placeholder is non-empty string
            
        Ensures:
            - Prints bigram analysis
            - Counts bigram occurrences
        """
        du.print_banner( f"Analyzing bigrams for placeholder [{placeholder}]...", prepend_nl=True )
        
        # Do a quick and dirty search and summary for DEFAULT_LOCATION
        bigrams = []
        
        for line in raw_lines:
            
            found = False
            words = line.split( " " )
            
            for idx, word in enumerate( words ):
                if placeholder in word and idx >= 1:
                    bigrams.append( words[ idx - 1 ] + " " + words[ idx ] )
                    found = True
                    break
                    
            if not found:
                bigrams.append( f"No placeholder '{placeholder}' provided" )
                
        # Count the bigrams
        from collections import Counter
        bigram_counter = Counter( bigrams )
        # Print out the most common bigrams sorted descending
        for bigram, count in bigram_counter.most_common():
            print( f"{bigram}: {count}" )
    
    def _build_function_mapping_questions( self, raw_lines: list, placeholders_and_values: dict ) -> list:
        """
        Builds function mapping questions.
        
        Requires:
            - raw_lines is list of strings
            - placeholders_and_values is dictionary
            
        Ensures:
            - Substitutes placeholders with values
            - Adds interjections and salutations
            - Returns list of questions
        """
        du.print_banner( "Building function mapping questions...", prepend_nl=True)
        lines   = []
        for line in raw_lines:
            
            # Iterate over placeholders and substitute random values for them
            for placeholder, values in placeholders_and_values.items():
                line = line.replace( placeholder, random.choice( values ) )
            
            # Insert interjections and salutations
            _, line = self.prompt_generator.insert_interjection( line, self.prompt_generator.interjections )
            _, line = self.prompt_generator.prepend_salutation( line, self.prompt_generator.salutations )
            lines.append( line )
            if self.debug:print( line )
        
        return lines
    
    def _generate_function_mapping_response_objects( self, questions: list, max_questions: Optional[int]=None ) -> list:
        """
        Generates function mapping response objects.
        
        Requires:
            - questions is list of strings
            - max_questions is None or positive integer
            
        Ensures:
            - Generates response objects for questions
            - Returns list of response dictionaries
            - Processes up to max_questions if specified
        """
        from cosa.utils.util_stopwatch import Stopwatch
        
        # If max_questions is None, the slice will be all the questions
        questions = questions[ 0:max_questions ]
        responses = []
        counter   = 0
        
        timer = Stopwatch( msg=f"Generating function mapping for {len( questions )} questions..." )
        for question in questions:
            
            counter += 1
            from cosa.agents.v000.function_mapping_search import FunctionMappingSearch
            mapper = FunctionMappingSearch( question=question, last_question_asked=question, debug=self.debug, verbose=self.verbose )
            du.print_banner( f"Question {counter} of {len( questions )}: {question}", end="\n", prepend_nl=True )
            prompt_response_dict = mapper.run_prompt( include_raw_response=True )
            
            responses.append( prompt_response_dict )
            
            # Print out some ~progress stats
            delta_ms            = timer.get_delta_ms()
            time_elapsed        = int( delta_ms / 1000 )
            ms_per_question     = int( round( delta_ms / counter, 0 ) )
            time_per_question   = int( ms_per_question / 1000 )
            questions_remaining = len( questions ) - counter
            seconds_remaining   = int( ms_per_question * questions_remaining / 1000 )
            
            print( f"Time elapsed {time_elapsed:,} seconds. Average time per question: {time_per_question:,} seconds. {questions_remaining} questions remaining, ETA: {seconds_remaining:,} seconds...", end="\n\n" )
        
        timer.print( msg="Done!", use_millis=False )
        print( f"Average time per question: {round( timer.get_delta_ms() / len( questions ), 0 ):,} ms" )
        
        return responses
    
    def build_simple_agent_router_training_prompts( self, sample_size_per_command: int=400, augmentation_config: dict=None ) -> pd.DataFrame:
        """
        Builds training prompts for simple agent router commands.

        Requires:
            - sample_size_per_command is positive integer
            - augmentation_config is None or dict mapping command names to {"factor": int}

        Ensures:
            - Generates prompts for all simple router commands
            - Each factor pass applies fresh random interjection/salutation selections
            - Returns DataFrame with prompts
            - DataFrame contains expected columns
        """
        instructions, inputs, outputs, prompts, commands = self._get_5_empty_lists()

        if augmentation_config is None:
            augmentation_config = {}

        default_factor = 1

        # Registry-ordered, registry-labelled — see the compound builder (row 95924f2d).
        for simple_command in self.prompt_generator.registry_ordered_training_commands( self.prompt_generator.agent_router_simple_commands ):

            factor = augmentation_config.get( simple_command, {} ).get( "factor", default_factor )

            du.print_banner( f"Building prompts for simple AGENT ROUTER command [{simple_command}] (augmentation factor: {factor}x)", prepend_nl=True, end="\n" )
            counter = 1

            raw_lines = du.get_file_as_list( self.path_prefix + self.prompt_generator.agent_router_simple_commands[ simple_command ], clean=True, skip_empty=True, skip_comments=True )

            for raw_line in raw_lines:

                for aug_idx in range( factor ):

                    augmented_line = raw_line
                    _, augmented_line = self.prompt_generator.insert_interjection( augmented_line, self.prompt_generator.interjections )
                    _, augmented_line = self.prompt_generator.prepend_salutation( augmented_line, self.prompt_generator.salutations )

                    # 14ba1437: use the AGENT-ROUTER wrapper, matching the sibling builders at :387 (compound)
                    # and :805 (agentic). This site trained 5 simple commands (todo/math/calculator/automatic/none)
                    # under the BROWSER wrapper ("a browser on your computer would understand", <browser-commands>),
                    # a train/serve mismatch against the served agent-routing prompt.
                    instruction = self.prompt_generator.agent_router_instruction_template.format( command_choices=self.prompt_generator.agent_router_commands )
                    human_says  = self.prompt_generator.common_human_says_template.format( voice_command=augmented_line )
                    input_text  = self.prompt_generator.common_input_template.format( human_says=human_says, response_format=self.prompt_generator.common_response_format )
                    output      = self.prompt_generator.common_output_template.format( command=simple_command, args="" )
                    prompt      = self.prompt_generator._get_prompt_instruction_format( instruction, input_text )

                    instructions.append( instruction )
                    inputs.append( input_text )
                    outputs.append( output )
                    prompts.append( prompt )
                    commands.append( simple_command )

                    self._do_conditional_print( counter, augmented_line )
                    counter += 1

        simple_agent_router_qna_df = pd.DataFrame( {"command": commands, "instruction": instructions, "input": inputs, "output": outputs, "prompt": prompts} )
        simple_agent_router_qna_df = self._prune_duplicates_and_sample( simple_agent_router_qna_df, sample_size=( sample_size_per_command * len( self.prompt_generator.agent_router_simple_commands ) ), sample_size_per_command=sample_size_per_command )

        return simple_agent_router_qna_df

    def _load_agentic_commands_config( self ):
        """
        Load agentic job command config from external JSON file.

        Requires:
            - JSON file exists at /src/conf/training/agent-router-agentic-commands.json

        Ensures:
            - Returns dict mapping command names to config dicts with template_file, placeholders, args_key
        """
        import json
        config_path = self.path_prefix + "/src/conf/training/agent-router-agentic-commands.json"
        with open( config_path, "r" ) as f:
            return json.load( f )

    # The single source of truth for which placeholder sources a config entry may
    # name. test_swe_team_training_data.py validates the config against THIS —
    # it used to keep its own hardcoded copy, which went stale the moment a
    # getter was added and failed the config rather than the drift.
    PLACEHOLDER_GETTER_NAMES = (
        "research_topics", "document_paths", "claude_code_tasks", "swe_team_tasks",
        "test_types", "tfe_plan_paths", "audience_levels", "audience_contexts",
        "renderer_names", "duration_minutes",
    )

    def _placeholder_getter_dispatch( self ):
        """
        Maps a config `source` name to the getter that supplies its values.

        Requires:
            - self.prompt_generator is initialized

        Ensures:
            - Returns a dict whose keys are exactly PLACEHOLDER_GETTER_NAMES
        """
        return {
            "research_topics"   : self.prompt_generator.get_research_topics,
            "document_paths"    : self.prompt_generator.get_document_paths,
            "claude_code_tasks" : self.prompt_generator.get_claude_code_tasks,
            "swe_team_tasks"    : self.prompt_generator.get_swe_team_tasks,
            "test_types"        : self.prompt_generator.get_test_types,
            "tfe_plan_paths"    : self.prompt_generator.get_tfe_plan_paths,
            "audience_levels"   : self.prompt_generator.get_audience_levels,
            "audience_contexts" : self.prompt_generator.get_audience_contexts,
            "renderer_names"    : self.prompt_generator.get_renderer_names,
            "duration_minutes"  : self.prompt_generator.get_duration_minutes,
        }

    def _get_placeholder_values_by_name( self, getter_name, requested_length=None ):
        """
        Dispatch placeholder getter by name string from config.

        Requires:
            - getter_name is a string matching a known getter

        Ensures:
            - Returns list of placeholder values

        Raises:
            - ValueError if getter_name is unknown
        """
        dispatch = self._placeholder_getter_dispatch()
        getter = dispatch.get( getter_name )
        if getter is None:
            raise ValueError( f"Unknown placeholder getter: '{getter_name}'. Available: {list( dispatch.keys() )}" )
        return getter( requested_length=requested_length )

    def build_agentic_job_training_prompts( self, sample_size_per_command: int=100 ) -> pd.DataFrame:
        """
        Builds training prompts for agentic job commands from external config.

        Requires:
            - sample_size_per_command is positive integer
            - External config JSON exists at /src/conf/training/agent-router-agentic-commands.json

        Ensures:
            - Generates prompts for all agentic job commands defined in config
            - Returns DataFrame with prompts
            - DataFrame contains expected columns (command, instruction, input, output, prompt)
        """
        instructions, inputs, outputs, prompts, commands = self._get_5_empty_lists()

        # Load agentic job commands from external config (single source of truth)
        agentic_commands = self._load_agentic_commands_config()

        # Use the shared agent router instruction template with ALL agent router commands
        # This integrates agentic jobs into the unified training pipeline
        # Registry-ordered, registry-labelled — see the compound builder (row 95924f2d).
        for command_name in self.prompt_generator.registry_ordered_training_commands( agentic_commands ):

            config = agentic_commands[ command_name ]

            du.print_banner( f"Building prompts for AGENTIC JOB command [{command_name}]", prepend_nl=True, end="\n" )
            counter = 1

            # Normalize placeholder specs: support legacy string form AND dict form with per-placeholder args_key
            #   legacy:   "DOCUMENT_PATH" : "document_paths"              → uses top-level config.args_key
            #   new:      "DURATION_MINUTES" : { "source": "duration_minutes", "args_key": "target_duration_minutes" }
            default_args_key  = config.get( "args_key", "" )
            placeholder_specs = {}
            for ph, spec in config[ "placeholders" ].items():
                if isinstance( spec, str ):
                    placeholder_specs[ ph ] = { "source": spec, "args_key": default_args_key }
                else:
                    placeholder_specs[ ph ] = { "source": spec[ "source" ], "args_key": spec.get( "args_key", default_args_key ) }

            # Get placeholder values via config-driven dispatch
            placeholder_values = {}
            for ph, spec in placeholder_specs.items():
                placeholder_values[ ph ] = self._get_placeholder_values_by_name( spec[ "source" ] )

            # Load templates from external file
            template_path    = self.path_prefix + config[ "template_file" ]
            template_patterns = du.get_file_as_list( template_path, clean=True, skip_empty=True, skip_comments=True )
            if self.debug: print( f"  Loaded [{len( template_patterns )}] templates from [{config[ 'template_file' ]}]" )

            conditional_args              = config.get( "conditional_args", {} )
            multi_placeholder_sample_size = 100  # per-template budget when >1 placeholder present

            # Build word-boundary regex for each placeholder so AUDIENCE doesn't match inside AUDIENCE_CONTEXT
            placeholder_patterns = { ph: re.compile( rf'\b{re.escape( ph )}\b' ) for ph in placeholder_specs }

            # Generate prompts from templates — multi-placeholder aware
            for template in template_patterns:

                # Determine which placeholders are actually present in THIS template line (word-boundary match)
                present_placeholders = [ ph for ph in placeholder_specs if placeholder_patterns[ ph ].search( template ) ]

                # Build list of (voice_command, args_value) pairs to emit for this template
                emission_pairs = []
                if not present_placeholders:
                    # Template has no placeholders → emit once, no placeholder args
                    emission_pairs.append( ( template, "" ) )
                elif len( present_placeholders ) == 1:
                    # Single-placeholder: iterate all values (preserves legacy coverage)
                    ph   = present_placeholders[ 0 ]
                    spec = placeholder_specs[ ph ]
                    pat  = placeholder_patterns[ ph ]
                    for v in placeholder_values[ ph ]:
                        voice_command = pat.sub( lambda m, v=v: v, template )
                        args_value    = f'{spec[ "args_key" ]}="{v}"' if spec[ "args_key" ] else ""
                        emission_pairs.append( ( voice_command, args_value ) )
                else:
                    # Multi-placeholder: sample N combinations (cartesian would explode)
                    for _ in range( multi_placeholder_sample_size ):
                        voice_command = template
                        args_parts    = []
                        for ph in present_placeholders:
                            v    = random.choice( placeholder_values[ ph ] )
                            spec = placeholder_specs[ ph ]
                            voice_command = placeholder_patterns[ ph ].sub( lambda m, v=v: v, voice_command )
                            if spec[ "args_key" ]:
                                args_parts.append( f'{spec[ "args_key" ]}="{v}"' )
                        emission_pairs.append( ( voice_command, " ".join( args_parts ) ) )

                # Emit each (voice_command, args_value) pair as a training example
                for voice_command, args_value in emission_pairs:

                    # Append conditional args when trigger patterns match the voice command
                    # Two forms supported:
                    #   dict form:  { "value": "True", "triggers": [...] }            — single boolean-ish flag
                    #   list form:  [ { "value": "...", "triggers": [...] }, ... ]     — multi-value (first match wins)
                    voice_lower = voice_command.lower()
                    for cond_arg_name, cond_config in conditional_args.items():
                        if isinstance( cond_config, list ):
                            for spec in cond_config:
                                if any( trigger in voice_lower for trigger in spec[ "triggers" ] ):
                                    args_value += ( " " if args_value else "" ) + f'{cond_arg_name}="{spec[ "value" ]}"'
                                    break  # first match wins
                        else:
                            if any( trigger in voice_lower for trigger in cond_config[ "triggers" ] ):
                                args_value += ( " " if args_value else "" ) + f'{cond_arg_name}="{cond_config[ "value" ]}"'

                    # Add natural language variation
                    _, voice_command = self.prompt_generator.insert_interjection( voice_command, self.prompt_generator.interjections )
                    _, voice_command = self.prompt_generator.prepend_salutation( voice_command, self.prompt_generator.salutations )

                    # Use shared agent_router_instruction_template with ALL agent router commands
                    instruction = self.prompt_generator.agent_router_instruction_template.format( command_choices=self.prompt_generator.agent_router_commands )
                    human_says  = self.prompt_generator.common_human_says_template.format( voice_command=voice_command )
                    input_text  = self.prompt_generator.common_input_template.format( human_says=human_says, response_format=self.prompt_generator.common_response_format )
                    output      = self.prompt_generator.common_output_template.format( command=command_name, args=args_value )
                    prompt      = self.prompt_generator._get_prompt_instruction_format( instruction, input_text )

                    instructions.append( instruction )
                    inputs.append( input_text )
                    outputs.append( output )
                    prompts.append( prompt )
                    commands.append( command_name )

                    self._do_conditional_print( counter, voice_command )
                    counter += 1

            print()

        agentic_job_qna_df = pd.DataFrame( {"command": commands, "instruction": instructions, "input": inputs, "output": outputs, "prompt": prompts} )
        agentic_job_qna_df = self._prune_duplicates_and_sample( agentic_job_qna_df, sample_size=( sample_size_per_command * len( agentic_commands ) ), sample_size_per_command=sample_size_per_command )

        return agentic_job_qna_df

    def build_all_training_prompts( self, sample_size_per_command: int=400, include_agentic_jobs: bool=True ) -> pd.DataFrame:
        """
        Builds all training prompts by combining all command types.

        Requires:
            - sample_size_per_command is positive integer
            - include_agentic_jobs is boolean

        Ensures:
            - Combines all command types with uniform sample size
            - Calculates statistics
            - Returns unified DataFrame
        """
        compound_vox_cmd_qna_df       = self.build_compound_vox_cmd_training_prompts( sample_size_per_command=sample_size_per_command )
        simple_vox_cmd_qna_df         = self.build_simple_vox_cmd_training_prompts( sample_size_per_command=sample_size_per_command )

        compound_router_qna_df        = self.build_compound_agent_router_training_prompts( sample_size_per_command=sample_size_per_command )

        augmentation_config = {
            "agent router go to automatic"              : { "factor": 9 },
            "agent router go to calculator"             : { "factor": 3 },
            "agent router go to math"                   : { "factor": 3 },
            "agent router go to todo"                   : { "factor": 3 },
            "none"                                      : { "factor": 3 },
        }
        simple_router_qna_df          = self.build_simple_agent_router_training_prompts( sample_size_per_command=sample_size_per_command, augmentation_config=augmentation_config )

        # Build list of dataframes to concatenate
        dataframes_to_concat = [ compound_vox_cmd_qna_df, simple_vox_cmd_qna_df, compound_router_qna_df, simple_router_qna_df ]

        # Optionally include agentic job training prompts
        if include_agentic_jobs:
            agentic_job_qna_df = self.build_agentic_job_training_prompts( sample_size_per_command=sample_size_per_command )
            dataframes_to_concat.append( agentic_job_qna_df )

        # Stack all dataframes vertically
        all_qna_df = pd.concat( dataframes_to_concat, ignore_index=True )
        
        # ── Per-command distribution summary ──────────────────────────────────
        counts = all_qna_df[ "command" ].value_counts().sort_index()
        du.print_banner( f"Per-command distribution for all {all_qna_df.shape[ 0 ]:,} training prompts ({len( counts )} commands)", prepend_nl=True )
        print( f"  {'#':<4} {'Command':<55} {'Count':>7} {'Pct':>7}" )
        print( "  " + "." * 75 )
        for i, ( cmd, count ) in enumerate( counts.items(), 1 ):
            pct = 100.0 * count / len( all_qna_df )
            print( f"  {i:<4} {cmd:<55} {count:>7} {pct:>6.1f}%" )
        print( "  " + "." * 75 )
        print( f"  {'':4} {'TOTAL':<55} {counts.sum():>7} {'100.0%':>7}" )

        # ── Imbalance analysis ────────────────────────────────────────────────
        min_count = counts.min()
        max_count = counts.max()
        ratio     = max_count / min_count if min_count > 0 else float( "inf" )
        print( f"\n  Min: {min_count}  Max: {max_count}  Mean: {counts.mean():.1f}  Ratio: {ratio:.1f}x" )
        if ratio > 2.0:
            under_target = counts[ counts < sample_size_per_command ]
            if len( under_target ) > 0:
                print( f"\n  WARNING: {len( under_target )} commands below target ({sample_size_per_command}):" )
                for cmd, cnt in under_target.items():
                    print( f"    {cmd}: {cnt}" )
        
        # Calculate Max, min, and mean prompt lengths
        all_qna_df[ "prompt_length" ] = all_qna_df[ "prompt" ].apply( lambda cell: len( cell ) )
        max_prompt_length  = all_qna_df[ "prompt_length" ].max()
        min_prompt_length  = all_qna_df[ "prompt_length" ].min()
        mean_prompt_length = all_qna_df[ "prompt_length" ].mean()
        
        # Delete the prompt_length column
        all_qna_df.drop( columns=[ "prompt_length" ], inplace=True )
        
        du.print_banner( f"Max, min, and mean prompt CHARACTER counts for all {all_qna_df.shape[ 0 ]:,} training prompts", prepend_nl=True)
        print( f"Max  prompt length [{max_prompt_length:,}] characters" )
        print( f"Min  prompt length [{min_prompt_length:,}] characters" )
        print( f"Mean prompt length [{round( mean_prompt_length, 1 ):,}] characters" )
        
        # Now calculate max min and mean word counts in the prompt column
        all_qna_df[ "prompt_word_count" ] = all_qna_df[ "prompt" ].apply( lambda cell: len( cell.split( " " ) ) )
        max_prompt_word_count  = all_qna_df[ "prompt_word_count" ].max()
        min_prompt_word_count  = all_qna_df[ "prompt_word_count" ].min()
        mean_prompt_word_count = all_qna_df[ "prompt_word_count" ].mean()
        
        # Delete the prompt_word_count column
        all_qna_df.drop( columns=[ "prompt_word_count" ], inplace=True )
        
        du.print_banner( f"Max, min, and mean prompt WORD counts for all {all_qna_df.shape[ 0 ]:,} training prompts", prepend_nl=True )
        print( f"Max  prompt length [{max_prompt_word_count:,}] words" )
        print( f"Min  prompt length [{min_prompt_word_count:,}] words" )
        print( f"Mean prompt length [{round( mean_prompt_word_count, 1 ):,}] words" )
        
        return all_qna_df
    
    def query_llm_tgi( self, prompt: str, model_name: str, max_new_tokens: int=1024, temperature: float=0.25, top_k: int=10, top_p: float=0.9, silent: bool=False ) -> str:
        """
        Queries a TGI server with a prompt.
        
        Requires:
            - prompt is a non-empty string
            - model_name is a valid model identifier
            - max_new_tokens is positive integer
            - temperature is between 0.0 and 1.0
            
        Ensures:
            - Queries TGI server with prompt
            - Returns generated response
            - Prints progress indicators
        """
        from huggingface_hub import InferenceClient
        from cosa.utils.util_stopwatch import Stopwatch
    
        timer = Stopwatch( msg=f"Asking LLM [{model_name}]...".format( model_name ), silent=silent )
        
        client         = InferenceClient( self.tgi_url )
        token_list     = []
        ellipsis_count = 0
        
        if self.debug and self.verbose:
            for line in prompt.split( "\n" ):
                print( line )
        
        for token in client.text_generation(
            prompt, max_new_tokens=max_new_tokens, stream=True, temperature=temperature, top_k=top_k, top_p=top_p, stop_sequences=[ "</response>" ]
        ):
            if self.debug:
                print( token, end="" )
            else:
                if not silent: print( ".", end="" )
                ellipsis_count += 1
                if ellipsis_count == 120:
                    ellipsis_count = 0
                    print()
                
            token_list.append( token )
            
        response = "".join( token_list ).strip()
        
        timer.print( msg="Done!", use_millis=True, prepend_nl=True, end="\n" )
        tokens_per_second = len( token_list ) / ( timer.get_delta_ms() / 1000.0 )
        print( f"Tokens per second [{round( tokens_per_second, 1 )}]" )
        
        if self.debug:
            print( f"Token list length [{len( token_list )}]" )
            if self.verbose:
                for line in response.split( "\n" ):
                    print( line )
        
        return response
    
    def generate_responses( self, df: pd.DataFrame, model: Optional[Any]=None, model_name: Optional[str]=None, max_new_tokens: int=1024, temperature: float=0.25, top_k: int=10, top_p: float=0.9, device: str="cuda:0", debug: Optional[bool]=None, verbose: Optional[bool]=None, silent: bool=False, vllm_base_url: Optional[str]=None ) -> pd.DataFrame:
        """
        Generates responses for a given DataFrame using various LLM backends.
        
        Requires:
            - df contains 'prompt' column
            - max_new_tokens is positive integer
            - temperature is between 0.0 and 1.0
            
        Ensures:
            - Generates responses for all prompts
            - Adds 'response' column to DataFrame
            - Returns DataFrame with responses
        """
        from cosa.utils.util_stopwatch import Stopwatch
        import torch
        
        # Save the original debug/verbose settings
        original_debug   = self.debug
        original_verbose = self.verbose
        
        # Use the passed parameters if provided
        if debug is not None:
            self.debug = debug
        if verbose is not None:
            self.verbose = verbose
            
        # initialize variables we'll need to maintain state while iterating using the apply function
        self.reset_call_counter()
        if vllm_base_url:
            from cosa.agents.completion_client import CompletionClient
            self.llm_client = CompletionClient(
                base_url=vllm_base_url, model_name=model,
                prompt_format="instruction_completion",
                debug=self.debug, verbose=self.verbose
            )
        else:
            factory = LlmClientFactory()
            self.llm_client = factory.get_client( model, debug=self.debug, verbose=self.verbose )
        rows = df.shape[0]
        timer = Stopwatch( msg=f"Generating responses for {rows:,} rows...", silent=silent )

        df[ "response" ]  = df[ "prompt" ].apply( lambda cell: self._get_response( cell, rows, timer=timer, model_name=model_name, max_new_tokens=max_new_tokens, temperature=temperature, top_k=top_k, top_p=top_p, silent=silent ) )
        
        self.debug   = original_debug
        self.verbose = original_verbose
        
        timer.print( msg="Done!", use_millis=False, prepend_nl=True, end="\n" )
        ms_per_item = timer.get_delta_ms() / ( rows * 1.0 )
        self.last_ms_per_item = ms_per_item
        print( f"[{round( ms_per_item, 1 ):,}] ms per item" )

        return df
    
    def validate_responses( self, df: pd.DataFrame ) -> pd.DataFrame:
        """
        Validates responses in a dataframe using the response validator.
        
        Requires:
            - df contains 'response' column
            
        Ensures:
            - Validates all responses
            - Adds validation columns
            - Returns DataFrame with validation results
        """
        return self.response_validator.validate_responses( df )
    
    def print_validation_stats( self, df: pd.DataFrame, title: str="Validation Stats" ) -> pd.DataFrame:
        """
        Prints validation statistics.
        
        Requires:
            - df contains validation columns
            - title is a string
            
        Ensures:
            - Prints validation statistics
            - Returns stats DataFrame
        """
        return self.response_validator.print_validation_stats( df, title=title )
    
    def get_train_test_validate_split( self, df: pd.DataFrame, sample_size: int=1000, test_size: float=0.2, test_validate_size: float=0.5, stratify: str="command" ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Splits a DataFrame into training, testing, and validation sets.

        Requires:
            - df contains expected columns
            - sample_size is positive integer
            - test_size is between 0.0 and 1.0
            - test_validate_size is between 0.0 and 1.0
            - stratify column exists in df

        Ensures:
            - Creates stratified splits
            - Returns three DataFrames
            - Total samples match sample_size
        """
        from sklearn.model_selection import train_test_split

        sampled_df = df[ [ "command", "instruction", "input", "output", "prompt" ] ].sample( sample_size, random_state=42 ).copy()

        # Split the dataframe into train and (test+validate)
        train_df, test_validate_df = train_test_split( sampled_df, test_size=test_size, random_state=42, stratify=sampled_df[ stratify ] )

        # Then split (test+validate) into test and validate
        test_df, validate_df = train_test_split( test_validate_df, test_size=test_validate_size, random_state=42, stratify=test_validate_df[ stratify ] )

        return train_df, test_df, validate_df
    
    def write_ttv_split_to_jsonl( self, train_df: pd.DataFrame, test_df: pd.DataFrame, validate_df: pd.DataFrame ) -> None:
        """
        Writes train/test/validate splits to JSONL files.

        Requires:
            - All DataFrames contain expected columns
            - Write permissions for output directory

        Ensures:
            - Creates JSONL files for each split
            - Sets appropriate file permissions
        """
        import os

        du.print_banner( "Writing train, test, validate splits to jsonl...", prepend_nl=True )
        print( f"   train_df.shape: {train_df.shape[ 0 ]:,} x {train_df.shape[ 1 ]}" )
        print( f"    test_df.shape: {test_df.shape[ 0 ]:,} x {test_df.shape[ 1 ]}" )
        print( f"validate_df.shape: {validate_df.shape[ 0 ]:,} x {validate_df.shape[ 1 ]}" )

        path = self.path_prefix + "/src/ephemera/prompts/data/voice-commands-xml-train.jsonl"
        train_df.to_json( path, orient="records", lines=True )
        os.chmod( path, 0o666 )

        path = self.path_prefix + "/src/ephemera/prompts/data/voice-commands-xml-test.jsonl"
        test_df.to_json( path, orient="records", lines=True )
        os.chmod( path, 0o666 )

        path = self.path_prefix + "/src/ephemera/prompts/data/voice-commands-xml-validate.jsonl"
        validate_df.to_json( path, orient="records", lines=True )
        os.chmod( path, 0o666 )

    def compare_validation_results( self, before_df: pd.DataFrame, after_df: pd.DataFrame, title: str="Validation Comparison" ) -> pd.DataFrame:
        """
        Compares validation results between two dataframes.
        
        Requires:
            - Both DataFrames contain validation columns
            - title is a string
            
        Ensures:
            - Compares validation results
            - Returns comparison DataFrame
        """
        return self.response_validator.compare_validation_results( before_df, after_df, title=title )
    
    # Helper methods
    def _get_5_empty_lists( self ) -> tuple[list, list, list, list, list]:
        """
        Returns 5 empty lists for storing prompt generation data.

        Requires:
            - None

        Ensures:
            - Returns tuple of 5 empty lists
            - Lists are for: instructions, inputs, outputs, prompts, commands
        """
        return [], [], [], [], []
    
    
    def _do_conditional_print( self, counter: int, voice_command: str, interval: int=10 ) -> None:
        """
        Conditionally prints progress information.
        
        Requires:
            - counter is positive integer
            - voice_command is a string
            - interval is positive integer
            
        Ensures:
            - Prints progress at intervals
            - Shows voice command or dots
        """
        if counter % interval == 0:
            if self.debug:
                print( voice_command )
            else:
                print( ".", end="" )
                if counter % ( interval * 100 ) == 0:
                    print()
    
    def _prune_duplicates_and_sample( self, df: pd.DataFrame, sample_size: int=1000, sample_size_per_command: int=-1 ) -> pd.DataFrame:
        """
        Removes duplicates and samples from a DataFrame.
        
        Requires:
            - df contains 'input' and 'command' columns
            - sample_size is positive integer
            - sample_size_per_command is integer
            
        Ensures:
            - Removes duplicate inputs
            - Samples data per command
            - Returns processed DataFrame
        """
        du.print_banner( "Pruning potential duplicates by 'input' values...", prepend_nl=True )
        
        rows_pre = df.shape[ 0 ]
        print( f" PRE {rows_pre:,} training inputs..." )
        df.drop_duplicates( subset=[ "input" ], inplace=True )
        rows_post  = df.shape[ 0 ]
        dupes_rows = rows_pre - rows_post
        dupes_pct  = dupes_rows / rows_pre * 100.0
        print( f"POST {rows_post:,} training inputs. Deleted {dupes_rows:,} rows = {dupes_pct:.1f}% duplicate questions" )
        
        if rows_post < sample_size:
            print( f"WARNING: Sample size [{sample_size:,}] > rows_post [{rows_post:,}]. Returning all [{rows_post:,}] rows." )
            return df
        else:
            # Show per-command counts before sampling
            group_counts = df[ "command" ].value_counts( normalize=False )
            du.print_banner( f"Per-command counts before sampling (target: {sample_size_per_command:,}/command):", prepend_nl=True )
            print( group_counts )

            # Check for undersized groups and warn
            undersized = group_counts[ group_counts < sample_size_per_command ]
            if len( undersized ) > 0:
                print( f"\n  WARNING: {len( undersized )} command(s) below target ({sample_size_per_command}):" )
                for cmd, cnt in undersized.items():
                    print( f"    {cmd}: {cnt} (will use all available)" )

            # Sample per group: take min( target, available ) to avoid ValueError
            sampled_groups = []
            for command, group_df in df.groupby( "command" ):
                n = min( sample_size_per_command, len( group_df ) )
                sampled_groups.append( group_df.sample( n, random_state=42 ) )

            return pd.concat( sampled_groups, ignore_index=True )
    
    def _get_receptionist_titles( self, requested_length: int=10 ) -> list:
        """
        Gets placeholder receptionist titles.
        
        Requires:
            - requested_length is positive integer
            
        Ensures:
            - Returns list of titles
            - Length matches requested_length
        """
        return self.prompt_generator._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-receptionist-titles.txt", requested_length=requested_length )
    
    def _get_events_values( self, requested_length: int=100 ) -> list[dict]:
        """
        Gets placeholder calendar event values.
        
        Requires:
            - requested_length is positive integer
            
        Ensures:
            - Returns list of event dictionaries
            - Each dict contains required keys
            - Length matches requested_length
        """
        events      = self.prompt_generator._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-calendaring-events.txt", requested_length=None )
        locations   = self.prompt_generator._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-calendaring-locations.txt", requested_length=None )
        start_times = self.prompt_generator._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-calendaring-dates-and-times.txt", requested_length=None )
        people      = self.prompt_generator._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-calendaring-people.txt", requested_length=None )
        
        events_values = []
        
        for i in range( requested_length ):
            events_values.append( {
                "EVENT_TYPE": random.choice( events ),
                "LOCATION"  : random.choice( locations ),
                "START_TIME": random.choice( start_times ),
                "PEOPLE"    : random.choice( people ),
                "PLACE"     : ""
            } )
        return events_values
    
    def _get_response(
        self, prompt: str, rows: int, model: Optional[Any]=None, model_name: Optional[str]=None, timer: Optional[Any]=None, tokenizer: Optional[Any]=None,
        max_new_tokens: int=1024, temperature: float=0.25, top_k: int=10, top_p: float=0.9, device: str="cuda:0", silent: bool=False, debug: bool=False, verbose: bool=False
    ) -> str:
        """
        Gets a response to a specific prompt using the specified LLM backend.
        
        Requires:
            - prompt is a non-empty string
            - rows is positive integer
            - temperature is between 0.0 and 1.0
            
        Ensures:
            - Increments call counter
            - Shows progress information
            - Returns generated response
        """
        self._call_counter += 1
        
        print( f"Processing call [{self._call_counter:03d}] out of [{rows}] = [{round( self._call_counter / rows * 100.0, 1 )}%]... ", end="" )
        
        # calculate remaining time
        if timer is not None:
            try:
                elapsed_ms = timer.get_delta_ms()
                ms_per_item = elapsed_ms / ( self._call_counter * 1.0 )
                remaining_ms = ( rows - self._call_counter ) * ms_per_item
                remaining_seconds = int( remaining_ms / 1000 )
                # calculate remaining minutes
                if remaining_seconds > 60:
                    remaining_minutes = int( remaining_seconds / 60 )
                    remaining_seconds = remaining_seconds % 60
                    print( f"ETA mm:ss {remaining_minutes:}:{remaining_seconds:02d}" )
                else:
                    print( f"ETA: {remaining_seconds} seconds" )
            except Exception as e:
                print( f"ETA: Error '{e}'" )
                
        return self.llm_client.run( prompt, max_tokens=max_new_tokens )


def quick_smoke_test():
    """
    Critical smoke test for XmlCoordinator - validates functionality and detects v000 dependencies.
    
    This test is essential for v000 deprecation as XmlCoordinator has known v000 dependencies
    that must be resolved before v000 agent removal.
    """
    import cosa.utils.util as du
    
    du.print_banner( "XmlCoordinator Smoke Test", prepend_nl=True )
    
    try:
        # Test 1: Basic instantiation
        print( "Testing basic instantiation..." )
        coordinator = XmlCoordinator( 
            debug=False, 
            verbose=False, 
            silent=True,
            init_prompt_templates=False  # Skip template initialization to avoid file dependencies
        )
        print( "✓ Basic instantiation successful" )
        
        # Test 2: Component initialization
        print( "Testing component initialization..." )
        if hasattr( coordinator, 'prompt_generator' ) and coordinator.prompt_generator is not None:
            print( "✓ Prompt generator initialized" )
        else:
            print( "✗ Prompt generator failed to initialize" )
            
        if hasattr( coordinator, 'response_validator' ) and coordinator.response_validator is not None:
            print( "✓ Response validator initialized" )
        else:
            print( "✗ Response validator failed to initialize" )
        
        # Test 3: Core functionality (safe methods only)
        print( "Testing core functionality..." )
        
        # Test call counter operations
        coordinator.reset_call_counter()
        if coordinator._call_counter == 0:
            print( "✓ Call counter reset working" )
        else:
            print( "✗ Call counter reset failed" )
        
        # Test helper methods
        empty_lists = coordinator._get_5_empty_lists()
        if len( empty_lists ) == 5 and all( isinstance( lst, list ) and len( lst ) == 0 for lst in empty_lists ):
            print( "✓ Helper methods working" )
        else:
            print( "✗ Helper methods failed" )
        
        # Test 4: XML validation capabilities (basic)
        print( "Testing XML validation..." )
        test_xml = "<response><command>test</command></response>"
        try:
            is_valid = coordinator.is_valid_xml( test_xml )
            print( f"✓ XML validation working (result: {is_valid})" )
        except Exception as e:
            print( f"⚠ XML validation had issues: {e}" )
        
        # Test 5: Critical v000 dependency detection
        print( "\n🚨 CRITICAL: Scanning for v000 dependencies..." )
        
        # Scan the file for v000 patterns
        import inspect
        source_file = inspect.getfile( XmlCoordinator )
        
        v000_found = False
        v000_patterns = []
        
        with open( source_file, 'r' ) as f:
            content = f.read()
            
            # Check for v000 imports and references
            if "v000" in content:
                v000_found = True
                lines = content.split( '\n' )
                for i, line in enumerate( lines ):
                    if "v000" in line:
                        v000_patterns.append( f"Line {i+1}: {line.strip()}" )
        
        if v000_found:
            print( "🚨 CRITICAL: v000 dependencies detected!" )
            print( "   Found v000 references:" )
            for pattern in v000_patterns[ :3 ]:  # Show first 3
                print( f"     • {pattern}" )
            if len( v000_patterns ) > 3:
                print( f"     ... and {len( v000_patterns ) - 3} more v000 references" )
            print( "   ⚠️  These dependencies MUST be resolved before v000 deprecation!" )
            print( "   📋 Action Required: Update XmlCoordinator to use v010 agents only" )
        else:
            print( "✅ EXCELLENT: No v000 dependencies found!" )
        
        # Test 6: Error handling
        print( "\nTesting error handling..." )
        try:
            # Test invalid XML
            result = coordinator.is_response_exact_match( "invalid", "also_invalid" )
            print( "✓ Error handling working" )
        except Exception as e:
            print( f"⚠ Error handling had issues: {e}" )
        
    except Exception as e:
        print( f"✗ Error during XmlCoordinator testing: {e}" )
        import traceback
        traceback.print_exc()
    
    # Summary with v000 emphasis
    print( "\n" + "="*60 )
    if v000_found:
        print( "🚨 CRITICAL ISSUE: XmlCoordinator has v000 dependencies!" )
        print( "   Status: NOT READY for v000 deprecation" )
        print( "   Priority: IMMEDIATE ACTION REQUIRED" )
        print( "   Risk Level: HIGH - Training system will break" )
    else:
        print( "✅ XmlCoordinator smoke test completed successfully!" )
        print( "   Status: Ready for v000 deprecation" )
        print( "   Risk Level: LOW" )
    
    print( "✓ XmlCoordinator smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()