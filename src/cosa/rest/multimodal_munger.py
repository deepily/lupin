import json
import re
from collections import defaultdict
from typing import Optional, Union, Any

import openai

import cosa.utils.util_stopwatch as sw
import cosa.utils.util as du

from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.agents.io_models.xml_models import CommandResponse
from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError

from cosa.config.configuration_manager import ConfigurationManager

# Currently, all transcription mode descriptors are three words long.
# This will become important or more important in the future?
trans_mode_text_raw           = "multimodal text raw"
trans_mode_text_email         = "multimodal text email"
trans_mode_text_punctuation   = "multimodal text punctuation"
trans_mode_text_broadcast     = "multimodal text broadcast"
trans_mode_text_proofread     = "multimodal text proofread"
trans_mode_text_contact       = "multimodal contact information"
trans_mode_sql_punctuation    = "multimodal sql punctuation"
trans_mode_sql_proofread      = "multimodal sql proofread"
trans_mode_python_punctuation = "multimodal python punctuation"
trans_mode_python_proofread   = "multimodal python proofread"
trans_mode_server_search      = "multimodal server search"
trans_mode_run_prompt         = "multimodal run prompt"
trans_mode_vox_cmd_browser    = "multimodal browser"
trans_mode_vox_cmd_agent      = "multimodal agent"
trans_mode_default            = trans_mode_text_punctuation

