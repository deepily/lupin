import re
from typing import Any

import cosa.utils.util as du
from cosa.utils.util_stopwatch import Stopwatch

from transformers import StoppingCriteria, StoppingCriteriaList
import torch

class StopOnTokens( StoppingCriteria ):
    """
    Custom stopping criteria for LLM generation.
    
    Stops generation when specific token sequence is encountered.
    """
    def __init__( self, stop_ids: list[int], device: str="cuda:0" ) -> None:
        """
        Initialize the stopping criteria.
        
        Requires:
            - stop_ids is a list of token IDs to stop on
            - device is a valid PyTorch device string
            
        Ensures:
            - Sets up stop token sequence and device
            
        Raises:
            - None
        """
        self.stop_ids = stop_ids
        self.device   = device

    def __call__( self, input_ids: torch.LongTensor, scores: torch.FloatTensor, **kwargs ) -> bool:
        """
        Check if generation should stop.
        
        Requires:
            - input_ids is a 2D tensor with shape (batch_size, sequence_length)
            - scores is a tensor of generation scores
            
        Ensures:
            - Returns True if stop sequence is found at end of input
            - Returns False if sequence is too short or stop sequence not found
            
        Raises:
            - None
        """
        if len( input_ids[ 0 ] ) < len( self.stop_ids ):
            return False
        # Check if the end of input_ids matches the stop_ids
        if torch.equal( input_ids[ 0 ][ -len( self.stop_ids ): ], torch.tensor( self.stop_ids, device=self.device ) ):
            return True
        return False
    
def query_llm_in_memory( model: Any, tokenizer: Any, prompt: str, device: str="cuda:0", model_name: str="ACME LLMs, Inc.", max_new_tokens: int=128, silent: bool=False, debug: bool=False, verbose: bool=False ) -> str:
    """
    Query an in-memory LLM model.
    
    Requires:
        - model is a loaded transformer model
        - tokenizer is a compatible tokenizer
        - prompt is a non-empty string
        - device is a valid PyTorch device string
        
    Ensures:
        - Generates response using the model
        - Stops on "</response>" sequence
        - Returns cleaned response string
        - Prints timing information unless silent
        
    Raises:
        - None (handles errors gracefully)
    """
    timer = Stopwatch( msg=f"Asking LLM [{model_name}]...".format( model_name ), silent=silent )
    
    inputs         = tokenizer( prompt, return_tensors="pt" ).to( device )
    stop_sequence  = "</response>"
    stop_ids = tokenizer.encode( stop_sequence, add_special_tokens=False )
    stop_on_tokens = StopOnTokens( stop_ids=stop_ids, device=device )
    stopping_criteria = StoppingCriteriaList( [ stop_on_tokens ] )
    
    generation_output = model.generate(
                input_ids=inputs[ "input_ids" ],
           attention_mask=inputs[ "attention_mask" ],
           max_new_tokens=max_new_tokens,
             eos_token_id=tokenizer.eos_token_id,
             pad_token_id=tokenizer.eos_token_id,
        stopping_criteria=stopping_criteria
    )
    
    # Skip decoding the prompt part of the output
    input_length = inputs[ "input_ids" ].size( 1 )
    raw_response = tokenizer.decode( generation_output[ 0 ][ input_length: ], skip_special_tokens=True )
    
    timer.print( msg="Done!", use_millis=True, end="\n" )
    seconds = timer.get_delta_ms() / 1000.0
    tokens_per_second = len( generation_output[ 0 ][ input_length: ] ) / seconds
    print( f"Tokens per second [{round( tokens_per_second, 1 )}] input tokens [{input_length}] + xml response tokens [{len( generation_output[ 0 ][ input_length: ] )}] = total tokens i/o [{len( generation_output[ 0 ] )}]" )
    
    # if debug and verbose:
    #     du.print_banner( "Raw response" )
    #     print( raw_response )
    
    # Remove the <s> and </s> tags
    response = raw_response.replace( "</s><s>", "" ).strip()
    # Remove white space outside XML tags
    response = re.sub( r'>\s+<', '><', response )
    
    return response