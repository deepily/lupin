import json
import os
import random
import regex as re
from xmlschema import XMLSchema
from typing import Optional, Any, Union

import cosa.utils.util as du
import cosa.utils.util_xml as dux

class XmlPromptGenerator:
    """
    Handles template management and prompt generation for XML-based LLM training.
    
    Responsible for:
    - Managing prompt templates for different command types
    - Formatting templates with proper content
    - Handling placeholder substitutions
    - Adding natural language variations (interjections, salutations)
    """
    
    def __init__( self, path_prefix: str=du.get_project_root(), debug: bool=False, verbose: bool=False, silent: bool=False ) -> None:
        self.debug                              = debug
        self.verbose                            = verbose
        self.silent                             = silent
        self.path_prefix                        = path_prefix
        
        # Template management
        self.common_input_template              = None
        self.common_human_says_template         = None
        self.common_response_format             = None
        self.common_output_template             = None
        self._init_common_templates()
        
        # Command templates
        self.vox_cmd_instruction_template          = None
        self.vox_cmd_instruction_template_gpt      = None
        self.agent_router_instruction_template     = None
        self.agent_router_instruction_template_gpt = None
        
        # Command categories
        self.vox_cmd_commands      = None
        self.agent_router_commands = None
        
        # Command dictionaries
        self.vox_cmd_compound_commands                = self._get_compound_vox_commands()
        self.vox_cmd_simple_commands                  = self._get_simple_vox_commands()
        self.agent_router_compound_commands           = self._get_compound_agent_router_commands()
        self.agent_router_simple_commands             = self._get_simple_agent_router_commands()
        self.agent_router_agentic_commands            = self._get_agentic_job_commands()
        self.agent_function_mapping_compound_commands = self._get_compound_agent_function_mapping_commands()

        # The JSONs supply PHRASINGS; the registry says what EXISTS. Checked here, before
        # a single row is built, because a row is where the two would silently disagree.
        self._assert_agent_router_json_commands_are_registry_subset()

        # Compile commands after loading dictionaries
        self.vox_cmd_commands                   = self._compile_vox_cmd_commands()
        self.agent_router_commands              = self._compile_agent_router_commands()
        
        # Initialize templates after compiling commands
        self._init_vox_cmd_templates()
        self._init_agent_router_templates()
        
        # Natural language variation data
        self.interjections                      = self.get_interjections()
        self.salutations                        = self.get_salutations()
    
    def _test_command_paths( self, commands: dict ) -> None:
        """
        Verifies that all command file paths exist.
        
        Requires:
            - commands is dictionary with string values
            - path_prefix is set
        
        Ensures:
            - Checks existence of all command files
            - Prints status if not silent
        
        Raises:
            - Exception if any command file missing
        """
        for command in commands.keys():
            path_exists = os.path.exists( self.path_prefix + commands[ command ] )
            if self.debug and not self.silent:
                print( f"Commands file for command [{command}] exists: {path_exists}" )
            if not path_exists:
                raise Exception( f"Commands file for command [{command}] [{self.path_prefix + commands[ command ]}] doesn't exist!" )
        
        if not self.silent:
            print()
    
    def _get_compound_vox_commands( self ) -> dict:
        """
        Returns dictionary of compound voice commands and their corresponding file paths.

        Requires:
            - JSON config file exists at src/conf/training/vox-cmd-compound-commands.json

        Ensures:
            - Returns command name to file path mapping loaded from JSON config
            - All file paths are tested for existence
        """
        config_path = self.path_prefix + "/src/conf/training/vox-cmd-compound-commands.json"
        with open( config_path, "r" ) as f:
            compound_commands = json.load( f )
        self._test_command_paths( compound_commands )

        return compound_commands
    
    def _get_simple_vox_commands( self ) -> dict:
        """
        Returns dictionary of simple voice commands and their corresponding file paths.

        Requires:
            - JSON config file exists at src/conf/training/vox-cmd-simple-commands.json

        Ensures:
            - Returns command name to file path mapping loaded from JSON config
            - All file paths are tested for existence
        """
        config_path = self.path_prefix + "/src/conf/training/vox-cmd-simple-commands.json"
        with open( config_path, "r" ) as f:
            simple_commands = json.load( f )
        self._test_command_paths( simple_commands )

        return simple_commands
    
    def _get_compound_agent_router_commands( self ) -> dict:
        """
        Returns dictionary of compound agent router commands and their file paths.

        Requires:
            - JSON config file exists at src/conf/training/agent-router-compound-commands.json

        Ensures:
            - Returns command name to file path mapping loaded from JSON config
            - All file paths are tested for existence
        """
        config_path = self.path_prefix + "/src/conf/training/agent-router-compound-commands.json"
        with open( config_path, "r" ) as f:
            compound_commands = json.load( f )
        self._test_command_paths( compound_commands )

        return compound_commands
    
    def _get_simple_agent_router_commands( self ) -> dict:
        """
        Returns dictionary of simple agent router commands and their file paths.

        Requires:
            - JSON config file exists at src/conf/training/agent-router-simple-commands.json

        Ensures:
            - Returns command name to file path mapping loaded from JSON config
            - All file paths are tested for existence
            - Does NOT include agentic job commands (those have their own getter)
        """
        config_path = self.path_prefix + "/src/conf/training/agent-router-simple-commands.json"
        with open( config_path, "r" ) as f:
            simple_commands = json.load( f )
        self._test_command_paths( simple_commands )

        return simple_commands
    
    def _get_agentic_job_commands( self ) -> dict:
        """
        Returns dictionary of agentic job commands loaded from enriched JSON config.

        Requires:
            - JSON config file exists at src/conf/training/agent-router-agentic-commands.json
            - Each entry has a "template_file" key with a valid path

        Ensures:
            - Returns enriched config dict (command name -> {template_file, placeholders, args_key})
            - All template_file paths are tested for existence
        """
        config_path = self.path_prefix + "/src/conf/training/agent-router-agentic-commands.json"
        with open( config_path, "r" ) as f:
            agentic_commands = json.load( f )

        # Validate template files exist (enriched format: value is dict with "template_file" key)
        flat_paths = { cmd: entry[ "template_file" ] for cmd, entry in agentic_commands.items() }
        self._test_command_paths( flat_paths )

        return agentic_commands

    def _get_compound_agent_function_mapping_commands( self ) -> dict:
        """
        Returns dictionary of compound agent function mapping commands.
        
        Requires:
            - None
        
        Ensures:
            - Returns command name to file path mapping
            - Handles configuration loading errors
        """
        try:
            from cosa.config.configuration_manager import ConfigurationManager
            config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            agent_function_mapping_compound_commands = {
                # This data set is not only static vs. dynamic, but also memory search vs. web search
                "agent router go to search function mapping": config_mgr.get( "path to search function mapping data wo root" )
            }
            self._test_command_paths( agent_function_mapping_compound_commands )
            return agent_function_mapping_compound_commands
        except Exception as e:
            if self.debug:
                print( f"Warning: Could not load function mapping commands: {e}" )
            return {}
    
    def _compile_vox_cmd_commands( self ) -> str:
        """
        Compiles both compound and simple voice commands into XML format.
        
        Requires:
            - vox_cmd_compound_commands initialized
            - vox_cmd_simple_commands initialized
        
        Ensures:
            - Returns XML formatted commands
            - Combines compound and simple commands
        """
        compound_categories = "".join( [ "        <command>" + command + "</command>\n" for command in self.vox_cmd_compound_commands.keys() ] )
        simple_categories   = "".join( [ "        <command>" + command + "</command>\n" for command in self.vox_cmd_simple_commands.keys() ] )
        
        return ( compound_categories + simple_categories ).strip()
    
    def _assert_agent_router_json_commands_are_registry_subset( self ) -> None:
        """
        Refuse to build a corpus for a command the registry has never heard of.

        WHAT THIS CLOSES (row 95924f2d, step 4). The MENU is already single-sourced —
        `_compile_agent_router_commands` reads `speakable_commands()`, and no JSON can
        move it. But the three agent-router JSONs still decide WHICH commands get rows:
        `xml_coordinator` iterates their keys and formats each row's answer with the key
        it is on. So a key the registry does not list produces training rows teaching a
        command the menu inside those very rows does not offer — and the LoRA learns
        both halves. Measured before this guard: injecting one key left the menu at 18
        while the row loop happily iterated the invented command.

        WHY THE ORACLE IS THE WHOLE REGISTRY AND NOT `speakable_commands()`: a
        system-triggered command is deliberately in the registry and deliberately out of
        the router prompt — the expediters are exactly that. Checking against the
        speakable set would flag a documented exemption as drift, which is how a guard
        earns the right to be ignored. Checking against REGISTRY lets the exemption
        through and still catches the invented command.

        This is the cheap half of step 4. The full version has the row loops iterate the
        registry and look each phrasing file up; this one lets the JSONs keep driving row
        generation while making it impossible for them to invent a command.

        Requires:
            - the three agent_router_*_commands dicts are loaded

        Ensures:
            - returns None when every JSON key is a command the registry knows
            - raises ValueError naming every unknown key otherwise, before any row is
              built

        Raises:
            - ValueError if any agent-router JSON key is absent from the registry
        """
        from cosa.rest.v2.registry import REGISTRY

        json_commands = (
            set( self.agent_router_compound_commands )
            | set( self.agent_router_simple_commands )
            | set( self.agent_router_agentic_commands )
        )
        unknown = sorted( json_commands - set( REGISTRY ) )
        if unknown:
            raise ValueError(
                "agent-router training JSON names command(s) the v2 registry does not "
                f"list: {unknown}. The JSONs supply PHRASINGS; the registry says what "
                "EXISTS (row 95924f2d). Building anyway would emit training rows whose "
                "answer is a command the menu in those same rows never offers. Either "
                "register the command in cosa/rest/v2/registry.py, or remove the key "
                "from the JSON."
            )

    def _compile_agent_router_commands( self ) -> str:
        """
        Compile the router command MENU that every training instruction interpolates.

        Single-sourced from the v2 registry (2026.08.16 single-source design §2.4):
        the menu is exactly the speakable commands the served router prompt lists, so
        the training menu and the served prompt cannot disagree by construction — the
        18-vs-19 drift this row exists to end. The three agent-router JSONs REMAIN the
        source of the example phrasings (row generation, §5.3); they no longer define
        WHICH commands exist. `speakable_commands()` fails loud if its order tuple and
        the registry ever disagree, so a stale menu cannot pass silently.

        Requires:
            - cosa.rest.v2.router_prompt_generator.speakable_commands is importable

        Ensures:
            - Returns the 8-space-indented <command> lines for speakable_commands(),
              in served order, matching the sibling builders' interpolation format
        """
        from cosa.rest.v2.router_prompt_generator import speakable_commands
        return "".join(
            [ "        <command>" + command + "</command>\n" for command in speakable_commands() ]
        ).strip()
    
    def _init_common_templates( self ) -> None:
        """
        Initializes common templates used for prompt formatting.
        
        Requires:
            - None
        
        Ensures:
            - Sets common template attributes
            - Templates are properly formatted
        """
        self.common_input_template = """
        Below is the raw human voice command transcription formatted using simple XML:
        {human_says}

        The standardized command that you translate MUST be returned wrapped in simple, well-formed XML:
        {response_format}"""
        
        self.common_human_says_template = """
        <human>
            <voice-command>{voice_command}</voice-command>
        </human>"""
        
        self.common_response_format = """
        <response>
            <command></command>
            <args></args>
        </response>"""
        
        self.common_output_template = """
        <response>
            <command>{command}</command>
            <args>{args}</args>
        </response>"""
    
    def _init_vox_cmd_templates( self ) -> None:
        """
        Initializes voice command templates.
        
        Requires:
            - vox_cmd_commands is compiled
        
        Ensures:
            - Sets vox command template attributes
            - Templates include command choices
        """
        self.vox_cmd_instruction_template_gpt = """INSTRUCTIONS:
        Your job is to discern the intent of a human voice command transcription and translate it into a standardized command that a browser on your computer would understand.

        You will be given a human voice command as INPUT as well as a list of possible standardized commands. You must choose the correct standardized command from the following list:
        
        <browser-commands>
            {command_choices}
        </browser-commands>
        
        RESPONSE FORMAT: MUST be returned wrapped in simple, well-formed XML
        <response>
            <command></command>
            <args></args>
        </response>
        """
        
        self.vox_cmd_instruction_template = """Your job is to discern the intent of a human voice command transcription and translate it into a standardized command that a browser on your computer would understand.

        You will be given a human voice command and a list of possible standardized commands. You must choose the correct standardized command from the following list:
        <browser-commands>
        {command_choices}
        </browser-commands>

        Requirement: You MUST NOT use python code to answer this question.
        Requirement: You MUST use your linguistic knowledge and intuition to answer this question.
        Requirement: The first word of your response MUST be `<response>`
        Hint: Anything that isn't a part of the command itself should be treated as arguments related to the command."""
    
    def _init_agent_router_templates( self ) -> None:
        """
        Initializes agent router templates.
        
        Requires:
            - agent_router_commands is compiled
        
        Ensures:
            - Sets agent router template attributes
            - Templates include command choices
        """
        self.agent_router_instruction_template_gpt = """INSTRUCTIONS:
        Your job is to discern the intent of a human voice command transcription and translate it into a standardized agent routing command that another LLM would understand.

        You will be given a human voice command as INPUT as well as a list of possible standardized commands. You must choose the correct standardized command from the following list:

        <agent-routing-commands>
            {command_choices}
        </agent-routing-commands>

        RESPONSE FORMAT: MUST be returned wrapped in simple, well-formed XML
        <response>
            <command></command>
            <args></args>
        </response>
        """
        
        self.agent_router_instruction_template = """Your job is to discern the intent of a human voice command transcription and translate it into a standardized agent routing command that another LLM would understand.

        You will be given a human voice command as INPUT as well as a list of possible standardized commands. You must choose the correct standardized command from the following list:
        <agent-routing-commands>
            {command_choices}
        </agent-routing-commands>

        Requirement: You MUST NOT use python code to answer this question.
        Requirement: You MUST use your linguistic knowledge and intuition to answer this question.
        Requirement: The first word of your response MUST be `<response>`
        Hint: Anything that isn't a part of the command itself should be treated as arguments related to the command."""
    
    def get_prompt_template( self, name: str ) -> str:
        """
        Returns a formatted prompt template for the specified command type.
        
        Requires:
            - name is 'vox command' or 'agent router'
        
        Ensures:
            - Returns properly formatted template
            - Template includes appropriate commands
        
        Raises:
            - ValueError if unknown template name
        """
        if name == "vox command":
            instruction = self.vox_cmd_instruction_template.format( command_choices=self.vox_cmd_commands )
        elif name == "agent router":
            instruction = self.agent_router_instruction_template.format( command_choices=self.agent_router_commands )
        else:
            raise ValueError( f"Unknown prompt template name [{name}] Please use one of ['vox command', 'agent router']" )
        
        human_says  = self.common_human_says_template.format( voice_command="{voice_command}" )
        input_text  = self.common_input_template.format( human_says=human_says, response_format=self.common_response_format )
        prompt      = self._get_prompt_instruction_format( instruction, input_text )
        
        reformatted_prompt = []
        
        # Splitting on '\n will consume some of the lines
        for line in prompt.split( "\n" ):
            
            # Remove the first 8 and then 4 leading space characters if they exist
            if line.startswith( "        " ):
                line = line[8:]
            elif line.startswith( "    " ):
                line = line[4:]
            
            # Adhoc insertion of space before command items
            if line.startswith( "<command>" ):
                line = "    " + line
                
            reformatted_prompt.append( line )

        prompt = "\n".join( reformatted_prompt )
        
        return prompt
    
    def _get_prompt_instruction_format( self, instruction: str, input_text: str ) -> str:
        """
        Formats instruction and input into a standardized prompt format.
        
        Requires:
            - instruction is non-empty string
            - input_text is non-empty string
        
        Ensures:
            - Returns formatted prompt
            - Includes task and response sections
        """
        return f"""### Instruction:
        
    Use the Task and Input given below to write a Response that can solve the following Task.
    
    ### Task:
    
    {instruction}
    
    ### Input:
    {input_text}
    
    ### Response:
    """
    
    def get_prompt( self, instruction: str, input_text: str, output: str="" ) -> str:
        """
        Formats a prompt with instruction, input, and optional output.
        
        Requires:
            - instruction is non-empty string
            - input_text is non-empty string
        
        Ensures:
            - Returns formatted prompt
            - Uses common templates
        """
        human_says = self.common_human_says_template.format( voice_command=input_text )
        prompt_input = self.common_input_template.format( human_says=human_says, response_format=self.common_response_format )
        prompt = self._get_prompt_instruction_format( instruction, prompt_input )
        
        return prompt
    
    def get_interjections( self, requested_length: Optional[int]=None ) -> list:
        """
        Gets a list of interjections for more natural language generation.
        
        Requires:
            - requested_length is None or positive integer
        
        Ensures:
            - Returns list of interjections
            - Length matches requested_length if specified
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-interjections-um-er-uh-etc.txt", requested_length=requested_length )
    
    def get_salutations( self, requested_length: int=500 ) -> list:
        """
        Gets randomized salutations with computer names.
        
        Requires:
            - requested_length is positive integer
        
        Ensures:
            - Returns list of salutations
            - Computer names substituted
            - Length matches requested_length
        """
        names       = self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-receptionist-names.txt", requested_length=None )
        salutations = self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-receptionist-salutations.txt", requested_length=requested_length )
        
        for idx, salutation in enumerate( salutations ):
            name = random.choice( names )
            # If we don't have any names, return the salutation sans the placeholder
            if name == "":
                salutations[ idx ] = salutation.replace( " COMPUTER_NAME", "" )
            else:
                salutations[ idx ] = salutation.replace( "COMPUTER_NAME", name )
        
        return salutations
    
    def insert_interjection( self, text: str, interjections: Optional[list]=None ) -> tuple[str, str]:
        """
        Inserts a random interjection into the provided text.
        
        Requires:
            - text is a string
            - interjections is None or list of strings
        
        Ensures:
            - Returns tuple with interjection and modified text
            - Randomly inserts interjection
            - Capitalizes if at beginning
        """
        if interjections is None:
            interjections = self.interjections
            
        interjection = random.choice( interjections )
        
        # If we don't have any interjections, return the text as is
        if interjection == "": 
            return "", text
        
        # Split on spaces and insert randomly
        words  = text.split()
        index  = random.randint( 0, len( words ) )
        # Capitalize the first word, otherwise lowercase it
        if index == 0:
            words.insert( index, interjection.capitalize() )
        else:
            words.insert( index, interjection.lower() )
            
        return interjection, " ".join( words )
    
    def prepend_salutation( self, text: str, salutations: Optional[list]=None ) -> tuple[str, str]:
        """
        Prepends a random salutation to the given text.
        
        Requires:
            - text is a string
            - salutations is None or list of strings
        
        Ensures:
            - Returns tuple with salutation and modified text
            - Text starts with salutation if provided
            - First character lowercased
        """
        if salutations is None:
            salutations = self.salutations
            
        salutation = random.choice( salutations )
        
        # If we don't have any salutation to prepend, return the text as is
        if salutation == "":
            return "", text
        else:
            # Lowercase the first word of the text
            return salutation, salutation + " " + text[0].lower() + text[1:]
    
    def _get_placeholder_values( self, placeholder_file: str, requested_length: Optional[int]=None ) -> list:
        """
        Loads placeholder values from a file.
        
        Requires:
            - placeholder_file is valid path string
            - requested_length is None or positive integer
        
        Ensures:
            - Returns list of placeholder values
            - Duplicates added if needed to match length
            - Length matches requested_length if specified
        """
        # A requested_length of None used as the second value in a list slice returns the entire list
        placeholders = du.get_file_as_list(
            self.path_prefix + placeholder_file, lower_case=False, clean=True, randomize=True
        )[:requested_length]
        
        # If we don't have enough placeholder values, append copies until we have enough
        while requested_length is not None and requested_length > len( placeholders ):
            # advise that we're inserting duplicate placeholders
            if self.debug and not self.silent: 
                print( f"Inserting DUPLICATE placeholders into the list. Requested length [{requested_length}] > list length [{len( placeholders )}]" )
            placeholders += placeholders
            
        # Truncate the placeholder list to equal the requested length
        placeholders = placeholders[:requested_length]
        
        return placeholders
    
    def get_search_terms( self, requested_length: int=100 ) -> list:
        """
        Gets placeholder search terms.
        
        Requires:
            - requested_length is positive integer
        
        Ensures:
            - Returns list of search terms
            - Length matches requested_length
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-search-terms.txt", requested_length=requested_length )
    
    def get_cities_and_countries( self, requested_length: Optional[int]=100 ) -> list:
        """
        Gets placeholder city and country names.
        
        Requires:
            - requested_length is None or positive integer
        
        Ensures:
            - Returns list of location names
            - Length matches requested_length if specified
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-cities-and-countries.txt", requested_length=requested_length )
    
    def get_domain_names( self, requested_length: int=100 ) -> list:
        """
        Generates domain names for URL commands.

        Requires:
            - requested_length is positive integer

        Ensures:
            - Returns list of domain names
            - Length equals requested_length
        """
        return du.generate_domain_names( requested_length )

    def get_research_topics( self, requested_length: Optional[int]=100 ) -> list:
        """
        Gets placeholder research topics for agentic job training.

        Requires:
            - requested_length is None or positive integer

        Ensures:
            - Returns list of research topics
            - Length matches requested_length if specified
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-research-topics.txt", requested_length=requested_length )

    def get_budget_values( self, requested_length: Optional[int]=None ) -> list:
        """
        Gets placeholder budget values for deep research.

        Requires:
            - requested_length is None or positive integer

        Ensures:
            - Returns list of budget values (as strings)
            - Length matches requested_length if specified
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-budget-values.txt", requested_length=requested_length )

    def get_language_codes( self, requested_length: Optional[int]=None ) -> list:
        """
        Gets placeholder language codes for agentic jobs.

        Requires:
            - requested_length is None or positive integer

        Ensures:
            - Returns list of language codes
            - Length matches requested_length if specified
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-language-codes.txt", requested_length=requested_length )

    def get_document_paths( self, requested_length: Optional[int]=None ) -> list:
        """
        Gets placeholder document paths for podcast generation.

        Requires:
            - requested_length is None or positive integer

        Ensures:
            - Returns list of document paths
            - Length matches requested_length if specified
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-document-paths.txt", requested_length=requested_length )

    def get_claude_code_tasks( self, requested_length: Optional[int]=None ) -> list:
        """
        Gets placeholder task descriptions for Claude Code job training.

        Requires:
            - requested_length is None or positive integer

        Ensures:
            - Returns list of coding task descriptions
            - Length matches requested_length if specified
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-claude-code-tasks.txt", requested_length=requested_length )

    def get_swe_team_tasks( self, requested_length: Optional[int]=None ) -> list:
        """
        Gets placeholder feature/project descriptions for SWE team job training.

        Requires:
            - requested_length is None or positive integer

        Ensures:
            - Returns list of feature-oriented task descriptions
            - Length matches requested_length if specified
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-swe-team-tasks.txt", requested_length=requested_length )

    def get_test_types( self, requested_length: Optional[int]=None ) -> list:
        """
        Gets placeholder test-suite type names for test suite job training.

        Requires:
            - requested_length is None or positive integer

        Ensures:
            - Returns list of test type names
            - Length matches requested_length if specified
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-test-types.txt", requested_length=requested_length )

    def get_tfe_plan_paths( self, requested_length: Optional[int]=None ) -> list:
        """
        Gets placeholder TFE resume targets for test-fix-expediter resume training.

        Values are limited to the two forms resume_resolver.resolve_resume_target
        actually implements — a tfe-* job ID, or a plan doc path ending in
        "-plan.md" / containing "/plans/". Its natural-language branch is a
        Phase 2 stub, so free-text targets are deliberately excluded.

        Requires:
            - requested_length is None or positive integer

        Ensures:
            - Returns list of resolvable TFE resume targets
            - Length matches requested_length if specified
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-tfe-plan-paths.txt", requested_length=requested_length )

    def get_audience_levels( self, requested_length: Optional[int]=None ) -> list:
        """
        Gets placeholder audience levels for podcast generation.

        Requires:
            - requested_length is None or positive integer

        Ensures:
            - Returns list of audience levels
            - Length matches requested_length if specified
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-audience-levels.txt", requested_length=requested_length )

    def get_audience_contexts( self, requested_length: Optional[int]=None ) -> list:
        """
        Gets placeholder audience context descriptions.

        Requires:
            - requested_length is None or positive integer

        Ensures:
            - Returns list of audience context descriptions
            - Length matches requested_length if specified
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-audience-contexts.txt", requested_length=requested_length )

    def get_max_segments( self, requested_length: Optional[int]=None ) -> list:
        """
        Gets placeholder max segments values for podcast generation.

        Requires:
            - requested_length is None or positive integer

        Ensures:
            - Returns list of max segment values (as strings)
            - Length matches requested_length if specified
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-max-segments.txt", requested_length=requested_length )

    def get_renderer_names( self, requested_length: Optional[int]=None ) -> list:
        """
        Gets placeholder renderer names for presentation generation.

        Requires:
            - requested_length is None or positive integer

        Ensures:
            - Returns list of renderer names (mermaid, matplotlib, d2, veo, nano_banana + ASR variants)
            - Length matches requested_length if specified
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-renderer-names.txt", requested_length=requested_length )

    def get_duration_minutes( self, requested_length: Optional[int]=None ) -> list:
        """
        Gets placeholder duration values in minutes for presentation/podcast generation.

        Requires:
            - requested_length is None or positive integer

        Ensures:
            - Returns list of duration values as strings (mix of numeric and word forms)
            - Length matches requested_length if specified
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-duration-minutes.txt", requested_length=requested_length )

    def get_agentic_templates( self, requested_length: Optional[int]=None ) -> list:
        """
        Gets placeholder agentic voice command templates.

        Requires:
            - requested_length is None or positive integer

        Ensures:
            - Returns list of voice command templates
            - Length matches requested_length if specified
        """
        return self._get_placeholder_values( "/src/ephemera/prompts/data/placeholders-agentic-templates.txt", requested_length=requested_length )

    def serialize_prompt( self, prompt: str, prompt_path: str ) -> None:
        """
        Writes a prompt to a file.
        
        Requires:
            - prompt is a string
            - prompt_path is valid path string
        
        Ensures:
            - Prompt written to file
            - Path is relative to path_prefix
        """
        path = self.path_prefix + prompt_path
        
        du.print_banner( f"Serializing prompt to [{path}]", prepend_nl=True )
        du.write_string_to_file( path, prompt )
        
    def serialize_prompts( self, prompt_path_prefix: str ) -> None:
        """
        Writes all prompt templates to files.
        
        Requires:
            - prompt_path_prefix is valid directory path
        
        Ensures:
            - All templates serialized
            - Files created at specified location
        """
        self.serialize_prompt( self.get_prompt_template( "vox command" ), prompt_path_prefix + "vox-command-template.txt" )
        self.serialize_prompt( self.get_prompt_template( "agent router" ), prompt_path_prefix + "agent-router-template.txt" )