modes_to_methods_dict = {
    
    trans_mode_vox_cmd_agent     : "munge_vox_cmd_agent",
    trans_mode_vox_cmd_browser   : "munge_vox_cmd_browser",
    trans_mode_text_raw          : "munge_text_raw",
    trans_mode_text_email        : "munge_text_email",
    trans_mode_text_punctuation  : "munge_text_punctuation",
    trans_mode_text_broadcast    : "munge_text_broadcast",
    trans_mode_text_proofread    : "munge_text_proofread",
    trans_mode_text_contact      : "munge_text_contact",
    trans_mode_python_punctuation: "munge_python_punctuation",
    trans_mode_python_proofread  : "munge_python_proofread",
    trans_mode_sql_punctuation   : "munge_sql_punctuation",
    trans_mode_sql_proofread     : "munge_sql_proofread",
    # trans_mode_server_search     : "do_ddg_search",
    # trans_mode_run_prompt        : "do_run_prompt",
}
class MultiModalMunger:
    """
    Process and munge multimodal transcriptions based on various modes.
    
    This class handles different types of transcription processing including
    text, email, code, commands, and contact information. It supports both
    string matching and AI-based matching for command recognition.
    """

    def __init__( self, raw_transcription: str, prefix: str="", prompt_key: str="generic", config_path: str="conf/modes-vox.json",
                  use_string_matching: bool=True, use_ai_matching: bool=True, debug: bool=False, verbose: bool=False, 
                  last_response: Optional[dict[str, Any]]=None, config_mgr: Optional[ConfigurationManager]=None ) -> None:
        """
        Initialize the multimodal transcription munger.
        
        Requires:
            - raw_transcription is a non-empty string
            - prompt_key exists in prompt-dictionary.map if provided
            - Various configuration files exist (translation-dictionary.map, etc.)
            
        Ensures:
            - Loads configuration dictionaries from files
            - Parses raw transcription into transcription and mode
            - Sets up command strings and class dictionaries
            - Initializes results field
            
        Raises:
            - FileNotFoundError if configuration files missing
            - KeyError if prompt_key not found in prompt dictionary
        """

        self.debug                  = debug
        self.verbose                = verbose
        self.config_mgr             = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ) if config_mgr is None else config_mgr
        self.config_path            = config_path
        self.raw_transcription      = raw_transcription
        self.prefix                 = prefix
        self.use_ai_matching        = use_ai_matching
        self.use_string_matching    = use_string_matching
        
        self.punctuation            = du.get_file_as_dictionary( du.get_project_root() + "/src/conf/translation-dictionary.map", lower_case=True, debug=self.debug )
        self.domain_names           = du.get_file_as_dictionary( du.get_project_root() + "/src/conf/domain-names.map",           lower_case=True )
        self.numbers                = du.get_file_as_dictionary( du.get_project_root() + "/src/conf/numbers.map",                lower_case=True )
        self.contact_info           = du.get_file_as_dictionary( du.get_project_root() + "/src/conf/contact-information.map",    lower_case=True )
        self.prompt_dictionary      = du.get_file_as_dictionary( du.get_project_root() + "/src/conf/prompt-dictionary.map",      lower_case=True )
        self.prompt                 = du.get_file_as_string( du.get_project_root() + self.prompt_dictionary.get( prompt_key, "generic" ) )
        self.command_strings        = self._get_command_strings()
        self.class_dictionary       = self._get_class_dictionary()
        
        # self.cmd_llm_tokenizer      = cmd_llm_tokenizer
        # self.cmd_llm_in_memory      = cmd_llm_in_memory
        # self.cmd_llm_name           = cmd_llm_name
        # self.cmd_llm_device         = cmd_llm_device
        # self.cmd_prompt_template    = cmd_prompt_template
        
        if self.debug and self.verbose:
            print( "prompt_key:", prompt_key )
            print( "prompt:", self.prompt )
        
        self.modes_to_methods_dict  = modes_to_methods_dict
        self.methods_to_modes_dict  = self._get_methods_to_modes_dict( modes_to_methods_dict )
        
        if self.debug and self.verbose:
            print( "modes_to_methods_dict", self.modes_to_methods_dict, end="\n\n" )
            print( "methods_to_modes_dict", self.methods_to_modes_dict, end="\n\n" )
        
        # This field added to hold the Results of a calculation, e.g.: ddg search, contact information, or eventually proofreading
        # When all processing is refactored and consistent across all functionality. ¡TODO!
        self.results       = ""
        self.last_response = last_response
        
        if self.debug and self.verbose:
            print( "self.last_response:", self.last_response )
        
        parsed_fields      = self.parse( raw_transcription )
        self.transcription = parsed_fields[ 0 ]
        self.mode          = parsed_fields[ 1 ]
        
        
    def __str__( self ) -> str:
        """
        Return string representation of the munger state.
        
        Requires:
            - Object attributes are initialized
            
        Ensures:
            - Returns formatted string with all major attributes
            
        Raises:
            - None
        """

        summary = """
                       Mode: [{}]
                     Prefix: [{}]
          Raw transcription: [{}]
        Final transcription: [{}]
                    Results: [{}]""".format( self.mode, self.prefix, self.raw_transcription, self.transcription, self.results )
        return summary

    def get_jsons( self ) -> str:
        """
        Get JSON representation of the munger state.
        
        Requires:
            - All required attributes are initialized
            
        Ensures:
            - Returns valid JSON string with munger state
            - Includes mode, prefix, transcriptions, and results
            
        Raises:
            - JSONEncodeError if attributes not serializable
        """
        
        # instantiate dictionary and convert to string
        munger_dict = { "mode": self.mode, "prefix": self.prefix, "raw_transcription": self.raw_transcription, "transcription": self.transcription, "results": self.results }
        json_str    = json.dumps( munger_dict )
        
        return json_str
        
    def _get_methods_to_modes_dict( self, modes_to_methods_dict: dict[str, str] ) -> dict[str, str]:
        """
        Create reverse mapping from methods to modes.
        
        Requires:
            - modes_to_methods_dict is a valid dictionary
            
        Ensures:
            - Returns dictionary mapping method names to mode names
            - Each method maps to exactly one mode
            
        Raises:
            - None
        """
        
        methods_to_modes_dict = { }
        
        for mode, method in modes_to_methods_dict.items():
            methods_to_modes_dict[ method ] = mode
        
        return methods_to_modes_dict
    def parse( self, raw_transcription: str ) -> tuple[str, str]:
        """
        Parse raw transcription to determine mode and process accordingly.
        
        Requires:
            - raw_transcription is a non-empty string
            - Mode-to-method mappings are initialized
            
        Ensures:
            - Returns tuple of (processed_transcription, mode)
            - Handles voice command parsing when appropriate
            - Applies mode-specific processing
            
        Raises:
            - AttributeError if method not found for mode
        """
        
        # ¡OJO! super special ad hoc prefix cleanup due to the use of 'multi'... please don't do this often!
        raw_transcription = self._adhoc_prefix_cleanup( raw_transcription )
        
        # knock everything down to alphabetic characters and spaces so that we can analyze what transcription mode we're in.
        regex = re.compile( '[^a-zA-Z ]' )
        transcription = regex.sub( '', raw_transcription ).replace( "-", " " ).lower()
        
        # First and foremost: Are we in multi-modal editor/command mode?
        # print( "  self.prefix:", self.prefix )
        # print( "transcription:", transcription )
        
        if self.prefix == trans_mode_vox_cmd_browser or transcription.startswith( trans_mode_vox_cmd_browser ):
            
            # ad hoc short circuit for the 'repeat' command
            if ( transcription == "repeat" or transcription == trans_mode_vox_cmd_browser + " repeat" ) and self.last_response is not None:
                
                print( self.last_response )
                
                self.prefix            = self.last_response[ "prefix" ]
                self.results           = self.last_response[ "results" ]
                self.raw_transcription = self.last_response[ "raw_transcription" ]
                
                return self.last_response[ "transcription" ], self.last_response[ "mode" ]
            
            elif ( transcription == "repeat" or transcription == trans_mode_vox_cmd_browser + " repeat" ) and self.last_response is None:
                
                print( "No previous response to repeat" )

            # strip out the prefix and move it into its own field before continuing
            if transcription.startswith( trans_mode_vox_cmd_browser ):
                
                # Strip out the first two words, regardless of punctuation
                # words_sans_prefix = "multimodal? editor! search, new tab, y tu mamá, también!".split( " " )[ 2: ]
                words_sans_prefix = raw_transcription.split( " " )[ 2: ]
                raw_transcription = " ".join( words_sans_prefix )
                self.prefix = trans_mode_vox_cmd_browser

            du.print_banner( "START MODE: [{}] for [{}]".format( self.prefix, raw_transcription ), end="\n" )
            transcription, mode = self._handle_vox_command_parsing( raw_transcription )
            print( "commmand_dict: {}".format( self.results ) )
            du.print_banner( "  END MODE: [{}] for [{}]".format( self.prefix, raw_transcription ), end="\n\n" )
            
            return transcription, mode
        
        print( "transcription [{}]".format( transcription ) )
        words = transcription.split()

        prefix_count = len( trans_mode_default.split() )
        
        # If we have fewer than 'prefix_count' words, just assign default transcription mode.
        if len( words ) < prefix_count and ( self.prefix == "" or self.prefix not in self.modes_to_methods_dict ):
            method_name = self.modes_to_methods_dict[ trans_mode_default ]
        else:
            
            first_words = " ".join( words[ 0:prefix_count ] )
            print( "first_words:", first_words )
            default_method = self.modes_to_methods_dict[ trans_mode_default ]
            method_name    = self.modes_to_methods_dict.get( first_words, default_method )
            
            # Conditionally pull the first n words before we send them to be transcribed.
            if first_words in self.modes_to_methods_dict:
                raw_words = raw_transcription.split()
                raw_transcription = " ".join( raw_words[ prefix_count: ] )
            else:
                print( "first_words [{}] of raw_transcription not found in modes_to_methods_dict".format( first_words ) )
                # If we have a prefix, try to use it to determine the transcription mode.
                if self.prefix in self.modes_to_methods_dict:
                    print( "prefix [{}] in modes_to_methods_dict".format( self.prefix ) )
                    method_name = self.modes_to_methods_dict[ self.prefix ]
                else:
                    print( "prefix [{}] not found in modes_to_methods_dict either".format( self.prefix ) )
                
        mode = self.methods_to_modes_dict[ method_name ]
        
        if self.debug:
            print( "Calling [{}] w/ mode [{}]...".format( method_name, mode ) )
            print( "raw_transcription [{}]".format( raw_transcription ) )
            
        transcription, mode = getattr( self, method_name )( raw_transcription, mode )
        if self.debug:
            print( "result after:", transcription )
            print( "mode:", mode )
        
        return transcription, mode
        
    def _handle_vox_command_parsing( self, raw_transcription: str ) -> tuple[str, str]:
        """
        Handle voice command parsing with string and AI matching.
        
        Requires:
            - raw_transcription is a string
            - Command matching settings are configured
            
        Ensures:
            - Returns tuple of (transcription, mode)
            - Attempts string matching first if enabled
            - Falls back to AI matching if enabled
            - Sets self.results with command dictionary
            
        Raises:
            - None
        """
    
        transcription, mode = self.munge_vox_cmd_browser( raw_transcription, trans_mode_vox_cmd_browser )

        # Try exact match first, then AI match if no exact match is found.
        if self.use_string_matching:

            is_match, command_dict = self._is_match( transcription )
            
            if is_match:

                self.results = command_dict
                return transcription, mode

        if self.use_ai_matching:

            print( "Attempting AI match..." )
            self.results = self._get_ai_command( transcription )
            print( "Attempting AI match... done!")

        return transcription, mode
    
    def _adhoc_prefix_cleanup( self, raw_transcription: str ) -> str:
        """
        Clean up common transcription errors in prefixes.
        
        Requires:
            - raw_transcription is a string
            
        Ensures:
            - Returns cleaned transcription
            - Fixes multimodal variations
            - Fixes toggle variations
            
        Raises:
            - None
        """
        
        # Find the first instance of "multi________" and replace it with "multimodal".
        multimodal_regex  = re.compile( "multi([ -]){0,1}mod[ae]l", re.IGNORECASE )
        raw_transcription = multimodal_regex.sub( "multimodal", raw_transcription, 1 )

        multimodal_regex = re.compile( "t[ao]ggle", re.IGNORECASE )
        raw_transcription = multimodal_regex.sub( "toggle", raw_transcription, 1 )
        
        return raw_transcription

    def _tokenize( self, text: str ) -> list[str]:
        """
        Split text into tokens: words (with apostrophes), spaces, and punctuation.
        Preserves everything for exact reconstruction when joined.

        Requires:
            - text is a string

        Ensures:
            - Returns list of tokens
            - Words include apostrophes (e.g., "What's" stays as one token)
            - Spaces preserved as separate tokens
            - Punctuation preserved as separate tokens
            - ''.join( result ) == original text

        Raises:
            - None

        Examples:
            "What's five?" → ["What's", " ", "five", "?"]
            "Five plus five" → ["Five", " ", "plus", " ", "five"]
        """
        # Match: words (including apostrophes), spaces, or single punctuation chars
        return re.findall( r"[\w']+|[ ]+|[^\w\s']", text )

    def _remove_protocols( self, words: str ) -> str:
        """
        Remove URL protocols from text.
        
        Requires:
            - words is a string
            
        Ensures:
            - Returns text with http:// and https:// removed
            - Only removes first occurrence
            
        Raises:
            - None
        """
        
        multimodal_regex = re.compile( "http([s]){0,1}://", re.IGNORECASE )
        words = multimodal_regex.sub( "", words, 1 )
        
        return words
    
    def _remove_spaces_around_punctuation( self, prose: str ) -> str:
        """
        Remove excessive spaces around punctuation marks.
        
        Requires:
            - prose is a string
            
        Ensures:
            - Returns text with normalized punctuation spacing
            - Handles various punctuation marks
            - Removes double punctuation
            
        Raises:
            - None
        """
    
        # Remove extra spaces.
        prose = prose.replace( " / ", "/" )
        prose = prose.replace( "[ ", "[" )
        prose = prose.replace( " ]", "]" )
    
        # prose = prose.replace( "< ", "<" )
        # prose = prose.replace( " >", ">" )
    
        prose = prose.replace( ". (", "(" )
        prose = prose.replace( " )", ")" )
        prose = prose.replace( "( ", "(" )
        prose = prose.replace( "):.", "):" )
        
        prose = prose.replace( " .", "." )
        prose = prose.replace( " ,", "," )
        prose = prose.replace( "??", "?" )
        prose = prose.replace( " ?", "?" )
        prose = prose.replace( "!!", "!" )
        prose = prose.replace( " !", "!" )
        prose = prose.replace( " :", ":" )
        prose = prose.replace( " ;", ";" )
        prose = prose.replace( ' "', '"' )
        prose = prose.replace( ' _ ', '_' )
        prose = prose.replace( ".. ", ". " )
        
        return prose
    
    def _remove_dashes_from_single_letters_within_word( self, word: str ) -> str:
        """
        Remove dashes between single letters in a word.
        
        Requires:
            - word is a string
            
        Ensures:
            - Returns word with dashes removed between single letters
            - Preserves hyphens in compound words
            
        Raises:
            - None
        """
        return re.sub(
            r'\b(\w)(-\w)+\b', lambda m: ''.join( [ char for char in m.group( 0 ) if char.isalpha() ] ), word
       )
    
    def _remove_dashed_spellings( self, sentence: str ) -> str:
        """
        Remove dashes between single letters throughout a sentence.
        
        Requires:
            - sentence is a string
            
        Ensures:
            - Returns sentence with dashed spellings cleaned
            - Applies to all words in the sentence
            - Preserves hyphenated compound words
            
        Raises:
            - None
        """
        return " ".join( [ self._remove_dashes_from_single_letters_within_word( word ) for word in sentence.split( " " ) ] )
    
    def _collapse_spaces_around_punctuation( self, code: str ) -> str:
        """
        Collapse spaces around punctuation in code.
        
        Requires:
            - code is a string
            
        Ensures:
            - Returns code with normalized spacing
            - Handles code-specific punctuation patterns
            - Preserves syntactically required spaces
            
        Raises:
            - None
        """
        
        code = code.replace( " _ ", "_" )
        code = code.replace( " ,", ", " )
        code = code.replace( "self . ", "self." )
        code = code.replace( " . ", "." )
        code = code.replace( "[ { } ]", "[{}]" )
        code = code.replace( " [", "[" )
        code = code.replace( " ( )", "()" )
        code = code.replace( ") :", "):" )
        code = code.replace( " ( ", "( " )
        code = code.replace( ") ;", ");" )
        
        return code
    
    def munge_text_raw( self, raw_transcription: str, mode: str ) -> tuple[str, str]:
        """
        Process raw text transcription minimally.
        
        Requires:
            - raw_transcription is a string
            - mode is a valid mode string
            
        Ensures:
            - Returns tuple of (transcription, mode)
            - Removes dashed spellings only
            
        Raises:
            - None
        """
        
        transcription = self._remove_dashed_spellings( raw_transcription )
        return transcription, mode
    
    def munge_text_email( self, raw_transcription: str, mode: str ) -> tuple[str, str]:
        """
        Process text for email addresses.
        
        Requires:
            - raw_transcription is a string
            - mode is a valid mode string
            - Domain and number dictionaries are loaded
            
        Ensures:
            - Returns tuple of (email, mode)
            - Converts to lowercase
            - Handles domain names and numbers
            - Removes spaces and extra punctuation
            
        Raises:
            - None
        """
    
        # Add special considerations for the erratic nature of email transcriptions when received raw from the whisper.
        # prose = raw_transcription.replace( ".", " dot " )
        print( "BEFORE raw_transcription:", raw_transcription )
        email = raw_transcription.lower()
        
        # Decode domain names
        for key, value in self.domain_names.items():
            email = email.replace( key, value )
        
        # Decode numbers
        for key, value in self.numbers.items():
            email = email.replace( key, value )

        # Remove space between individual numbers.
        regex = re.compile( '(?<=[0-9]) (?=[0-9])' )
        email = regex.sub( "", email )
        
        print( " AFTER raw_transcription:", raw_transcription )
        
        email = re.sub( r'[,]', '', email )
        
        # phonetic spellings often contain -'s
        regex = re.compile( "(?<=[a-z])([-])(?=[a-z])", re.IGNORECASE )
        email = regex.sub( "", email )

        # Translate punctuation mark words into single characters.
        for key, value in self.punctuation.items():
            email = email.replace( key, value )

        # Remove extra spaces around punctuation.
        email = self._remove_spaces_around_punctuation( email )
        
        # Remove extra spaces
        email = email.replace( " ", "" )
        
        # Remove trailing periods.
        email = email.rstrip( "." )
        
        email = self._remove_dashed_spellings( email )
        
        return email, mode
    
    def munge_vox_cmd_browser( self, raw_transcription: str, mode: str ) -> tuple[str, str]:
        """
        Process voice commands for browser control.
        
        Requires:
            - raw_transcription is a string
            - mode is a valid mode string
            
        Ensures:
            - Returns tuple of (command, mode)
            - Handles URLs and domain names
            - Removes unnecessary punctuation
            - Normalizes spacing
            
        Raises:
            - None
        """
        
        command = raw_transcription.lower()
        command = self._remove_dashed_spellings( command )

        # Remove the protocol from URLs
        command = self._remove_protocols( command )
        
        # Encode domain names as plain text before removing dots below
        for key, value in self.domain_names.items():
            command = command.replace( key, value )
            
        command = re.sub( r'[,?!]', '', command )
        
        # Remove periods between words + trailing periods
        command = command.replace( ". ", " " ).rstrip( "." )
        
        # Translate punctuation mark words into single characters.
        for key, value in self.punctuation.items():
            command = command.replace( key, value )
        
        # Remove extra spaces.
        command = self._remove_spaces_around_punctuation( command )
        
        return command, mode
    
    def munge_vox_cmd_agent( self, raw_transcription: str, mode: str ) -> tuple[str, str]:
        """
        Process voice commands for agent control.
        
        Requires:
            - raw_transcription is a string
            - mode is a valid mode string
            
        Ensures:
            - Returns tuple of (transcription, mode)
            - Handles underscore replacements
            - Removes dashed spellings
            
        Raises:
            - None
        """
        
        du.print_banner( "AGENT MODE for [{}]".format( raw_transcription ), end="\n" )
        # Agent voice command processing - currently using simple passthrough
        
        transcription = self._remove_dashed_spellings( raw_transcription )
        # Add hawk clean up for forcing underscores when giving explicit field name commands to the agent
        transcription = transcription.replace( " underscore ", "_" )
        
        return transcription, mode
    
    def munge_text_punctuation( self, raw_transcription: str, mode: str ) -> tuple[str, str]:
        """
        Process text with proper punctuation while preserving original case.

        Uses TOKENIZATION approach for reliable word-level replacement without
        fragile regex boundary handling.

        Requires:
            - raw_transcription is a string
            - mode is a valid mode string
            - Punctuation and number dictionaries are loaded

        Ensures:
            - Returns tuple of (prose, mode)
            - Preserves original case from raw_transcription (e.g., "What's" stays capitalized)
            - Handles URL protocols
            - Converts punctuation words to symbols (case-insensitive matching)
            - Converts number words to digits (e.g., "two" → "2", case-insensitive)
            - Normalizes spacing

        Raises:
            - None

        Implementation Notes (2024.11.30):
            TOKENIZATION APPROACH:
                Instead of regex patterns on continuous text (which fails at boundaries),
                we tokenize first, match tokens against dictionaries, then rejoin.

                "What's five plus five?" → ["What's", " ", "five", " ", "plus", " ", "five", "?"]
                                        → ["What's", " ", "5",    " ", "+",    " ", "5",    "?"]
                                        → "What's 5 + 5?"

            Benefits:
                - Word boundaries are implicit (tokens are pre-separated)
                - Works at sentence start/end (no space boundary issues)
                - Case preservation is natural (check lowercase, keep/replace original)
                - No complex regex patterns to maintain
                - The `|` space-delimiter in .map files is now irrelevant - just strip keys

            Previous approaches (regex-based) failed because:
                - ` five ` pattern couldn't match "five?" at end of sentence
                - ` five ` pattern couldn't match "Five" at start of sentence
                - Order of operations mangled spacing around punctuation

            To rollback: See commented OLD APPROACHES below.
        """

        # ============================================================================
        # OLD APPROACHES - Preserved for rollback reference
        # ============================================================================
        # APPROACH 1 (case-destructive, simple .replace()):
        #     prose = raw_transcription.lower()
        #     for key, value in self.punctuation.items():
        #         prose = prose.replace( key, value )
        #     Problem: Lost case - "What's 2 plus 2?" → "what's 2 + 2?"
        #
        # APPROACH 2 (regex with space-boundary detection):
        #     if key.startswith( ' ' ) or key.endswith( ' ' ):
        #         pattern = r'(?i)' + re.escape( key )
        #     else:
        #         pattern = r'(?i)\b' + re.escape( key ) + r'\b'
        #     prose = re.sub( pattern, lambda m: value, prose )
        #     Problem: Failed at boundaries - "five?" couldn't match " five "
        # ============================================================================

        # ============================================================================
        # TOKENIZATION APPROACH
        # ============================================================================

        prose = raw_transcription

        # Remove URL protocols first (before tokenization)
        prose = self._remove_protocols( prose )

        # Build case-insensitive lookup dictionaries (strip spaces from keys)
        # The `|` delimiter in .map files adds spaces, but tokenization makes them irrelevant
        domain_lookup = { k.strip().lower(): v for k, v in self.domain_names.items() if k.strip() }
        punct_lookup  = { k.strip().lower(): v for k, v in self.punctuation.items() if k.strip() }
        number_lookup = { k.strip().lower(): v for k, v in self.numbers.items() if k.strip() }

        # Tokenize: split into words, spaces, and punctuation
        tokens = self._tokenize( prose )

        # Replace tokens (order: domains, then punctuation, then numbers)
        result = []
        for token in tokens:
            token_lower = token.lower()
            if token_lower in domain_lookup:
                result.append( domain_lookup[ token_lower ] )
            elif token_lower in punct_lookup:
                result.append( punct_lookup[ token_lower ] )
            elif token_lower in number_lookup:
                result.append( number_lookup[ token_lower ] )
            else:
                result.append( token )  # Keep original (preserves case)

        prose = ''.join( result )

        # Remove commas and periods
        prose = re.sub( r'[,.]', '', prose )

        # ============================================================================

        # Remove extra spaces around punctuation
        prose = self._remove_spaces_around_punctuation( prose )

        # Remove dashed spellings (e.g., "t-h-i-s" → "this")
        prose = self._remove_dashed_spellings( prose )

        return prose, mode

    def munge_text_broadcast( self, raw_transcription: str, mode: str ) -> tuple[str, str]:
        """
        Process broadcast-context speech while preserving @-mention syntax.

        Mirrors munge_text_punctuation's tokenize-and-lookup pipeline but:
          - Phrase-preprocesses literal "at sign" → "@" BEFORE tokenization
            (the per-token tokenizer cannot match the multi-token map entry)
          - OMITS the comma/period strip that munge_text_punctuation applies
            (broadcast preserves '.' and ',' so URLs, versions, decimals, and
             @user.name patterns survive intact)

        Requires:
            - raw_transcription is a string
            - mode is a valid mode string
            - Punctuation, number, and domain dictionaries are loaded

        Ensures:
            - Returns tuple of (prose, mode)
            - Literal "at sign" (case-insensitive, word-boundaried) is replaced
              with "@" before tokenization
            - Single-token punctuation lookups still fire ("dot" → ".",
              "underscore" → "_", "hash" → "#", "period" → ".", etc.)
            - "." and "," characters in the output are preserved (not stripped)
            - Bare "at" not followed by "sign" stays as the English word
              (preserves "look at this", "we'll meet at noon")

        Raises:
            - None

        Design notes (2026-05-13):
            Decision Q2 (verbose) explicitly limits @-conversion to the literal
            phrase "at sign". Whisper produces this phrase reliably when the
            user dictates the symbol; bare "at" is ambiguous and would break
            ordinary English in non-mention contexts.

            The line-757 [,.] strip in munge_text_punctuation is intentionally
            absent here. That strip is a separate prose-mode bug filed under
            its own TODO entry — fixing it in this mode is out of scope and
            would risk regressing the default punctuation path.
        """

        prose = raw_transcription

        # Phrase-preprocess passes for multi-token map entries.
        # The tokenizer (see _tokenize) is per-token, so multi-word map keys like
        # "at sign = @" / "question mark = ?" / "exclamation point = !" cannot
        # match downstream via the per-token lookup. We substitute the spoken
        # phrases to their target symbols BEFORE tokenization.
        #
        # Whitespace handling diverges by symbol semantics:
        #   - "at sign" is a JOINING char (binds to following identifier), so
        #     \s* consumes the trailing space → "at sign you" → "@you"
        #   - "question mark" / "exclamation point" are TERMINAL chars (natural
        #     space after them), so we DO NOT consume trailing whitespace; the
        #     existing _remove_spaces_around_punctuation pass collapses any
        #     " ?" / " !" leading-space afterwards.
        prose = re.sub( r"\bat sign\s*",         "@", prose, flags=re.IGNORECASE )
        prose = re.sub( r"\bquestion mark\b",    "?", prose, flags=re.IGNORECASE )
        prose = re.sub( r"\bexclamation point\b", "!", prose, flags=re.IGNORECASE )

        # Remove URL protocols (mirror munge_text_punctuation)
        prose = self._remove_protocols( prose )

        # Build case-insensitive lookup dictionaries (strip spaces from keys)
        domain_lookup = { k.strip().lower(): v for k, v in self.domain_names.items() if k.strip() }
        punct_lookup  = { k.strip().lower(): v for k, v in self.punctuation.items()  if k.strip() }
        number_lookup = { k.strip().lower(): v for k, v in self.numbers.items()      if k.strip() }

        # Tokenize: split into words, spaces, and punctuation
        tokens = self._tokenize( prose )

        # Identifier-joining punctuation: when a spoken word maps to one of these
        # symbols, treat the conversion as a glue point — drop the surrounding
        # spaces so "file underscore name" → "file_name" and "1 dot 0" → "1.0".
        # Other punctuation (comma, colon, semicolon, etc.) keeps natural spacing.
        joining_chars = { ".", "_", "#" }

        # Replace tokens with explicit space-handling for joining punctuation.
        result = []
        i      = 0
        while i < len( tokens ):
            token       = tokens[ i ]
            token_lower = token.lower()

            if token_lower in domain_lookup:
                # Domain replacements (e.g., ".com") are themselves joining —
                # pull off any trailing whitespace from result so "example .com"
                # stays "example.com".
                if result and result[ -1 ].isspace():
                    result.pop()
                result.append( domain_lookup[ token_lower ] )
                i += 1
            elif token_lower in punct_lookup and punct_lookup[ token_lower ] in joining_chars:
                # Joining punctuation: drop a trailing space from result and the
                # next leading space from tokens so the symbol glues neighbors.
                if result and result[ -1 ].isspace():
                    result.pop()
                result.append( punct_lookup[ token_lower ] )
                if i + 1 < len( tokens ) and tokens[ i + 1 ].isspace():
                    i += 2
                else:
                    i += 1
            elif token_lower in punct_lookup:
                # Non-joining punctuation: append verbatim, preserve spacing.
                result.append( punct_lookup[ token_lower ] )
                i += 1
            elif token_lower in number_lookup:
                result.append( number_lookup[ token_lower ] )
                i += 1
            else:
                result.append( token )  # Keep original (preserves case)
                i += 1

        prose = "".join( result )

        # NB: line 757 [,.] strip is intentionally OMITTED here — broadcast
        # mode preserves periods and commas. See Q4 in design doc.

        # Remove extra spaces around punctuation (e.g., "@ you" → "@you")
        prose = self._remove_spaces_around_punctuation( prose )

        # Remove dashed spellings (e.g., "t-h-i-s" → "this")
        prose = self._remove_dashed_spellings( prose )

        # Ad-hoc cleanup of gratuitous Whisper-emitted punctuation runs
        # (broadcast-specific, added 2026-05-13 per Rick's voice request).
        # Whisper occasionally emits ",,," or ",!" around emphatic dictation;
        # broadcast preserves all punctuation by default but these specific
        # patterns are objectively redundant and degrade readability:
        #   - Multiple commas in a row → single comma
        #   - Comma immediately before "!" → drop the comma
        #   - Period immediately after "!" → drop the period
        # Apply in order so cascades work (e.g., ",,!" → ",!" → "!").
        prose = re.sub( r",+", ",", prose )
        prose = prose.replace( ",!", "!" )
        prose = prose.replace( "!.", "!" )

        return prose, mode

    def munge_text_contact( self, raw_transcription: str, mode: str, extra_words: str="" ) -> tuple[str, str]:
        """
        Process contact information requests.
        
        Requires:
            - raw_transcription is a string
            - mode is a valid mode string
            - Contact info dictionary is loaded
            
        Ensures:
            - Returns tuple of (raw_transcription, mode)
            - Sets self.results with contact information
            - Handles full address formatting
            - Properly capitalizes names and addresses
            
        Raises:
            - None
        """
        
        # multimodal contact information ___________
        raw_transcription = raw_transcription.lower()
        regex = re.compile( '[^a-zA-Z ]' )
        raw_transcription = regex.sub( '', raw_transcription ).replace( "-", " " )
        # # There could be more words included here, but they're superfluous, we're only looking for the 1st word After three have been stripped out already.
        # contact_info_key = raw_transcription.split()[ 0 ]
        contact_info_key = raw_transcription
        contact_info     = self.contact_info.get( contact_info_key, "N/A" )
        
        print( "contact_info_key:", contact_info_key )
        print( "    contact_info:", contact_info )
        
        if contact_info_key in "full all":
            
            contact_info = "{}\n{}\n{} {}, {}\n{}\n{}".format(
                self.contact_info[ "name" ].title(),
                self.contact_info[ "address" ].title(),
                self.contact_info[ "city" ].title(), self.contact_info[ "state" ].upper(), self.contact_info[ "zip" ],
                self.contact_info[ "email" ],
                self.contact_info[ "telephone" ]
            )
        elif contact_info_key == "city state zip":
        
            contact_info = "{} {}, {}".format(
                self.contact_info[ "city" ].title(), self.contact_info[ "state" ].upper(), self.contact_info[ "zip" ]
            )
        
        elif contact_info_key == "state":
            contact_info = contact_info.upper()
        elif contact_info_key != "email":
            contact_info = contact_info.title()
        
        self.results     = contact_info
        print( "    self.results:", self.results )
        
        return raw_transcription, mode
    def munge_text_proofread( self, raw_transcription: str, mode: str ) -> tuple[str, str]:
        """
        Proofread text transcription.
        
        Requires:
            - raw_transcription is a string
            - mode is a valid mode string
            
        Ensures:
            - Returns tuple of (transcription, mode)
            - Currently delegates to punctuation processing
            
        Raises:
            - None
        """
    
        transcription, mode = self.munge_text_punctuation( raw_transcription, mode )
        
        return transcription, mode
    
    def munge_python_punctuation( self, raw_transcription: str, mode: str ) -> tuple[str, str]:
        """
        Process Python code transcription.
        
        Requires:
            - raw_transcription is a string
            - mode is a valid mode string
            - Punctuation and number dictionaries loaded
            
        Ensures:
            - Returns tuple of (code, mode)
            - Handles Python-specific punctuation
            - Processes numbers and digits
            - Normalizes spacing for code
            
        Raises:
            - None
        """
    
        code = raw_transcription.lower()
        print( "BEFORE code:", code )

        # Remove "space, ", commas, and periods.
        code = re.sub( r'space, |[,-]', '', code.lower() )
        # print( ",.", code )

        # Translate punctuation mark words into single characters.
        for key, value in self.punctuation.items():
            code = code.replace( key, value )
        # print( "punct", code )
        
            # Decode numbers
        for key, value in self.numbers.items():
            code = code.replace( key, value )
        # print( "numbers", code )
        
        # Remove space between any two single digits
        code = re.sub( r"(?<=\d) (?=\d)", "", code )
        # print( "single digits", code)
        
        # remove exactly one space between individual letters too
        # code = re.sub( r'(?<=\w) (?=\w)', '', code )
        # print( "letters", code )
        
        # Remove extra spaces around punctuation.
        code = self._remove_spaces_around_punctuation( code )
        # print( "punct spaces", code )
        
        # Remove extra spaces.
        # code = " ".join( code.split() )
        
        code = self._remove_dashed_spellings( code )
        
        print( "AFTER code:", code )
        
        return code, mode
    
    # def munge_python_proofread( self, raw_transcription, mode ):
    #
    #     code, mode = self.munge_python_punctuation( raw_transcription, mode )
    #
    #     # lupin_client = LupinClient( debug=True )
    #     # timer = sw.Stopwatch()
    #     # preamble = "You are an expert Software engineer specializing in python. Please proofread the following code fragments Generated by voice transcription software and make any necessary corrections So that the code is syntactically valid."
    #     # proofread_code = lupin_client.ask_chat_gpt_text( code, preamble=preamble )
    #     # timer.print( "Proofread", use_millis=True )
    #     # print( "PRE: ",proofread_code )
    #     # proofread_code = self._extract_string_from_backticked_llm_output( proofread_code, tag_name="python" )
    #     # print( "POST:", proofread_code )
    #
    #     tgi_url = self.config_mgr.get( "deepily inference chat url" )
    #     du.print_banner( "tgi_url: [{}]".format( tgi_url ) )
    #
    #     python_prompt_template = du.get_file_as_string( du.get_project_root() + "/src/conf/prompts/python-proofreading-template.txt" )
    #     python_prompt = python_prompt_template.format( voice_command=code )
    #     xml_ftp_generator = XmlFineTuningPromptGenerator( tgi_url=tgi_url, debug=False, silent=True, init_prompt_templates=False )
    #
    #     response = xml_ftp_generator.query_llm_tgi( python_prompt, model_name="Phind-CodeLlama-34B-v2", max_new_tokens=1024, temperature=0.25, top_k=10, top_p=0.9, silent=False )
    #     response = du_xml.strip_all_white_space( response )
    #     print( response )
    #     python = du_xml.get_value_by_xml_tag_name( response, "python" )
    #     print( python )
    #
    #     return python, mode
    
    def _extract_string_from_backticked_llm_output( self, raw_string: str, tag_name: str="python" ) -> str:
        """
        Extract code from markdown-style backticks.
        
        Requires:
            - raw_string is a string
            - tag_name is a valid language identifier
            
        Ensures:
            - Returns extracted code if found
            - Returns raw_string if extraction fails
            - Handles triple backtick markdown format
            
        Raises:
            - None (catches all exceptions)
        """
        
        try:
            return raw_string.split( "```" + tag_name )[ 1 ].split( "```" )[ 0 ].strip()
        except:
            print( f"Error extracting string from ```{tag_name} ...CODE...```, returning raw_string" )
            return raw_string
    
    def munge_sql_punctuation( self, raw_transcription: str, mode: str ) -> tuple[str, str]:
        """
        Apply SQL-specific punctuation transformations.
        
        Requires:
            - raw_transcription is a string containing SQL code
            - mode indicates SQL-specific processing
            - Punctuation and number dictionaries loaded
            
        Ensures:
            - Returns tuple of (sql_code, mode)
            - Converts spoken symbols to SQL syntax
            - Processes numbers and digits
            - Normalizes spaces and punctuation
            
        Raises:
            - None (handles all input gracefully)
        """
        code = raw_transcription.lower()
        print( "BEFORE sql:", code )
        
        # Remove commas, and periods.
        code = re.sub( r'|[,-]', '', code.lower() )
        # print( ",.", code )
        
        # Translate punctuation mark words into single characters.
        for key, value in self.punctuation.items():
            code = code.replace( key, value )
        # print( "punct", code )
        
            # Decode numbers
        for key, value in self.numbers.items():
            code = code.replace( key, value )
        # print( "numbers", code )
        
        # Remove space between any two single digits
        code = re.sub( r"(?<=\d) (?=\d)", "", code )
        # print( "single digits", code )
        
        # remove exactly one space between individual letters too
        # code = re.sub( r'(?<=\w) (?=\w)', '', code )
        
        # Remove extra spaces from punctuation.
        code = self._remove_spaces_around_punctuation( code )
        
        # Remove extra spaces.
        # code = " ".join( code.split() )
        
        code = self._remove_dashed_spellings( code )
        
        print( "AFTER sql:", code )
        
        return code, mode
    # def do_ddg_search( self, raw_transcription, mode ):
    #
    #     transcription, mode = self.munge_text_punctuation( raw_transcription, mode )
    #
    #     if "this information" in transcription:
    #         print( "KLUDGE: 'THIS information' munged into 'DISinformation'" )
    #         transcription = transcription.replace( "this information", "disinformation" )
    #
    #     return transcription, mode
    
    # def do_run_prompt( self, raw_transcription, mode ):
    #
    #     # Not doing much preparation work here. For the moment.
    #     raw_transcription = raw_transcription.lower()
    #
    #     return raw_transcription, mode
    
    def is_text_proofread( self ) -> bool:
        """
        Check if current mode is text proofreading.
        
        Requires:
            - self.mode is initialized
            
        Ensures:
            - Returns True if mode is trans_mode_text_proofread
            - Returns False otherwise
            
        Raises:
            - None
        """
        return self.mode == trans_mode_text_proofread
    
    def is_ddg_search( self ) -> bool:
        """
        Check if current mode is DuckDuckGo search.
        
        Requires:
            - self.mode is initialized
            
        Ensures:
            - Returns True if mode is trans_mode_server_search
            - Returns False otherwise
            
        Raises:
            - None
        """
        return self.mode == trans_mode_server_search
    
    def is_run_prompt( self ) -> bool:
        """
        Check if current mode is run prompt.
        
        Requires:
            - self.mode is initialized
            
        Ensures:
            - Returns True if mode is trans_mode_run_prompt
            - Returns False otherwise
            
        Raises:
            - None
        """
        return self.mode == trans_mode_run_prompt
    
    def is_agent( self ) -> bool:
        """
        Check if current mode is voice command agent.
        
        Requires:
            - self.mode is initialized
            
        Ensures:
            - Returns True if mode is trans_mode_vox_cmd_agent
            - Returns False otherwise
            
        Raises:
            - None
        """
        return self.mode == trans_mode_vox_cmd_agent
    
    def _is_match( self, transcription: str ) -> tuple[bool, dict]:
        """
        Check if transcription matches any known command.
        
        Requires:
            - transcription is a non-empty string
            - self.command_strings is initialized
            
        Ensures:
            - Returns tuple of (is_match, command_dict)
            - Checks for exact and startswith matches
            - Populates command_dict with match details
            
        Raises:
            - None
        """
        # set default values
        command_dict = self._get_command_dict( confidence=100.0 )
        
        for command in self.command_strings:
            
            if transcription == command:
                
                print( "EXACT MATCH: Transcription [{}] == command [{}]".format( transcription, command ) )
                command_dict[ "command"    ] = command
                command_dict[ "match_type" ] = "string_matching_exact"
                
                return True, command_dict
                
            elif transcription.startswith( command ):
                
                print( "Transcription [{}] STARTS WITH command [{}]".format( transcription, command ) )
                
                # Grab the metadata associated with this command: Strip out the command and use the remainder as the arguments
                command_dict[ "args"       ] = [ transcription.replace( command, "" ).strip() ]
                command_dict[ "command"    ] = command
                command_dict[ "match_type" ] = "string_matching_startswith"
                
                return True, command_dict
            
        
        print( "NO exact match        [{}]".format( transcription ) )
        print( "NO startswith() match [{}]".format( transcription ) )
        
        return False, command_dict
    
    def _get_command_dict( self, command: str="none", confidence: float=0.0, args: list[str]=[ "" ], match_type: str="none" ) -> dict:
        """
        Create a dictionary with command metadata.
        
        Requires:
            - All parameters have valid values
            
        Ensures:
            - Returns dictionary with command metadata
            - Contains match_type, command, confidence, args fields
            
        Raises:
            - None
        """
        command_dict = {
            "match_type": match_type,
               "command": command,
            "confidence": confidence,
                  "args": args,
        }
        return command_dict
    
    def _get_ai_command( self, transcription: str ) -> dict:
        """
        Use LLM to determine command from transcription.
        
        Requires:
            - transcription is a non-empty string
            - Config manager has necessary LLM settings
            - Voice command prompt template exists
            
        Ensures:
            - Returns command_dict with AI-determined command
            - Uses LLM to parse transcription into command and args
            - Extracts XML-formatted response
            
        Raises:
            - FileNotFoundError if prompt template missing
            - LLM errors propagated
        """
        # Add runtime switch or configuration to allow for TGI service to be used also.
        command_dict    = self._get_command_dict( match_type="ai_matching", confidence=-1.0 )
        
        template_path   = du.get_project_root() + self.config_mgr.get( "vox command prompt path wo root" )
        prompt_template = du.get_file_as_string( template_path )
        prompt          = prompt_template.format( voice_command=transcription )
        
        model         = self.config_mgr.get( "router and vox command model" )
        is_completion = self.config_mgr.get( "router and vox command is completion", return_type="boolean", default=False )
        
        factory  = LlmClientFactory( debug=self.debug, verbose=self.verbose )
        llm      = factory.get_client( model, debug=self.debug, verbose=self.verbose )
        response = llm.run( prompt )
        
        if self.debug: print( f"LLM response: [{response}]" )

        # Parse results using Pydantic CommandResponse model
        try:
            parsed = CommandResponse.from_xml( response )
            command_dict[ "command" ] = parsed.command
            command_dict[ "args"    ] = [ parsed.args or "" ]
            if self.debug: print( f"Pydantic parsing extracted: command='{parsed.command}', args='{parsed.args}'" )
        except XMLParsingError as e:
            if self.debug: print( f"XML parsing failed: {e}" )
            command_dict[ "command" ] = "unknown"
            command_dict[ "args"    ] = [ "" ]
        except Exception as e:
            if self.debug: print( f"Unexpected error during XML parsing: {e}" )
            command_dict[ "command" ] = "unknown"
            command_dict[ "args"    ] = [ "" ]

        return command_dict
    
    def extract_args( self, raw_text: str, model: str="NO_MODEL_SPECIFIED" ) -> list[str]:
        """
        Extract arguments from text using OpenAI completion.
        
        Requires:
            - raw_text is a string containing potential arguments
            - model is a valid OpenAI model identifier
            - OpenAI API key is available
            
        Ensures:
            - Returns list of extracted arguments
            - Uses deterministic temperature for consistent results
            - Stops at newline for clean extraction
            
        Raises:
            - OpenAI API errors propagated
        """
        openai.api_key = du.get_api_key( "openai" )
        # openai.api_key = os.getenv( "FALSE_POSITIVE_API_KEY" )
        
        if self.debug:
            print( " raw_text [{}]".format( raw_text ) )
            # print( "Using FALSE_POSITIVE_API_KEY [{}]".format( os.getenv( "FALSE_POSITIVE_API_KEY" ) ) )
        
        timer = sw.Stopwatch()
        print( "Calling [{}]...".format( model ), end="" )
        response = openai.completions.create(
            model=model,
            prompt=raw_text + "\n\n###\n\n",
            # From: https://community.openai.com/t/cheat-sheet-mastering-temperature-and-top-p-in-chatgpt-api-a-few-tips-and-tricks-on-controlling-the-creativity-deterministic-output-of-prompt-responses/172683
            temperature=0.0,
            top_p=0.0,
            max_tokens=12,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            stop=["\n"]
        )
        timer.print( "Calling [{}]... Done!".format( model ), use_millis=True, end="\n" )
        
        if self.debug: print( response )
        
        response = response.choices[ 0 ].text.strip()
        print( "extract_args response [{}]".format( response ) )
        
        return [ response ]
        
    def _get_command_strings( self ) -> list[str]:
        """
        Load command strings from configuration file.
        
        Requires:
            - constants.js file exists at specified path
            - File contains command definitions
            
        Ensures:
            - Returns list of command strings sorted by length (longest first)
            - Filters out non-command lines
            - Removes quotes and formatting
            
        Raises:
            - FileNotFoundError if constants.js missing
        """
        command_strings = du.get_file_as_list( du.get_project_root() + "/src/conf/constants.js", lower_case=True, clean=True )
        vox_commands = [ ]
        
        for command in command_strings :
            
            # Skip comments and other lines that don't split into two pieces.
            if len( command.split( " = " ) ) == 1:
                continue
            
            match = command.split( " = " )[ 1 ].strip()
            
            if match.startswith( '"' ) and match.endswith( '";' ) and not match.startswith( '"http' ):
                # Remove quotes and semicolon.
                match = match[ 1 : -2 ]
                vox_commands.append( match )
            else:
                if self.debug and self.verbose: print( "SKIPPING [{}]...".format( match ) )
                
        
        if self.debug and self.verbose:
            # Sort keys alphabetically before printing them out.
            vox_commands.sort()
            for vox_command in vox_commands: print( vox_command )
        
        # Sort the sending order by length of string, longest first.  From: https://stackoverflow.com/questions/60718330/sort-list-of-strings-in-decreasing-order-according-to-length
        vox_commands = sorted( vox_commands, key=lambda command: ( -len( command ), command) )
        
        return vox_commands
    
    def _get_class_dictionary( self ) -> dict:
        """
        Create dictionary mapping class IDs to command descriptions.
        
        Requires:
            - None
            
        Ensures:
            - Returns defaultdict with command mappings
            - Maps numeric strings to command descriptions
            - Defaults to "unknown command" for unmapped keys
            
        Raises:
            - None
        """
        class_dictionary = defaultdict( lambda: "unknown command" )
        # class_dictionary = { }
        class_dictionary[ "0" ] =                    "go to current tab"
        class_dictionary[ "1" ] =                        "go to new tab"
        class_dictionary[ "2" ] =                    "none of the above"
        class_dictionary[ "3" ] =            "search google current tab"
        class_dictionary[ "4" ] =                "search google new tab"
        class_dictionary[ "5" ] =    "search google scholar current tab"
        class_dictionary[ "6" ] =        "search google scholar new tab"
        class_dictionary[ "7" ] =                   "search current tab"
        class_dictionary[ "8" ] =                       "search new tab"
    
        return class_dictionary
    
def quick_smoke_test():
    """Quick smoke test to validate MultiModalMunger functionality."""
    import cosa.utils.util as du

    du.print_banner( "MultiModalMunger Smoke Test", prepend_nl=True )

    # Test different types of multimodal input
    test_cases = [
        {
            "transcription": "Head to NPR.org in a new tab",
            "prefix": "",
            "description": "Browser navigation command"
        },
        {
            "transcription": "multimodal python punctuation console dot log open parentheses one plus one equals two closed parentheses",
            "prefix": "",
            "description": "Python code dictation"
        },
        {
            "transcription": "multimodal text email r-i-c-a-r-d-o dot example at gmail.com",
            "prefix": "",
            "description": "Email address dictation"
        }
    ]

    for i, test_case in enumerate( test_cases, 1 ):
        print( f"\nTest {i}: {test_case['description']}" )
        print( f"Input: '{test_case['transcription']}'" )

        try:
            munger = MultiModalMunger( test_case["transcription"], prefix=test_case["prefix"], debug=False )
            result = munger.get_json()
            print( f"✓ Successfully processed: {result.get('mode', 'unknown mode')}" )
        except Exception as e:
            print( f"✗ Error processing: {e}" )

    # ── Broadcast-mode coverage (added 2026-05-13 by Arnold) ──────────────────
    # Asserts EXACT output values for the new munge_text_broadcast method.
    # See src/rnd/v0.1.7/2026.05.13-broadcast-munger-mode-design.md §5.1.
    du.print_banner( "Broadcast Mode Coverage", prepend_nl=True )
    broadcast_cases = [
        ( "at sign you",                       "@you",                "single @-mention" ),
        ( "hello at noon",                     "hello at noon",       "bare 'at' preserved as English" ),
        ( "at sign you at sign me",            "@you @me",            "multiple @-mentions, inter-word space preserved" ),
        ( "AT SIGN you",                       "@you",                "case-insensitive phrase match" ),
        ( "file_name dot py",                  "file_name.py",        "underscore + dot both preserved (no line-757 strip)" ),
        ( "version 1 dot 0 dot 5",             "version 1.0.5",       "decimals survive (no line-757 strip)" ),
        ( "the URL is example dot com",        "the URL is example.com", "URLs survive (domain lookup + no strip)" ),
        # ── Punctuation coverage (added 2026-05-13 per Rick's voice request) ──
        ( "How are you question mark",         "How are you?",        "'?' via 'question mark' phrase preprocess" ),
        ( "Wow exclamation point",             "Wow!",                "'!' via 'exclamation point' phrase preprocess" ),
        ( "Hi comma friend",                   "Hi, friend",          "',' via single-token 'comma' lookup" ),
        ( "Title colon text",                  "Title: text",         "':' via single-token 'colon' lookup" ),
        ( "yes semicolon thanks",              "yes; thanks",         "';' via single-token 'semicolon' lookup" ),
        ( "Hello period world",                "Hello.world",         "'.' joins identifiers (broadcast intent)" ),
        ( "Wow bang",                          "Wow!",                "'!' via single-token 'bang' lookup" ),
        # ── Ad-hoc cleanup rules (added 2026-05-13 per Rick's voice request) ──
        ( "I am so,,, excited",                "I am so, excited",     "triple-comma run collapses to single comma" ),
        ( "I am so,, excited",                 "I am so, excited",     "double-comma run collapses to single comma" ),
        ( "I am so,,, excited,!.",             "I am so, excited!",    "triple-comma collapse + drop ',!' + drop '!.' cascade" ),
        ( "Wow,!",                             "Wow!",                 "comma-before-bang dropped" ),
        ( "Wow!.",                             "Wow!",                 "period-after-bang dropped" ),
        ( "I am so comma comma comma excited", "I am so, excited",     "spoken-word triple comma also collapses" ),
    ]
    broadcast_pass = 0
    broadcast_fail = 0
    for i, ( transcription, expected, description ) in enumerate( broadcast_cases, 1 ):
        print( f"\nBroadcast {i}: {description}" )
        print( f"  Input:    '{transcription}'" )
        print( f"  Expected: '{expected}'" )
        try:
            munger = MultiModalMunger( transcription, prefix="multimodal text broadcast", debug=False )
            actual = munger.transcription
            print( f"  Actual:   '{actual}'" )
            if actual == expected:
                print( "  ✓ PASS" )
                broadcast_pass += 1
            else:
                print( "  ✗ FAIL" )
                broadcast_fail += 1
        except Exception as e:
            print( f"  ✗ ERROR: {e}" )
            broadcast_fail += 1
    print( f"\nBroadcast summary: {broadcast_pass} passed, {broadcast_fail} failed" )

    print( "\n✓ MultiModalMunger smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()
    
    