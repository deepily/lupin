import gc
import sys
import json
import pandas as pd
import argparse
import time
import subprocess
import threading
import requests
import torch, os, multiprocessing
from typing import Optional, Union, List, Dict, Tuple, Any, Iterable

try:
    from peft import LoraConfig, prepare_model_for_kbit_training, PeftModel
    PEFT_AVAILABLE = True
except ImportError:
    PEFT_AVAILABLE = False
    LoraConfig = None
    prepare_model_for_kbit_training = None
    PeftModel = None

from torch.ao.quantization import quantize
from torch.utils.benchmark import timer

from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    set_seed
)
from datasets import Dataset
from datasets.formatting.formatting import LazyBatch

try:
    from trl import SFTTrainer, SFTConfig
    TRL_AVAILABLE = True
except ImportError:
    TRL_AVAILABLE = False
    SFTTrainer = None
    SFTConfig = None

try:
    from auto_round import AutoRoundConfig
    AUTO_ROUND_AVAILABLE = True
except ImportError:
    AUTO_ROUND_AVAILABLE = False
    AutoRoundConfig = None

from huggingface_hub import login

# Import the model configuration loader
from cosa.training.conf.model_config_loader import load_model_config

import cosa.utils.util as du
import cosa.utils.util_pytorch as dupt

import cosa.agents.llm_client as llmc
from cosa.training.quantizer import Quantizer
from cosa.utils.util_stopwatch import Stopwatch

from cosa.training.xml_coordinator import XmlCoordinator

set_seed( 42 )

@staticmethod
def is_root() -> bool:
    """
    Check if the current process is running as root.
    
    Requires:
        - Running on a Unix-like system
        
    Ensures:
        - Returns True if user ID is 0 (root)
        - Returns False otherwise
        
    Raises:
        - AttributeError on non-Unix systems
    """
    return os.geteuid() == 0

@staticmethod
def invoked_with_sudo() -> bool:
    """
    Check if the process was invoked with sudo.
    
    Requires:
        - Environment variables accessible
        
    Ensures:
        - Returns True if SUDO_UID environment variable exists
        - Returns False otherwise
        
    Raises:
        - None
    """
    return "SUDO_UID" in os.environ

@staticmethod
def print_gpu_memory() -> None:
    """
    Print current GPU memory usage and allocation for all available GPUs.
    
    Requires:
        - torch library is imported
        - CUDA is available (optional)
        
    Ensures:
        - Prints memory statistics for each GPU
        - Shows total, allocated, reserved memory in GB
        - Shows utilization percentage
        - Prints message if no GPU available
        
    Raises:
        - None (handles CUDA unavailability)
    """
    
    # Check if CUDA is available
    if not torch.cuda.is_available():
        print( "No CUDA-capable GPU available." )
        return
    
    # Get the number of GPUs
    gpu_count = torch.cuda.device_count()
    print( f"Found {gpu_count} GPU(s):" )
    
    # For each GPU, get and print memory stats
    for gpu_id in range( gpu_count ):
        # Get device properties
        gpu_stats = torch.cuda.get_device_properties( gpu_id )
        
        # Calculate memory metrics (in GB)
        total_memory = round( gpu_stats.total_memory / 1024 / 1024 / 1024, 3 )
        
        # Get per-device memory stats
        with torch.cuda.device( gpu_id ):
            # Get allocated memory (current memory usage)
            allocated_memory = round( torch.cuda.memory_allocated() / 1024 / 1024 / 1024, 3 )
            
            # Get cached/reserved memory (memory reserved by PyTorch allocator)
            reserved_memory = round( torch.cuda.memory_reserved() / 1024 / 1024 / 1024, 3 )
            
            # Get peak memory stats
            max_allocated = round( torch.cuda.max_memory_allocated() / 1024 / 1024 / 1024, 3 )
            max_reserved = round( torch.cuda.max_memory_reserved() / 1024 / 1024 / 1024, 3 )
        
        # Print GPU info and memory stats
        print( f"GPU {gpu_id}: {gpu_stats.name}" )
        print( f"  Total memory:     {total_memory} GB" )
        print( f"  Allocated memory: {allocated_memory} GB (peak: {max_allocated} GB)" )
        print( f"  Reserved memory:  {reserved_memory} GB (peak: {max_reserved} GB)" )
        print( f"  Utilization:      {round(allocated_memory/total_memory * 100, 1)}%" )
    
@staticmethod
def release_gpus( models: Iterable[Any], nuclear_kill_button: bool=False ) -> None:
    """
    Release GPU memory by moving models to CPU and clearing CUDA cache.
    
    Requires:
        - models is an iterable collection of model objects
        - Each model may or may not have a 'cpu' method
        - If nuclear_kill_button, user has appropriate permissions
        
    Ensures:
        - All models moved to CPU if possible
        - Models deleted from memory
        - Garbage collection performed
        - CUDA cache cleared
        - If nuclear_kill_button, GPU processes killed and GPUs reset
        
    Raises:
        - SubprocessError if GPU reset fails
        - Various exceptions if nuclear option fails
    """
    
    du.print_banner( "Releasing GPU memory... BEFORE", prepend_nl=True )
    print_gpu_memory()
    
    for model in models:
        
        # move it to the CPU before deleting it, but test to make sure the attribute actually exists before you do
        model_name = type(model).__name__
        if hasattr( model, 'cpu' ) and callable( getattr( model, 'cpu' ) ):
            print( f"Moving model {model_name} to CPU before deleting it..." )
            model.cpu()
        else:
            print( f"Model {model_name} does not have a 'cpu' method, skipping..." )
        del model
        gc.collect()
        
    torch.cuda.empty_cache()

    # Force GPU reset if nuclear_kill_button is enabled
    if nuclear_kill_button:
        du.print_banner( "NUCLEAR OPTION: Force resetting GPU memory!", prepend_nl=True )
        
        # Get the number of GPUs available
        gpu_count = torch.cuda.device_count()
        print( f"Detected {gpu_count} GPU(s), forcing reset..." )
        
        try:
            # Launch external GPU cleanup but exclude self
            current_pid = os.getpid()
            
            # if they want to nuke the GPU and they're not running as root, then throw in the `sudo` cmd
            if is_root() and invoked_with_sudo():
                sudo_placeholder = ""
            else:
                sudo_placeholder = "sudo "
            cmd = f"{sudo_placeholder}nvidia-smi | grep -E '[0-9]+ +C ' | awk '{{print $5}}' | grep -v {current_pid} | xargs -r sudo kill -9"
            subprocess.run( cmd, shell=True, check=True )
            
            # Reset each GPU individually
            for gpu_id in range( gpu_count ):
                print( f"Resetting GPU {gpu_id}..." )
                subprocess.run( f"sudo nvidia-smi --gpu-reset -i {gpu_id}", shell=True, check=True )
                
            print( "GPU reset completed successfully" )
        except subprocess.CalledProcessError as e:
            print( f"Error during GPU reset: {e}" )
        except Exception as e:
            print( f"Unexpected error during GPU reset: {e}" )

class PeftTrainer:
    """
    Trainer for fine-tuning models using PEFT (Parameter-Efficient Fine-Tuning).
    
    Supports various models with LoRA adapters for efficient fine-tuning.
    """
    def __init__(
            self, model_hf_id: str, model_name: str, test_train_path: str, lora_dir: Optional[str]=None, debug: bool=False, verbose: bool=False
    ) -> None:
        """
        Initialize a new PEFT Trainer instance.
        
        Requires:
            - model_hf_id is a valid Hugging Face model identifier
            - model_name is one of the supported models
            - test_train_path is a valid directory path
            - lora_dir is None or a valid directory path
            
        Ensures:
            - Creates trainer instance with all attributes
            - Validates model name against supported models
            - Prints initialization info
            
        Raises:
            - ValueError if model_name not supported
        """
        du.print_banner( f"Initializing PEFT Trainer for {model_name}", prepend_nl=True )
        print( f"Model ID: {model_hf_id}" )
        print( f"Path to test/train data: {test_train_path}" )
        
        self.debug = debug
        self.verbose = verbose
        self.trainer = None
        self.model = None
        self.model_hf_id = model_hf_id
        self.tokenizer = None
        self.output_dir = None
        self.checkpoint_dir = None
        self.model_name = model_name
        self.test_train_dir = test_train_path
        self.lora_dir = lora_dir
        self.merged_adapter_dir   = None
        self.quantized_model_dir  = None
        self.quantized_model_dirs = {}
        
        # stats tracking
        self.start_gpu_memory = -1
        self.max_memory = -1
        
        # models supported by this trainer
        self.supported_model_names = [ "Mistral-7B-Instruct-v0.2", "Ministral-8B-Instruct-2410",
            "Llama-3.2-3B-Instruct", "Phi-4-mini-instruct", "Qwen3-4B-Base" ]
        
        # Validate the model name
        self._validate_model_name()
    
    def _validate_model_name( self ) -> None:
        """
        Validate the model name against supported models.
        
        Requires:
            - self.model_name is set
            - MODEL_CONFIG_MAP is available
            
        Ensures:
            - Validates model name is in MODEL_CONFIG_MAP
            - Completes without error if valid
            
        Raises:
            - ValueError if model_name not supported
        """
        # Import the model config map which has all supported models
        from cosa.training.conf.model_config_loader import MODEL_CONFIG_MAP
        
        if self.model_name not in MODEL_CONFIG_MAP:
            raise ValueError(
                f"Unsupported model_name: '{self.model_name}'. Must be one of: {', '.join( MODEL_CONFIG_MAP.keys() )}"
                )
        
        # Claude snuck another check in on me, don't know why it thought that I wanted backward compatibility
        # # For backward compatibility, also check supported_model_names
        # if hasattr(self, 'supported_model_names') and self.model_name not in self.supported_model_names:
        #     print(f"Warning: Model '{self.model_name}' not in self.supported_model_names. Updating supported_model_names.")
        #     self.supported_model_names = list(MODEL_CONFIG_MAP.keys())
    
    # Maps model base names to their environment variable names in ~/.lora_env
    LORA_ENV_VAR_MAP = {
        "Ministral-8B-Instruct-2410" : "LUPIN_ROUTER_LORA_MINISTRAL_8B_PATH",
        "Qwen3-4B-Base"              : "LUPIN_ROUTER_LORA_QWEN3_4B_PATH",
        "Llama-3.2-3B-Instruct"     : "LUPIN_ROUTER_LORA_LLAMA_3B_PATH",
    }

    def _update_lora_env( self, env_file_path=None ):
        """
        Update ~/.lora_env with the latest quantized model path for this model.

        Requires:
            - self.model_name is set
            - self.quantized_model_dirs is populated with {bits: path}
            - model_name exists in LORA_ENV_VAR_MAP

        Ensures:
            - ~/.lora_env is updated with new path for this model
            - Other model entries are preserved
            - Header comments and timestamp are updated
            - Prefers 8-bit path if available, falls back to 4-bit

        Raises:
            - IOError if file cannot be written
        """
        from datetime import datetime

        if env_file_path is None:
            env_file_path = os.path.expanduser( "~/.lora_env" )

        # Look up this model's env var name
        env_var_name = self.LORA_ENV_VAR_MAP.get( self.model_name )
        if env_var_name is None:
            print( f"Warning: Model '{self.model_name}' not in LORA_ENV_VAR_MAP, skipping env update" )
            return

        # Pick preferred quantized path: 8-bit > 4-bit
        new_path = self.quantized_model_dirs.get( 8 ) or self.quantized_model_dirs.get( 4 )
        if new_path is None:
            print( f"Warning: No quantized model dirs available for {self.model_name}, skipping env update" )
            return

        # Read existing env file → parse into dict of {VAR_NAME: (value, comment)}
        existing_vars    = {}
        existing_comments = {}
        if os.path.exists( env_file_path ):
            with open( env_file_path, "r" ) as f:
                lines = f.readlines()
            pending_comment = None
            for line in lines:
                stripped = line.strip()
                if stripped.startswith( "#" ) and "export" not in stripped:
                    # Collect comment lines that precede an export
                    pending_comment = stripped
                elif stripped.startswith( "export " ):
                    # Parse: export VAR_NAME="value"
                    rest = stripped[ len( "export " ): ]
                    eq_idx = rest.find( "=" )
                    if eq_idx > 0:
                        var_name = rest[ :eq_idx ]
                        var_val  = rest[ eq_idx + 1: ].strip( '"' )
                        existing_vars[ var_name ] = var_val
                        if pending_comment:
                            existing_comments[ var_name ] = pending_comment
                    pending_comment = None
                else:
                    pending_comment = None

        # Update the dict with new path
        existing_vars[ env_var_name ] = new_path

        # Default comments for known models
        default_comments = {
            "LUPIN_ROUTER_LORA_MINISTRAL_8B_PATH" : "# Ministral 8B — production router",
            "LUPIN_ROUTER_LORA_QWEN3_4B_PATH"     : "# Qwen3 4B — backup router",
            "LUPIN_ROUTER_LORA_LLAMA_3B_PATH"      : "# Llama 3.2 3B — experimental",
        }

        # Write back with header, per-model comments, and timestamp
        timestamp = datetime.now().strftime( "%Y-%m-%d" )
        out_lines = []
        out_lines.append( "# LoRA model paths — auto-updated by peft_trainer.py after successful training runs" )
        out_lines.append( "# Sourced by ~/.bashrc — changes take effect on next shell or `source ~/.bashrc`" )
        out_lines.append( f"# Last updated: {timestamp}" )
        out_lines.append( "" )

        for var_name, var_val in existing_vars.items():
            comment = existing_comments.get( var_name ) or default_comments.get( var_name )
            if comment:
                out_lines.append( comment )
            out_lines.append( f'export {var_name}="{var_val}"' )
            out_lines.append( "" )

        with open( env_file_path, "w" ) as f:
            f.write( "\n".join( out_lines ) )

        if self.debug: print( f"Updated {env_file_path}: {env_var_name}={new_path}" )

    def login_to_hf( self ) -> None:
        """
        Authenticate with Hugging Face API.
        
        Requires:
            - LUPIN_ROOT environment variable set
            - Valid HF token accessible via du.get_api_key
            
        Ensures:
            - Authenticates with Hugging Face
            - Prints confirmation message
            
        Raises:
            - KeyError if token not found
            - FileNotFoundError if token file missing
            - HF login exceptions
        """
        hf_token = du.get_api_key( "huggingface", project_root=os.getenv( "LUPIN_ROOT" ) )
        print( f"Logging in to Hugging Face with token [{hf_token}]... ", end="" )
        login( token=hf_token )
        print( "Done!" )
    
    def get_training_prompt_stats( self, backend: str="cuda", device_map: str="auto", device: str="cuda:1", debug: bool=False,
                                   verbose: bool=False
                                   ) -> tuple[dict[str, float], dict[str, float]]:
        """
        Analyze token and word statistics of training prompts.
        
        Requires:
            - Model and tokenizer available or loadable
            - Training dataset exists at expected path
            - Dataset has 'instruction', 'input', 'output' columns
            
        Ensures:
            - Calculates min, max, mean for tokens and words
            - Returns statistics as two dictionaries
            - Prints debug info if enabled
            
        Raises:
            - FileNotFoundError if dataset missing
            - KeyError if required columns missing
        """
        self._load_model_and_tokenizer( backend=backend, device_map=device_map, mode="training" )
        
        df = pd.read_json( f"/{self.test_train_dir}/voice-commands-xml-train.jsonl", lines=True
                           )  # .sample( 1000, random_state=42 )
        
        token_stats = { "min": -1, "max": -1, "mean": -1 }
        word_stats = { "min": -1, "max": -1, "mean": -1 }
        
        token_counts = [ ]
        word_counts = [ ]
        counter = 0
        for row in df.itertuples():
            
            prompt = self.get_prompt( getattr( row, "instruction" ), getattr( row, "input" ),
                                      output=getattr( row, "output" )
                                      )
            tokens_metadata = self.tokenizer( prompt, return_tensors="pt" ).to( device )
            
            tokens_count = len( tokens_metadata[ "input_ids" ][ 0 ] )
            word_count = len( prompt.split( ' ' ) )
            
            token_counts.append( tokens_count )
            word_counts.append( word_count )
            if debug and verbose:
                print( f"  Word count: {len( prompt.split( ' ' ) )}" )
                print( f"Tokens count: {tokens_count}" )
                # print( tokens_metadata[ "input_ids" ] )
            else:
                counter += 1
                if counter % 100 == 0: print( ".", end="" )
        
        print()
        
        token_stats[ "min" ] = min( token_counts )
        token_stats[ "max" ] = max( token_counts )
        token_stats[ "mean" ] = sum( token_counts ) / len( token_counts )
        
        word_stats[ "min" ] = min( word_counts )
        word_stats[ "max" ] = max( word_counts )
        word_stats[ "mean" ] = sum( word_counts ) / len( word_counts )
        
        if self.debug:
            du.print_banner( "Token stats", prepend_nl=True )
            print( token_stats )
            du.print_banner( "Last prompt" )
            print( prompt )
        
        return token_stats, word_stats
    
    def fine_tune( self, batch_size: int=8, gradient_accumulation_steps: int=1, logging_steps: float=0.05, eval_steps: float=0.20,
    sample_size: float=1.0, device_map: str="auto", output_dir: str="./results"
    ) -> str:
        """
        Fine-tune the model using PEFT techniques.
        
        Requires:
            - Model and tokenizer available or loadable
            - Valid test/train datasets accessible
            - Sufficient GPU memory for batch size and model
            
        Ensures:
            - Model is fine-tuned with given parameters
            - Checkpoints saved to output directory
            - Training stats displayed
            - Updates self.output_dir and self.checkpoint_dir
            - Returns path to last checkpoint
            
        Raises:
            - CUDA out of memory if insufficient GPU
            - FileNotFoundError if datasets missing
        """
        du.print_banner( f"Fine-tuning model {self.model_name} with PEFT", prepend_nl=True )
        run_start = f"Run started @ {du.get_current_time( format='%H:%M' )}"
        print( run_start )
        timer = Stopwatch( msg=None )
        
        self._load_model_and_tokenizer( device_map=device_map, mode="training" )
        
        # I used this when loading a quantized model. Since I'm not quantizing now, it's commented out
        # self.model         = prepare_model_for_kbit_training( self.model, gradientoow_checkpointing_kwargs={'use_reentrant': True} )
        peft_config = self._get_peft_config()
        training_arguments = self._get_training_args( output_dir=output_dir, batch_size=batch_size,
                                                      gradient_accumulation_steps=gradient_accumulation_steps,
                                                      logging_steps=logging_steps, eval_steps=eval_steps
                                                      )
        test_train_data = self._get_test_train_data( sample_size=sample_size )
        
        du.print_banner( "Training data", prepend_nl=True )
        print( test_train_data[ "train" ] )
        du.print_banner( "Validation data", prepend_nl=True )
        print( test_train_data[ "test" ] )
        
        self.trainer = SFTTrainer(
            # self.trainer = MyKludgySFTTrainer(
            
            # workaround for buggy safe tensors behavior when a model is loaded across multiple GPUs
            # save_safetensors=False,
            model=self.model,
            train_dataset=test_train_data[ "train" ],
            eval_dataset=test_train_data[ "test" ],
            peft_config=peft_config,
            processing_class=self.tokenizer,
            args=training_arguments,
            # packing=False,
            formatting_func=self._format_prompt,
        )
        
        self._print_trainable_parameters()
        self._print_stats_pre()
        self.trainer.train()
        self._print_stats_post()
        print( run_start )
        print( f"Run completed @ {du.get_current_time( format='%H:%M' )}" )
        timer.print( msg=None )
        
        print( f"LORA checkpoints stashed here [{training_arguments.output_dir}]" )
        # the output directory contains the original lora_dir + date and time, and also now contains...
        self.output_dir = training_arguments.output_dir
        # ...the last checkpoint directory created by the fine-tuning job
        self.checkpoint_dir = self._get_last_checkpoint_dir( training_arguments.output_dir )
        
        du.print_banner( f"Last checkpoint: {self.checkpoint_dir}" )
        du.print_simple_file_list( self.checkpoint_dir )
        
        return self.checkpoint_dir
    
    def get_last_checkpoint_dir( self ) -> Optional[str]:
        """
        Get path to last checkpoint from recent fine-tuning.
        
        Requires:
            - Fine-tuning has been completed
            - self.checkpoint_dir has been set
            
        Ensures:
            - Returns checkpoint directory path
            - Returns None if no fine-tuning done
            
        Raises:
            - None
        """
        return self.checkpoint_dir
    
    def _get_last_checkpoint_dir( self, output_dir: str ) -> Optional[str]:
        """
        Find the most recent checkpoint directory.
        
        Requires:
            - output_dir is valid directory path
            - Checkpoints follow 'checkpoint-N' naming
            
        Ensures:
            - Returns path to highest numbered checkpoint
            - Returns None if no checkpoints found
            
        Raises:
            - OSError if directory access fails
        """
        # List all subdirectories in the output directory
        subdirs = [ d for d in os.listdir( output_dir ) if os.path.isdir( os.path.join( output_dir, d ) ) ]
        
        # Filter out checkpoint directories
        checkpoint_dirs = [ d for d in subdirs if d.startswith( 'checkpoint-' ) ]
        
        # Sort checkpoint directories by their step number
        checkpoint_dirs.sort( key=lambda x: int( x.split( '-' )[ -1 ] ) )
        
        # Get the path to the last checkpoint directory in the list
        last_checkpoint_dir = os.path.join( output_dir, checkpoint_dirs[ -1 ] ) if checkpoint_dirs else None
        
        return last_checkpoint_dir
    
    def save_model( self ) -> None:
        """
        Save current model and tokenizer with timestamp.
        
        Requires:
            - self.output_dir is valid directory path
            - self.model and self.tokenizer initialized
            
        Ensures:
            - Saves to timestamped subdirectory
            - Preserves original working directory
            - Uses safe_serialization=False
            - Directory named: final-{date}-at-{time}
            
        Raises:
            - OSError if directory creation fails
        """
        date = du.get_current_date()
        time = du.get_current_time( format='%H-%M', include_timezone=False )
        path = f"{self.output_dir}/final-{date}-at-{time}"
        if not os.path.exists( path ):
            print( f"Creating output directory {path}..." )
            os.makedirs( path )
            print( f"Creating output directory {path}... Done!" )
        
        # get the current working directory
        cwd = os.getcwd()
        # change directory to save adapter
        os.chdir( path )
        
        # try/finally: the cwd is PROCESS-global. Restoring it only on the happy path
        # leaks the directory change into everything that runs after a save failure.
        try:
            print( f"Saving MODEL to {path}..." )
            self.model.save_pretrained( path, safe_serialization=False )
            print( f"Saving MODEL to {path}... Done!" )
            
            print( f"Saving TOKENIZER to {path}..." )
            self.tokenizer.save_pretrained( path )
            print( f"Saving TOKENIZER to {path}... Done!" )
        finally:
            # change back to the original working directory
            os.chdir( cwd )
    
    def _load_adapter( self, adapter_path: str ) -> None:
        """
        Load PEFT adapter and apply to model.
        
        Requires:
            - self.model is initialized
            - adapter_path is valid path to adapter
            
        Ensures:
            - Adapter loaded and applied
            - self.model becomes PeftModel instance
            
        Raises:
            - FileNotFoundError if adapter missing
        """
        print( f"Loading adapter from {adapter_path}" )
        self.model = PeftModel.from_pretrained( self.model, adapter_path )
        print( f"Loading adapter from {adapter_path}... Done!" )
    
    def run_validation( self, banner_prefix: str="",
            model: Optional[Any]=None, switch: str="", path_prefix: str="/var/model/lupin",
            device_map: dict={ "": 0 }, validation_sample_size: int=1000, debug: Optional[bool]=None, verbose: Optional[bool]=None,
            vllm_base_url: Optional[str]=None
    ) -> pd.DataFrame:
        """
        Run validation against model server.
        
        Requires:
            - Validation dataset at expected path
            - Model instance provided
            - Tokenizer available
            
        Ensures:
            - Performs validation on sample set
            - Computes and displays results
            - Returns DataFrame with metrics
            
        Raises:
            - ValueError if model is None
            - FileNotFoundError if dataset missing
        """
        # set debug and verbose to the class defaults if not provided
        if debug is not None: self.debug = debug
        if verbose is not None: self.verbose = verbose
        
        if model is None:
            raise ValueError( "Model must be provided" )
        # # this is dangerous?
        # else:
        #     self.model = model
        
        du.print_banner( f"{banner_prefix} Testing model [{model}]".strip(), prepend_nl=True )
        
        df = pd.read_json(
            f"{self.test_train_dir}/voice-commands-xml-validate.jsonl", lines=True
        )
        # Stratified sampling: equal representation per command for balanced validation
        num_commands       = df[ "command" ].nunique()
        samples_per_command = max( 1, validation_sample_size // num_commands )
        df = df.groupby( "command" ).apply(
            lambda x: x.sample( min( len( x ), samples_per_command ), random_state=42 ),
            include_groups=False
        ).droplevel( 1 ).reset_index()
        print( f"Stratified validation: {samples_per_command} samples/command, {len( df )} total from {num_commands} commands" )
        
        # update the prompt field
        # KLUDGE: this is a workaround for the fact that the prompt field is not being created when the validation df is created
        print( f"Updating the prompt field for [{validation_sample_size}] rows..." )
        df[ "prompt" ] = df.apply(
            lambda row: self.get_prompt( row[ "instruction" ], row[ "input" ], output="" ), axis=1
        )
        print( f"Updating the prompt field for [{validation_sample_size}] rows... Done!" )
        
        du.print_banner( f"Testing {self.model_name} w/ {validation_sample_size} samples via vLLM server...", prepend_nl=True )
        # Print value counts for the command column to see how many unique commands we have
        print( df.command.value_counts(), end="\n\n" )
        
        xml_coordinator = XmlCoordinator( path_prefix=path_prefix, debug=debug, verbose=verbose )
        
        # generate responses
        df = xml_coordinator.generate_responses(
            df, model=model, model_name=self.model_name, device=device_map, max_new_tokens=128, debug=debug, verbose=verbose,
            vllm_base_url=vllm_base_url
        )
        # validate responses
        df = xml_coordinator.validate_responses( df )
        # print validation stats using the coordinator
        xml_coordinator.print_validation_stats( df, title=f"Validation stats for model {self.model_name}" )

        # Build results dict for consolidated dashboard
        stage_name  = banner_prefix.strip().rstrip( ":" ) if banner_prefix else "Unknown"
        stats_dict  = xml_coordinator.response_validator.get_validation_stats( df )
        ms_per_item = xml_coordinator.last_ms_per_item

        return {
            "df"          : df,
            "stats"       : stats_dict,
            "ms_per_item" : ms_per_item,
            "stage"       : stage_name
        }
    
    def load_and_merge_adapter( self, checkpoint_dir: Optional[str]=None, device_map: dict={ "": 0 } ) -> None:
        """
        Load PEFT adapter and merge with base model.
        
        Requires:
            - Model available or loadable
            - Valid adapter path provided or in self.checkpoint_dir
            
        Ensures:
            - Model loaded if needed
            - Adapter loaded and merged
            - self.model contains merged model
            
        Raises:
            - ValueError if no adapter path available
        """
        du.print_banner( f"Load and merge adapter {checkpoint_dir}" )
        self._load_model_and_tokenizer( device_map=device_map, mode="inference" )
        
        if checkpoint_dir is not None:
            self.checkpoint_dir = checkpoint_dir
        elif self.checkpoint_dir is None:
            raise ValueError( "No adapter path provided or found" )
        
        print( f"Loading adapter from {self.checkpoint_dir}... ", end="" )
        self.model = PeftModel.from_pretrained( self.model, self.checkpoint_dir )
        print( "Done!" )
        
        print( "Merging adapter... ", end="" )
        self.model = self.model.merge_and_unload()
        print( "Done!" )
    
    def save_merged_adapter( self, lora_dir: Optional[str]=None ) -> str:
        """
        Save merged model and tokenizer with timestamp.
        
        Requires:
            - Model loaded and merged with adapter
            - Valid directory path in lora_dir or self.lora_dir
            
        Ensures:
            - Saves to timestamped subdirectory
            - Updates self.merged_adapter_dir
            - Returns path to saved adapter
        
        Parameters:
        - lora_dir (str, optional): Base directory where the merged adapter will be saved. 
          If None, uses self.lora_dir. Defaults to None.
        
        Returns:
        - str: Path to the directory where the merged adapter was saved.
        
        Raises:
        - ValueError: If lora_dir is not provided and self.lora_dir is not set.
        """
        if lora_dir is not None:
            self.lora_dir = lora_dir
        elif self.lora_dir is None:
            raise ValueError( "lora_dir directory is neither provided nor found" )
        
        du.print_banner( f"Save merged adapter to {self.lora_dir}" )
        
        date = du.get_current_date()
        time = du.get_current_time( format='%H-%M', include_timezone=False )
        path = f"{self.lora_dir}/merged-on-{date}-at-{time}"
        
        if not os.path.exists( path ):
            print( f"Creating output directory {path}... ", end="" )
            os.makedirs( path )
            print( "Done!" )
        
        print( f"Saving merged adapter to {path}... ", end="" )
        self.model.save_pretrained( path )
        self.tokenizer.save_pretrained( path )
        print( "Done!" )
        
        self.merged_adapter_dir = path
        
        du.print_banner( f"Contents of: {self.merged_adapter_dir}" )
        du.print_simple_file_list( self.merged_adapter_dir )
        
        return self.merged_adapter_dir
    
    def quantize_merged_adapter( self, merged_adapter_dir: Optional[str]=None, bits: int=4 ) -> str:
        """
        Quantize merged model to reduce size and memory.

        Requires:
            - Valid merged adapter path provided or in self.merged_adapter_dir
            - Quantizer class properly implemented
            - GPU available for quantization
            - bits is a positive integer (typically 4 or 8)

        Ensures:
            - Quantizes model using Quantizer at the specified bit width
            - Saves quantized model to disk
            - Updates self.quantized_model_dir and self.quantized_model_dirs[bits]
            - Returns path to quantized model

        Raises:
            - ValueError if no adapter path available
            - RuntimeError if no GPU or quantization fails
        """
        # sanity check
        if merged_adapter_dir is not None:
            self.merged_adapter_dir = merged_adapter_dir
        elif self.merged_adapter_dir is None:
            raise ValueError( "merged_adapter_dir is neither provided nor found" )

        try:
            # Detect available GPUs
            num_gpus = torch.cuda.device_count()
            if num_gpus == 0:
                raise RuntimeError( "No GPUs available for quantization" )

            # Use specific device mapping rather than "auto" to avoid meta device issues
            if num_gpus == 1:
                # Use a specific device (cuda:0) instead of "auto" to prevent meta device placement
                device_map = "cuda:0"
                if self.debug: print( f"Using single GPU with device_map={device_map}" )
            else:
                # For multi-GPU setup, only use first GPU to avoid meta device issues
                device_map = "cuda:0"
                if self.debug: print( f"Multiple GPUs detected but using only first GPU with device_map={device_map}" )

            du.print_banner( f"Quantizing merged adapter ({bits}-bit) in {self.merged_adapter_dir}", prepend_nl=True )

            # Initialize quantizer with specific device mapping
            quantizer = Quantizer( self.merged_adapter_dir, device_map=device_map, local_files_only=True )

            # Quantize with appropriate batch size for the GPU
            batch_size = 1  # Conservative batch size to prevent OOM
            quantizer.quantize_model( batch_size=batch_size, bits=bits )

            # Save the quantized model
            quantized_dir = quantizer.save( self.merged_adapter_dir, include_model_name=False )

            # Track both single and multi-quant paths
            self.quantized_model_dir = quantized_dir
            if not hasattr( self, "quantized_model_dirs" ):
                self.quantized_model_dirs = {}
            self.quantized_model_dirs[ bits ] = quantized_dir

            # Release quantizer GPU memory before returning — explicitly dismantles
            # the autoround → model reference web, moves model to CPU, then clears cache.
            # This ensures reserved GPU memory is actually freed (not just dereferenced).
            du.print_banner( "Releasing quantizer GPU memory...", prepend_nl=True )
            print_gpu_memory()
            quantizer.release_gpu_memory()
            del quantizer
            gc.collect()
            torch.cuda.empty_cache()
            if not self._wait_for_gpu_memory_release():
                print( "Attempting forced GPU cache clear..." )
                torch.cuda.empty_cache()
                gc.collect()
                time.sleep( 5 )
            du.print_banner( "Releasing quantizer GPU memory... AFTER", prepend_nl=True )
            print_gpu_memory()

            return quantized_dir
        
        except Exception as e:
            error_msg = f"Quantization failed: {str( e )}"
            if self.debug:
                import traceback
                traceback.print_exc()
                print( f"ERROR: {error_msg}" )
            raise RuntimeError( error_msg ) from e
    
    def _load_model_and_tokenizer( self, device_map: Union[str, dict]="auto", mode: Optional[str]=None ) -> None:
        """
        Load model and tokenizer for training or inference.
        
        Requires:
            - HF_HOME environment variable set
            - Model available locally in HF cache
            - mode is "training" or "inference"
            
        Ensures:
            - Loads model with mode-specific settings
            - Configures tokenizer for model type
            - Preserves working directory
            - No-op if already loaded
            
        Raises:
            - ValueError if HF_HOME not set
            - ValueError if invalid mode
        """
        # Quick sanity checks
        if "HF_HOME" not in os.environ:
            raise ValueError( "Environment variable HF_HOME must be set, try calling trainer.set_hf_env_vars() first?" )
        
        if mode is None or mode not in [ "training", "inference" ]:
            raise ValueError( "Mode MUST be specified, either 'training' or 'inference'" )
        
        torch_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        attn_implementation = "flash_attention_2"
        cache_dir = os.getenv( "HF_HOME" ) + "/hub"
        original_cwd = os.getcwd()
        # quantization_config = AutoRoundConfig( backend=backend )
        
        # try/finally: the cwd is PROCESS-global. Restoring it only on the happy path
        # leaks the directory change into everything that runs after a load failure.
        try:
            if self.model is None:
            
                print( f"Loading {self.model_hf_id}..." )
                print( f"Switching from current working directory: {original_cwd}..." )
                os.chdir( os.environ[ "HF_HOME" ] )
                print( f"To new working directory: {os.getcwd()}" )
            
                self.model = AutoModelForCausalLM.from_pretrained(
                    self.model_hf_id, device_map=device_map, low_cpu_mem_usage=True, use_cache=False,
                    torch_dtype=torch_dtype, local_files_only=True, cache_dir=cache_dir,
                    attn_implementation=attn_implementation
                )
            
                if self.debug and self.verbose:
                    dupt.print_device_allocation( self.model )
            else:
                print( "Model already loaded. Skipping" )
        
            if self.tokenizer is None:
            
                self.tokenizer = AutoTokenizer.from_pretrained( self.model_hf_id, force_download=True, from_slow=False )
            
                # Load the model-specific tokenizer configuration
                model_config = load_model_config( self.model_name )
                tokenizer_config = model_config[ "tokenizer" ]
            
                # Apply tokenizer settings from configuration
                pad_token = tokenizer_config[ "pad_token" ]
            
                # Handle different token attribute references
                if pad_token == "eos_token":
                    self.tokenizer.pad_token = self.tokenizer.eos_token
                elif pad_token == "unk_token":
                    self.tokenizer.pad_token = self.tokenizer.unk_token
                    # Convert from unk_token if needed
                    if tokenizer_config.get( "pad_token_id" ) == "converted_from_unk_token":
                        self.tokenizer.pad_token_id = self.tokenizer.convert_tokens_to_ids( self.tokenizer.pad_token )
                else:
                    # Direct string assignment
                    self.tokenizer.pad_token = pad_token
                    # Set ID if provided
                    if "pad_token_id" in tokenizer_config and isinstance( tokenizer_config[ "pad_token_id" ], int ):
                        self.tokenizer.pad_token_id = tokenizer_config[ "pad_token_id" ]
            
                # Set padding side based on mode
                if mode == "training":
                    print( f"Setting padding side to '{tokenizer_config[ 'padding_side' ][ 'training' ]}' for training" )
                    self.tokenizer.padding_side = tokenizer_config[ 'padding_side' ][ 'training' ]
                elif mode == "inference":
                    print( f"Setting padding side to '{tokenizer_config[ 'padding_side' ][ 'inference' ]}' for inference" )
                    self.tokenizer.padding_side = tokenizer_config[ 'padding_side' ][ 'inference' ]
                else:
                    # this is checked above, this will never be called
                    raise ValueError( "Mode MUST be specified, either 'training' or 'inference'" )
            else:
                print( "Tokenizer already loaded. Skipping" )
        
        finally:
            if original_cwd != os.getcwd():
                print( f"Switching back to original working directory: {original_cwd}" )
                os.chdir( original_cwd )
            # print( f"New working directory: {os.getcwd()}" )
    
    def _get_peft_config( self ) -> LoraConfig:
        """
        Create PEFT configuration for the model.
        
        Requires:
            - self.model_name is a supported model
            - Model config available
            
        Ensures:
            - Returns LoraConfig with model-specific parameters
            - Loads from model configuration files
            
        Raises:
            - KeyError if config missing required fields
        """
        # Load the model-specific configuration
        model_config = load_model_config( self.model_name )
        lora_params = model_config[ "lora" ]
        
        return LoraConfig(
            lora_alpha=lora_params[ "lora_alpha" ],
            lora_dropout=lora_params[ "lora_dropout" ],
            r=lora_params[ "r" ],
            bias=lora_params[ "bias" ],
            task_type=lora_params[ "task_type" ],
            target_modules=lora_params[ "target_modules" ]
        )
    
    def _get_training_args( self, output_dir: str="./results", batch_size: int=8, gradient_accumulation_steps: int=1,
                            logging_steps: float=0.05, eval_steps: float=0.5
                            ) -> Any:
        """
        Create training configuration for SFT trainer.
        
        Requires:
            - output_dir is valid path
            - All numeric parameters have valid values
            
        Ensures:
            - Returns SFTConfig with training parameters
            - Creates timestamped output directory
            - Sets precision based on GPU support
            - Max sequence length from model config
            
        Raises:
            - None
        """
        return SFTConfig(
            # set logging dir
            # output_dir=f"{output_dir}/peft-output-{du.get_current_date()}-at-{du.get_current_time( format='%H-%M', include_timezone=False )}",
            output_dir=f"{output_dir}/training-{du.get_current_date()}-at-{du.get_current_time( format='%H-%M', include_timezone=False )}",
            eval_strategy="steps",
            do_eval=True,
            optim="adamw_8bit",
            per_device_train_batch_size=batch_size,
            per_device_eval_batch_size=batch_size,
            gradient_accumulation_steps=gradient_accumulation_steps,
            # for a batch size of 8: Gradient checkpointing nearly reduces the memory consumption by 40%.
            # For a batch size of 8: Fine-tuning is twice as fast without gradient checkpointing.
            gradient_checkpointing=False,
            log_level="debug",
            save_strategy="epoch",
            logging_steps=logging_steps,
            learning_rate=1e-5,
            bf16=torch.cuda.is_bf16_supported(),
            fp16=not torch.cuda.is_bf16_supported(),
            eval_steps=eval_steps,
            num_train_epochs=1,
            warmup_ratio=0.1,
            lr_scheduler_type="linear",
            # what is this doing here?
            # dataset_text_field="text",
            max_seq_length=self._get_max_seq_length()
        )
    
    def _get_max_seq_length( self ) -> int:
        """
        Get maximum sequence length for the model.
        
        Requires:
            - self.model_name is a supported model
            - Model config available
            
        Ensures:
            - Returns max sequence length from config
            
        Raises:
            - ValueError if model not supported
        """
        # Load the model-specific configuration
        model_config = load_model_config( self.model_name )
        return model_config[ "model" ][ "max_seq_length" ]
    
    def _print_dry_run_stats( self, sample_size: float ) -> None:
        """
        Prints training data statistics without performing training.

        Requires:
            - sample_size is between 0.0 and 1.0
            - Training JSONL files exist at test_train_dir

        Ensures:
            - Loads and parses training/test data
            - Prints total row counts, effective sample counts
            - Prints per-command distribution with imbalance analysis
            - Does NOT load any model or perform training
        """
        import re

        train_path = f"/{self.test_train_dir}/voice-commands-xml-train.jsonl"
        test_path  = f"/{self.test_train_dir}/voice-commands-xml-test.jsonl"

        train_rows_raw = du.get_file_as_list( train_path )
        test_rows_raw  = du.get_file_as_list( test_path )

        train_total    = len( train_rows_raw )
        test_total     = len( test_rows_raw )
        train_effective = int( train_total * sample_size ) if sample_size < 1.0 else train_total
        test_effective  = int( test_total * sample_size ) if sample_size < 1.0 else test_total

        # Parse commands from training data output field
        command_pattern = re.compile( r"<command>(.*?)</command>" )
        command_counts  = {}
        for line in train_rows_raw[ :train_effective ]:
            row   = json.loads( line )
            match = command_pattern.search( row.get( "output", "" ) )
            if match:
                cmd = match.group( 1 )
                command_counts[ cmd ] = command_counts.get( cmd, 0 ) + 1

        separator = "=" * 65
        print( f"\n{separator}" )
        print( f" DRY RUN: Training Data Summary" )
        print( f"{separator}\n" )
        print( f"  Model:            {self.model_name}" )
        print( f"  Sample size:      {sample_size} ({sample_size * 100:.0f}%)" )
        print( f"  Train file:       voice-commands-xml-train.jsonl" )
        print( f"  Test file:        voice-commands-xml-test.jsonl" )
        print( f"\n  Training rows:    {train_total:,} total, {train_effective:,} effective" )
        print( f"  Test rows:        {test_total:,} total, {test_effective:,} effective" )

        if command_counts:
            sorted_commands = sorted( command_counts.items() )
            print( f"\n  Per-command distribution (training set, {len( sorted_commands )} commands):" )
            print( f"  {'#':<4} {'Command':<55} {'Count':>7} {'Pct':>7}" )
            print( "  " + "." * 75 )
            for i, ( cmd, count ) in enumerate( sorted_commands, 1 ):
                pct = 100.0 * count / train_effective
                print( f"  {i:<4} {cmd:<55} {count:>7} {pct:>6.1f}%" )
            print( "  " + "." * 75 )
            print( f"  {'':4} {'TOTAL':<55} {train_effective:>7} {'100.0%':>7}" )

            counts_list = list( command_counts.values() )
            min_count   = min( counts_list )
            max_count   = max( counts_list )
            mean_count  = sum( counts_list ) / len( counts_list )
            ratio       = max_count / min_count if min_count > 0 else float( "inf" )
            print( f"\n  Min: {min_count}  Max: {max_count}  Mean: {mean_count:.1f}  Ratio: {ratio:.1f}x" )

        print( f"\n{separator}" )

    def _print_training_summary( self ) -> None:
        """
        Print consolidated training results dashboard comparing all validation stages.

        Requires:
            - self.validation_results is a non-empty list of dicts from run_validation()
            - Each dict has keys: "stats", "ms_per_item", "stage", "df"
            - self.stage_timings is a dict mapping stage names to elapsed milliseconds

        Ensures:
            - Prints Table 1: Overall metrics comparison across stages
            - Prints Table 2: Per-command accuracy with deltas (if 2+ stages)
            - Prints Table 3: Quantization impact summary (if post-training + post-quantization both present)
            - Prints Table 4: Pipeline stage timing breakdown
        """
        sep = "=" * 90
        print( f"\n{sep}" )
        print( f" TRAINING RESULTS DASHBOARD" )
        print( f"{sep}\n" )

        # ── Table 1: Overall Metrics Comparison ──
        print( "  Table 1: Overall Metrics Comparison" )
        print( "  " + "-" * 86 )
        header = f"  {'Stage':<22} | {'Exact Match':>12} | {'Command':>9} | {'Args':>9} | {'ms/item':>9} | {'Speedup':>8}"
        print( header )
        print( "  " + "-" * 86 )

        baseline_ms = None
        for r in self.validation_results:
            s           = r[ "stats" ]
            exact       = s[ "response_exact_percent" ]
            cmd         = s[ "command_correct_percent" ]
            args_pct    = s[ "args_correct_percent" ]
            ms          = r[ "ms_per_item" ]
            stage       = r[ "stage" ]

            if baseline_ms is None:
                baseline_ms = ms
                speedup_str = "-".rjust( 8 )
            else:
                speedup     = baseline_ms / ms if ms > 0 else 0
                speedup_str = f"{speedup:.2f}x".rjust( 8 )

            print( f"  {stage:<22} | {exact:>11.1f}% | {cmd:>8.1f}% | {args_pct:>8.1f}% | {ms:>9.1f} | {speedup_str}" )

        print( "  " + "-" * 86 )
        print()

        # ── Tables 2 & 3: Per-Command Accuracy + Quantization Impact (per quant variant) ──
        # Find the post-training baseline (if present) and all post-quantization results
        baseline_result = None
        quant_results   = []
        for r in self.validation_results:
            if "POST-training" in r[ "stage" ]:
                baseline_result = r
            elif "POST-quantization" in r[ "stage" ]:
                quant_results.append( r )

        # Fall back to comparing last two stages if no post-training baseline found
        if baseline_result is None and len( self.validation_results ) >= 2:
            baseline_result = self.validation_results[ -2 ]
            quant_results   = [ self.validation_results[ -1 ] ]

        table_number = 2
        for current_result in quant_results:
            if baseline_result is None:
                break

            prev_per_cmd    = baseline_result[ "stats" ].get( "per_command", {} )
            current_per_cmd = current_result[ "stats" ].get( "per_command", {} )
            prev_label      = baseline_result[ "stage" ]
            current_label   = current_result[ "stage" ]

            all_commands = sorted( set( prev_per_cmd.keys() ) | set( current_per_cmd.keys() ) )

            if all_commands:
                print( f"  Table {table_number}: Per-Command Accuracy ({prev_label} vs {current_label})" )
                print( "  " + "-" * 86 )
                print( f"  {'Command':<50} | {prev_label:>12} | {current_label:>12} | {'Delta':>7}" )
                print( "  " + "-" * 86 )

                # Sort by delta ascending (worst degradation first)
                command_deltas = []
                for cmd in all_commands:
                    prev_val    = prev_per_cmd.get( cmd, 0.0 )
                    current_val = current_per_cmd.get( cmd, 0.0 )
                    delta       = current_val - prev_val
                    command_deltas.append( ( cmd, prev_val, current_val, delta ) )

                command_deltas.sort( key=lambda x: x[ 3 ] )

                degraded_count = 0
                worst_cmd      = None
                worst_delta    = 0.0
                for cmd, prev_val, current_val, delta in command_deltas:
                    delta_str = f"{delta:+.1f}"
                    print( f"  {cmd:<50} | {prev_val:>11.2f}% | {current_val:>11.2f}% | {delta_str:>7}" )
                    if delta < -0.5:
                        degraded_count += 1
                        if delta < worst_delta:
                            worst_delta = delta
                            worst_cmd   = cmd

                print( "  " + "-" * 86 )
                print()

                # ── Impact Summary for this quant variant ──
                table_number += 1
                prev_exact    = baseline_result[ "stats" ][ "response_exact_percent" ]
                current_exact = current_result[ "stats" ][ "response_exact_percent" ]
                prev_ms       = baseline_result[ "ms_per_item" ]
                current_ms    = current_result[ "ms_per_item" ]
                speedup       = prev_ms / current_ms if current_ms > 0 else 0

                print( f"  Table {table_number}: Quantization Impact Summary ({current_label})" )
                print( "  " + "-" * 60 )
                print( f"  Quantization Speedup : {speedup:.2f}x ({prev_ms:.1f}ms -> {current_ms:.1f}ms)" )
                print( f"  Accuracy Cost        : {current_exact - prev_exact:+.1f}pp ({prev_exact:.1f}% -> {current_exact:.1f}%)" )
                print( f"  Commands Degraded    : {degraded_count} of {len( all_commands )}" )
                if worst_cmd:
                    print( f"  Worst Degradation    : {worst_cmd} ({worst_delta:+.1f}pp)" )
                print( "  " + "-" * 60 )
                print()

                table_number += 1

        # ── Pipeline Stage Timing ──
        if self.stage_timings:
            print( f"  Table {table_number}: Pipeline Stage Timing" )
            print( "  " + "-" * 60 )
            print( f"  {'Stage':<35} | {'Duration':>12} | {'% of Total':>10}" )
            print( "  " + "-" * 60 )

            total_ms = self.stage_timings.get( "total_pipeline", sum( self.stage_timings.values() ) )

            # Display order for stages — includes both legacy and new dual-quant keys
            stage_display_order = [
                ( "pre_training_validation",              "Pre-training validation" ),
                ( "fine_tuning",                          "Fine-tuning" ),
                ( "adapter_merge",                        "Adapter merge" ),
                ( "post_training_validation",             "Post-training validation" ),
                ( "quantization",                         "Quantization" ),
                ( "quantization_4bit",                    "Quantization (4-bit)" ),
                ( "quantization_8bit",                    "Quantization (8-bit)" ),
                ( "post_quantization_validation",         "Post-quantization validation" ),
                ( "post_quantization_4bit_validation",    "Post-quant (4-bit) validation" ),
                ( "post_quantization_8bit_validation",    "Post-quant (8-bit) validation" ),
            ]

            displayed_ms = 0
            for key, label in stage_display_order:
                if key in self.stage_timings:
                    ms  = self.stage_timings[ key ]
                    pct = ( ms / total_ms * 100 ) if total_ms > 0 else 0
                    displayed_ms += ms
                    print( f"  {label:<35} | {self._format_duration_ms( ms ):>12} | {pct:>9.1f}%" )

            # Show unaccounted time (GPU release, overhead, etc.)
            if total_ms > 0 and displayed_ms < total_ms:
                overhead_ms = total_ms - displayed_ms
                pct = ( overhead_ms / total_ms * 100 )
                print( f"  {'Other (GPU release, overhead)':<35} | {self._format_duration_ms( overhead_ms ):>12} | {pct:>9.1f}%" )

            print( "  " + "-" * 60 )
            if "total_pipeline" in self.stage_timings:
                print( f"  {'Total pipeline':<35} | {self._format_duration_ms( total_ms ):>12} | {'100.0%':>10}" )

            print( "  " + "-" * 60 )

        print( f"\n{sep}\n" )

    def _write_training_summary_to_file( self ) -> str:
        """
        Write training results to a versioned markdown file with YAML frontmatter.

        Requires:
            - self.validation_results is populated with at least one result
            - self.stage_timings is populated
            - cu.get_project_root() returns a valid path

        Ensures:
            - Creates io/peft/ directory if it doesn't exist
            - Writes YAML frontmatter with machine-parseable training metadata
            - Writes 4 tables in GitHub-flavored markdown matching the console dashboard
            - Writes Output Paths section listing all pipeline artifacts
            - Returns the path to the written file

        Raises:
            - IOError if file write fails
            - ImportError if yaml is not available
        """
        import yaml

        project_root = du.get_project_root()
        output_dir   = project_root + "/io/peft"
        os.makedirs( output_dir, exist_ok=True )

        # Build filename: YYYY.MM.DD-at-HH-MM-peft-training-results-{model}-{bits}-bits.md
        date_str = du.get_current_date()
        time_str = du.get_current_time( format='%H-%M', include_timezone=False )

        # Determine model short name for filename
        model_short = self.model_name.lower().replace( " ", "-" )

        # Determine bits label for filename
        quant_bits = sorted( self.quantized_model_dirs.keys() ) if self.quantized_model_dirs else []
        if len( quant_bits ) == 0:
            bits_label = "no-quant"
        elif len( quant_bits ) == 1:
            bits_label = f"{quant_bits[ 0 ]}-bits"
        else:
            bits_label = f"{quant_bits[ 0 ]}-and-{quant_bits[ -1 ]}-bits"

        filename    = f"{date_str}-at-{time_str}-peft-training-results-{model_short}-{bits_label}.md"
        output_path = f"{output_dir}/{filename}"

        # ── Build YAML frontmatter ──
        frontmatter = {
            "model_name"  : self.model_name,
            "model_hf_id" : self.model_hf_id,
            "generated"   : du.get_current_date() + "T" + du.get_current_time( format='%H:%M:%S', include_timezone=False ),
        }

        if self.lora_dir is not None:
            frontmatter[ "lora_dir" ] = self.lora_dir
        if self.merged_adapter_dir is not None:
            frontmatter[ "merged_adapter_dir" ] = self.merged_adapter_dir
        if self.quantized_model_dirs:
            frontmatter[ "quantized_model_dirs" ] = { str( k ): v for k, v in self.quantized_model_dirs.items() }

        frontmatter[ "validation_stages" ] = len( self.validation_results )

        stages_list = []
        for r in self.validation_results:
            s = r[ "stats" ]
            stage_entry = {
                "stage"       : r[ "stage" ],
                "exact_match" : round( s[ "response_exact_percent" ], 1 ),
                "command_pct" : round( s[ "command_correct_percent" ], 1 ),
                "args_pct"    : round( s[ "args_correct_percent" ], 1 ),
                "ms_per_item" : round( r[ "ms_per_item" ], 1 ),
            }
            stages_list.append( stage_entry )
        frontmatter[ "stages" ] = stages_list

        if "total_pipeline" in self.stage_timings:
            frontmatter[ "total_pipeline_ms" ]    = round( self.stage_timings[ "total_pipeline" ] )
            frontmatter[ "total_pipeline_human" ] = self._format_duration_ms( self.stage_timings[ "total_pipeline" ] )

        # ── Build markdown body ──
        lines = []
        lines.append( "---" )
        lines.append( yaml.dump( frontmatter, default_flow_style=False, sort_keys=False ).rstrip() )
        lines.append( "---" )
        lines.append( "" )
        lines.append( f"# PEFT Training Results: {self.model_name}" )
        lines.append( "" )

        # ── Table 1: Overall Metrics Comparison ──
        lines.append( "## Table 1: Overall Metrics Comparison" )
        lines.append( "" )
        lines.append( "| Stage | Exact Match | Command | Args | ms/item | Speedup |" )
        lines.append( "|-------|-------------|---------|------|---------|---------|" )

        baseline_ms = None
        for r in self.validation_results:
            s     = r[ "stats" ]
            exact = s[ "response_exact_percent" ]
            cmd   = s[ "command_correct_percent" ]
            args  = s[ "args_correct_percent" ]
            ms    = r[ "ms_per_item" ]
            stage = r[ "stage" ]

            if baseline_ms is None:
                baseline_ms = ms
                speedup_str = "-"
            else:
                speedup     = baseline_ms / ms if ms > 0 else 0
                speedup_str = f"{speedup:.2f}x"

            lines.append( f"| {stage} | {exact:.1f}% | {cmd:.1f}% | {args:.1f}% | {ms:.1f} | {speedup_str} |" )

        lines.append( "" )

        # ── Tables 2 & 3: Per-Command + Impact (per quant variant) ──
        baseline_result = None
        quant_results   = []
        for r in self.validation_results:
            if "POST-training" in r[ "stage" ]:
                baseline_result = r
            elif "POST-quantization" in r[ "stage" ]:
                quant_results.append( r )

        if baseline_result is None and len( self.validation_results ) >= 2:
            baseline_result = self.validation_results[ -2 ]
            quant_results   = [ self.validation_results[ -1 ] ]

        for current_result in quant_results:
            if baseline_result is None:
                break

            prev_per_cmd    = baseline_result[ "stats" ].get( "per_command", {} )
            current_per_cmd = current_result[ "stats" ].get( "per_command", {} )
            prev_label      = baseline_result[ "stage" ]
            current_label   = current_result[ "stage" ]
            all_commands    = sorted( set( prev_per_cmd.keys() ) | set( current_per_cmd.keys() ) )

            if all_commands:
                lines.append( f"## Per-Command Accuracy: {prev_label} vs {current_label}" )
                lines.append( "" )
                lines.append( f"| Command | {prev_label} | {current_label} | Delta |" )
                lines.append( "|---------|-------------|-------------|-------|" )

                command_deltas = []
                for cmd in all_commands:
                    prev_val    = prev_per_cmd.get( cmd, 0.0 )
                    current_val = current_per_cmd.get( cmd, 0.0 )
                    delta       = current_val - prev_val
                    command_deltas.append( ( cmd, prev_val, current_val, delta ) )
                command_deltas.sort( key=lambda x: x[ 3 ] )

                degraded_count = 0
                worst_cmd      = None
                worst_delta    = 0.0
                for cmd, prev_val, current_val, delta in command_deltas:
                    lines.append( f"| {cmd} | {prev_val:.2f}% | {current_val:.2f}% | {delta:+.1f} |" )
                    if delta < -0.5:
                        degraded_count += 1
                        if delta < worst_delta:
                            worst_delta = delta
                            worst_cmd   = cmd

                lines.append( "" )

                # Impact summary
                prev_exact    = baseline_result[ "stats" ][ "response_exact_percent" ]
                current_exact = current_result[ "stats" ][ "response_exact_percent" ]
                prev_ms       = baseline_result[ "ms_per_item" ]
                current_ms    = current_result[ "ms_per_item" ]
                speedup       = prev_ms / current_ms if current_ms > 0 else 0

                lines.append( f"### Quantization Impact Summary ({current_label})" )
                lines.append( "" )
                lines.append( f"- **Quantization Speedup**: {speedup:.2f}x ({prev_ms:.1f}ms -> {current_ms:.1f}ms)" )
                lines.append( f"- **Accuracy Cost**: {current_exact - prev_exact:+.1f}pp ({prev_exact:.1f}% -> {current_exact:.1f}%)" )
                lines.append( f"- **Commands Degraded**: {degraded_count} of {len( all_commands )}" )
                if worst_cmd:
                    lines.append( f"- **Worst Degradation**: {worst_cmd} ({worst_delta:+.1f}pp)" )
                lines.append( "" )

        # ── Pipeline Stage Timing ──
        if self.stage_timings:
            lines.append( "## Pipeline Stage Timing" )
            lines.append( "" )
            lines.append( "| Stage | Duration | % of Total |" )
            lines.append( "|-------|----------|------------|" )

            total_ms = self.stage_timings.get( "total_pipeline", sum( self.stage_timings.values() ) )

            stage_display_order = [
                ( "pre_training_validation",              "Pre-training validation" ),
                ( "fine_tuning",                          "Fine-tuning" ),
                ( "adapter_merge",                        "Adapter merge" ),
                ( "post_training_validation",             "Post-training validation" ),
                ( "quantization",                         "Quantization" ),
                ( "quantization_4bit",                    "Quantization (4-bit)" ),
                ( "quantization_8bit",                    "Quantization (8-bit)" ),
                ( "post_quantization_validation",         "Post-quantization validation" ),
                ( "post_quantization_4bit_validation",    "Post-quant (4-bit) validation" ),
                ( "post_quantization_8bit_validation",    "Post-quant (8-bit) validation" ),
            ]

            displayed_ms = 0
            for key, label in stage_display_order:
                if key in self.stage_timings:
                    ms  = self.stage_timings[ key ]
                    pct = ( ms / total_ms * 100 ) if total_ms > 0 else 0
                    displayed_ms += ms
                    lines.append( f"| {label} | {self._format_duration_ms( ms )} | {pct:.1f}% |" )

            if total_ms > 0 and displayed_ms < total_ms:
                overhead_ms = total_ms - displayed_ms
                pct = ( overhead_ms / total_ms * 100 )
                lines.append( f"| Other (GPU release, overhead) | {self._format_duration_ms( overhead_ms )} | {pct:.1f}% |" )

            if "total_pipeline" in self.stage_timings:
                lines.append( f"| **Total pipeline** | **{self._format_duration_ms( total_ms )}** | **100.0%** |" )

            lines.append( "" )

        # ── Output Paths ──
        lines.append( "## Output Paths" )
        lines.append( "" )
        lines.append( "| Artifact | Path |" )
        lines.append( "|----------|------|" )

        if self.lora_dir is not None:
            lines.append( f"| LoRA Adapter | {self.lora_dir} |" )
        if self.merged_adapter_dir is not None:
            lines.append( f"| Merged Adapter | {self.merged_adapter_dir} |" )
        for bits, qdir in sorted( self.quantized_model_dirs.items() ):
            lines.append( f"| Quantized ({bits}-bit) | {qdir} |" )
        if hasattr( self, "test_train_dir" ) and self.test_train_dir is not None:
            lines.append( f"| Test/Train Data | {self.test_train_dir} |" )
        lines.append( f"| Training Results | {output_path} |" )
        lines.append( "" )

        # Write file
        with open( output_path, "w" ) as f:
            f.write( "\n".join( lines ) )

        return output_path

    @staticmethod
    def _format_duration_ms( ms: float ) -> str:
        """
        Format milliseconds as human-readable duration string.

        Requires:
            - ms is a non-negative number

        Ensures:
            - Returns string in format HH:MM:SS or MM:SS for durations under 1 hour
        """
        total_seconds = int( ms / 1000 )
        hours         = total_seconds // 3600
        minutes       = ( total_seconds % 3600 ) // 60
        seconds       = total_seconds % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"

    def _get_test_train_data( self, sample_size: float=1.0 ) -> dict[str, Dataset]:
        """
        Load and prepare training and testing datasets.

        Requires:
            - self.model_name is supported
            - Dataset files exist in test_train_dir
            - Files are in JSONL format

        Ensures:
            - Loads train and test datasets
            - Samples data if requested
            - Formats according to model needs
            - Returns dict with 'train' and 'test' keys

        Raises:
            - ValueError if model not supported
            - FileNotFoundError if datasets missing
        """
        # Validate model name for supported models
        if self.model_name not in [ "Mistral-7B-Instruct-v0.2", "Ministral-8B-Instruct-2410", "Llama-3.2-3B-Instruct",
            "Phi-4-mini-instruct", "Qwen3-4B-Base" ]:
            self._validate_model_name()

        path = f"/{self.test_train_dir}/voice-commands-xml-train.jsonl"
        train_dataset = self._get_dataset( path, sample_size=sample_size )

        path = f"/{self.test_train_dir}/voice-commands-xml-test.jsonl"
        test_dataset = self._get_dataset( path, sample_size=sample_size )

        return { 'train': train_dataset, 'test': test_dataset }

    def _get_dataset( self, path: str, sample_size: float=1.0 ) -> Dataset:
        """
        Load and process dataset from JSONL file.

        Requires:
            - path is valid JSONL file
            - sample_size between 0.0 and 1.0

        Ensures:
            - Loads and parses JSON data
            - Samples if sample_size < 1.0
            - Returns Dataset object

        Raises:
            - FileNotFoundError if file missing
            - JSONDecodeError if invalid JSON
        """
        rows = du.get_file_as_list( path )
        # retain a sample of the data set expressed as a percentage
        row_count = len( rows )
        if sample_size < 1.0:
            rows = rows[ : int( row_count * sample_size ) ]
        rows = [ json.loads( line ) for line in rows ]

        print( f"Loaded {len( rows )} of {row_count} training rows" )

        return Dataset.from_list( rows )
    
    def _format_prompt( self, row: dict ) -> str:
        """
        Format training example into model-specific prompt.
        
        Requires:
            - row has "instruction", "input", "output" keys
            - self.model_name is supported
            - Model config available
            
        Ensures:
            - Returns formatted prompt string
            - Uses model-specific template from config
            
        Raises:
            - ValueError if model not supported
            - KeyError if row missing required fields
        """
        # Load the model-specific configuration
        model_config = load_model_config( self.model_name )
        template = model_config[ "model" ][ "prompt_template" ]
        
        # Format using the template from the configuration
        # Check if last_tag_func exists in the configuration
        if "last_tag_func" in model_config[ "model" ]:
            # Use the lambda function directly from the config
            last_tag_func = model_config[ "model" ][ "last_tag_func" ]
            last_tag = last_tag_func( row[ "output" ] )
        else:
            last_tag = ""
        
        # Format the prompt with the template
        return template.format(
            instruction=row[ "instruction" ],
            input=row[ "input" ],
            output=row[ "output" ],
            last_tag=last_tag
        )
    
    def get_prompt( self, instruction, input, output="" ):
        """
        Formats a prompt for a given model based on instruction, input, and optional output.
        
        Preconditions:
        - instruction and input must be valid strings.
        - self.model_name must be one of the supported model names.
        
        Postconditions:
        - A formatted prompt string is returned in the appropriate format for the model type.
        - If output is empty, the prompt is formatted for inference (generation).
        - If output is provided, the prompt is formatted for training.
        
        Parameters:
        - instruction (str): The instruction or task description.
        - input (str): The input data for the task.
        - output (str, optional): The expected output or response. Defaults to "".
        
        Returns:
        - str: A formatted prompt string suitable for the specified model type.
        
        Raises:
        - ValueError: If self.model_name is not one of the supported models.
        
        Notes:
        - The prompt format is loaded from the model-specific configuration file
        - For some models, the closing tag is only included if output is provided
        """
        # Load the model-specific configuration
        model_config = load_model_config( self.model_name )
        template = model_config[ "model" ][ "prompt_template" ]
        
        # Check if last_tag_func exists in the configuration
        if "last_tag_func" in model_config[ "model" ]:
            # Use the lambda function directly from the config
            last_tag_func = model_config[ "model" ][ "last_tag_func" ]
            last_tag = last_tag_func( output )
        else:
            last_tag = ""
        
        # Format the prompt with the template
        return template.format(
            instruction=instruction,
            input=input,
            output=output,
            last_tag=last_tag
        )
    
    def _print_trainable_parameters( self ) -> None:
        """
        Prints the number of trainable parameters in the model.
        
        Requires:
            - Model loaded and initialized
            - Model has named parameters
        
        Ensures:
            - Trainable parameter count printed
            - Total parameter count printed
            - Percentage calculated and printed
        """
        trainable_params = 0
        all_param = 0
        for _, param in self.model.named_parameters():
            all_param += param.numel()
            if param.requires_grad:
                trainable_params += param.numel()
        print(
            f"trainable params: {trainable_params:,} || all params: {all_param:,} || trainable%: {100 * trainable_params / all_param:.2f}"
        )
    
    def _print_stats_pre( self ) -> None:
        """
        Captures and prints GPU memory statistics before training.
        
        Requires:
            - CUDA available
            - GPU accessible through torch.cuda
        
        Ensures:
            - GPU device properties retrieved
            - Baseline memory usage recorded
            - Max memory available captured
            - Stats printed to console
        """
        gpu_stats = torch.cuda.get_device_properties( 0 )
        self.start_gpu_memory = round( torch.cuda.max_memory_reserved() / 1024 / 1024 / 1024, 3 )
        self.max_memory = round( gpu_stats.total_memory / 1024 / 1024 / 1024, 3 )
        print( f"GPU = {gpu_stats.name}. Max memory = {self.max_memory} GB." )
        print( f"{self.start_gpu_memory} GB of memory reserved." )
    
    def _print_stats_post( self ) -> None:
        """
        Captures and prints GPU memory statistics after training.
        
        Requires:
            - CUDA available
            - GPU accessible through torch.cuda
            - _print_stats_pre called first
            - start_gpu_memory/max_memory initialized
        
        Ensures:
            - Peak memory usage calculated
            - Training memory delta computed
            - Memory percentages calculated
            - Stats printed to console
        """
        used_memory = round( torch.cuda.max_memory_reserved() / 1024 / 1024 / 1024, 3 )
        used_memory_for_trainer = round( used_memory - self.start_gpu_memory, 3 )
        used_percentage = round( used_memory / self.max_memory * 100, 3 )
        trainer_percentage = round( used_memory_for_trainer / self.max_memory * 100, 3 )
        print( f"Peak reserved memory = {used_memory} GB." )
        print( f"Peak reserved memory for training = {used_memory_for_trainer} GB." )
        print( f"Peak reserved memory % of max memory = {used_percentage} %." )
        print( f"Peak reserved memory for training % of max memory = {trainer_percentage} %." )
        
        # Note: Attempted to access self.trainer.metrics but SFTTrainer has no metrics attribute
        # AttributeError: 'SFTTrainer' object has no attribute 'metrics'
    
    def set_hf_env_vars( self, hf_home: str="/var/model/models", hf_hub_etag_timeout: str="60", hf_hub_download_timeout: str="60" ) -> None:
        """
        Sets environment variables for the Hugging Face model hub.
        
        Requires:
            - None (can be called anytime)
        
        Ensures:
            - HF_HOME environment variable set
            - HF_HUB_ETAG_TIMEOUT variable set
            - HF_HUB_DOWNLOAD_TIMEOUT variable set
            - All values printed to console
        """
        os.environ[ "HF_HOME" ] = hf_home
        os.environ[ "HF_HUB_ETAG_TIMEOUT" ] = hf_hub_etag_timeout
        os.environ[ "HF_HUB_DOWNLOAD_TIMEOUT" ] = hf_hub_download_timeout
        
        du.print_banner( "Hugging Face Environment Variables:" )
        print( os.environ[ "HF_HOME" ] )
        print( os.environ[ "HF_HUB_ETAG_TIMEOUT" ] )
        print( os.environ[ "HF_HUB_DOWNLOAD_TIMEOUT" ] )
    
    def set_lupin_env_vars( self, wandb_disable_service: str="True", lupin_root: str="/var/model/lupin" ) -> None:
        """
        Sets environment variables for the Genie in the Box application.
        
        Requires:
            - None (can be called anytime)
        
        Ensures:
            - LUPIN_ROOT variable set
            - LUPIN_CONFIG_MGR_CLI_ARGS variable set
            - WANDB_DISABLE_SERVICE variable set
        """
        os.environ[ "LUPIN_ROOT" ] = lupin_root
        os.environ[
            "LUPIN_CONFIG_MGR_CLI_ARGS" ] = "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"
        os.environ[ "WANDB_DISABLE_SERVICE" ] = wandb_disable_service
    
    def _start_vllm_server( self,
        model_path_or_hf_id: str, port: int=3000, max_model_len: int=2048, gpu_memory_utilization: float=0.75, timeout: int=180,
        quantization: str=None, verbose_server: bool=False
    ) -> subprocess.Popen:
        """
        Starts a vLLM server for the quantized model and waits for it to be available.

        Requires:
            - Valid model path or HF model ID
            - DEEPILY_PROJECTS_DIR environment set
            - vLLM installed in virtual environment
            - GPU resources available
            - quantization (if provided) is a valid vLLM quantization method (e.g. "gptq_marlin")
            - verbose_server is a bool

        Ensures:
            - vLLM server started in subprocess
            - Server configured for available GPUs
            - Model-specific vllm_config overrides applied (max_model_len, gpu_memory_utilization)
            - Quantization flag appended to command only when explicitly passed
            - When verbose_server=True, all vLLM startup output is printed to console
            - Waits for server availability
            - Returns process object

        Raises:
            - ValueError if DEEPILY_PROJECTS_DIR not set
            - TimeoutError if server start times out
            - RuntimeError if server exits unexpectedly
        """
        # Apply model-specific vLLM config overrides if available
        vllm_config = load_model_config( self.model_name ).get( "vllm", {} )
        if vllm_config:
            max_model_len          = vllm_config.get( "max_model_len", max_model_len )
            gpu_memory_utilization = vllm_config.get( "gpu_memory_utilization", gpu_memory_utilization )
            if self.debug: print( f"vLLM config overrides from {self.model_name}: max_model_len={max_model_len}, gpu_memory_utilization={gpu_memory_utilization}" )

        # Read optional per-model overrides for TP size and max concurrent sequences
        tp_override  = vllm_config.get( "tensor_parallel_size", None )
        max_num_seqs = vllm_config.get( "max_num_seqs", None )

        # Check if DEEPILY_PROJECTS_DIR is set
        projects_dir = os.environ.get( "DEEPILY_PROJECTS_DIR" )
        if not projects_dir: raise ValueError( "DEEPILY_PROJECTS_DIR environment variable is not set." )

        du.print_banner( "Starting vLLM server...", prepend_nl=True  )

        # Check for multiple GPUs
        gpu_count = torch.cuda.device_count()

        if self.debug:
            for i in range( gpu_count ):
                gpu_name = torch.cuda.get_device_name( i )
                gpu_mem  = torch.cuda.get_device_properties( i ).total_memory / ( 1024 ** 3 )  # in GB
                print( f"  GPU {i}: {gpu_name} with {gpu_mem:.2f} GB memory" )

        # Use config TP size or auto-detect from available GPUs
        tensor_parallel_size = tp_override if tp_override else gpu_count
        gpu_devices          = ",".join( str( i ) for i in range( tensor_parallel_size ) )

        if self.debug: print( f"Detected {gpu_count} GPU(s), using tensor_parallel_size={tensor_parallel_size}, CUDA_VISIBLE_DEVICES={gpu_devices}" )

        # Build the vLLM command with GPU configuration
        if tensor_parallel_size > 1:
            gpu_config = f"--tensor-parallel-size {tensor_parallel_size} --gpu-memory-utilization {gpu_memory_utilization}"
        else:
            gpu_config = f"--gpu-memory-utilization {gpu_memory_utilization}"

        # Cap V1 engine warmup buffer allocation if specified
        if max_num_seqs:
            gpu_config += f" --max-num-seqs {max_num_seqs}"

        # Force specific quantization kernel (e.g. gptq_marlin) — only for quantized models
        if quantization:
            gpu_config += f" --quantization {quantization}"
            if self.debug: print( f"Quantization kernel override: --quantization {quantization}" )

        # Command to start the vLLM server
        cmd = f"cd {projects_dir}/vllm-pip; source .venv/bin/activate; CUDA_VISIBLE_DEVICES={gpu_devices} vllm serve {model_path_or_hf_id} --served-model-name {model_path_or_hf_id} --port {port} --max-model-len {max_model_len} {gpu_config}"
        
        if self.debug: print( f"Command to start vLLM server: {cmd}" )
        
        # Create error log capture
        server_log = [ ]
        server_error = None
        
        # Define function to monitor process status
        def check_process_status( process: subprocess.Popen, log: list ) -> bool:
            """Monitor subprocess status and capture any error if it exits prematurely"""
            nonlocal server_error
            return_code = process.poll()
            if return_code is not None:
                # Process exited
                stderr_output = process.stderr.read()
                if stderr_output:
                    error_msg = f"vLLM server exited with code {return_code}. Error: {stderr_output}"
                    server_error = RuntimeError( error_msg )
                    print( f"[vLLM Server ERROR] {error_msg}" )
                    # Add to log
                    log.append( f"EXIT CODE {return_code}: {stderr_output}" )
                return False
            return True
        
        # Start the vLLM server in a separate process with its own process group
        process = subprocess.Popen(
            cmd, shell=True, executable='/bin/bash', stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True
        )
        
        # Start a thread to read and print server output
        def print_server_output( process: subprocess.Popen, log: list ) -> None:
            for line in process.stdout:
                log.append( line.strip() )
                if verbose_server or ( self.debug and self.verbose ):
                    print( f"[vLLM Server] {line.strip()}" )
                # Check for genuine vLLM server errors (not model-generated text containing "error")
                # Real server errors: CUDA issues, Python exceptions at line start, vLLM-specific errors
                is_cuda_error   = "CUDA out of memory" in line or "CUDA error" in line
                is_server_error = line.strip().startswith( "Error:" ) or line.strip().startswith( "ERROR" )
                is_python_error = line.strip().startswith( "Traceback" ) or line.strip().startswith( "RuntimeError" )
                is_vllm_error   = "AsyncEngineDeadError" in line or "EngineDeadError" in line
                if is_cuda_error or is_server_error or is_python_error or is_vllm_error:
                    print( f"[vLLM Server ERROR] Detected error: {line.strip()}" )
        
        output_thread = threading.Thread( target=print_server_output, args=(process, server_log), daemon=True )
        output_thread.start()
        
        # Wait for the server to be available
        print( f"Waiting for vLLM server to be available on port {port}. This could take a couple minutes..." )
        server_url = f"http://localhost:{port}/health"
        start_time = time.time()
        
        # Keep track of how many times we've checked for status to periodically check process health
        check_count = 0
        
        while time.time() - start_time < timeout:
            check_count += 1
            
            # Every 5 checks, verify the process is still running
            if check_count % 5 == 0:
                if not check_process_status( process, server_log ):
                    if server_error:
                        raise server_error
                    else:
                        raise RuntimeError( "vLLM server process terminated unexpectedly" )
            
            try:
                response = requests.get( server_url, timeout=1 )
                if response.status_code == 200:
                    if self.debug or self.verbose:
                        print( f"vLLM server successfully started and is responding on port {port}" )
                        # Get and print server info if in debug mode
                        try:
                            info_response = requests.get( f"http://localhost:{port}/v1/models", timeout=1 )
                            print( f"Server model info: {info_response.json()}" )
                        except Exception as e:
                            print( f"Could not fetch server info: {str( e )}" )
                    else:
                        print( f"vLLM server is now available on port {port}" )
                    return process
            except requests.RequestException:
                # Server not yet available
                time.sleep( 2 )
                elapsed = time.time() - start_time
                if self.debug:
                    print( f"  Waiting... ({elapsed:.1f}s of max {timeout}s)" )
                # Print a progress message every 30 seconds even without debug mode
                elif elapsed % 30 < 2:  # This ensures the message prints only once near each 30s mark
                    print( f"  Still waiting for vLLM server... ({int( elapsed )}s of max {timeout}s)" )
        
        # If we reach here, the server did not start within the timeout
        # if self.debug or self.verbose:
        print( "vLLM server startup timed out. Last log entries:" )
        for entry in server_log[ -10: ]:  # Show last 10 log entries
            print( f"  {entry}" )
        
        self._stop_vllm_server( process )
        
        # Consolidate the logs for the error message
        log_tail = "\n".join( server_log[ -20: ] ) if server_log else "No log output captured"
        raise TimeoutError( f"vLLM server did not start within {timeout} seconds.\nLast log entries:\n{log_tail}" )
    
    def _stop_vllm_server( self, process: subprocess.Popen ) -> bool:
        """
        Stops the vLLM server process (spawned with start_new_session=True).
        
        Requires:
            - Valid subprocess.Popen object
            - Process created with start_new_session=True
        
        Ensures:
            - Server process terminated
            - Child processes also terminated
            - Returns True on success, False otherwise
        """
        if not process:
            return False
        
        du.print_banner( "Stopping vLLM server...", prepend_nl=True )
        
        try:
            # Process was started with start_new_session=True, so its PID is the group ID
            # Send SIGTERM to the child's own process group
            if self.debug: print( f"Sending SIGTERM to process group {process.pid}" )
            os.killpg( process.pid, 15 )  # SIGTERM
            
            # Wait for a clean exit, but not too long
            try:
                process.wait( timeout=10 )
                if self.debug: print( "vLLM server exited cleanly" )
            except subprocess.TimeoutExpired:
                if self.debug: print( "vLLM server did not exit after SIGTERM, sending SIGKILL" )
                # If it didn't exit cleanly, force kill
                try:
                    os.killpg( process.pid, 9 )  # SIGKILL
                except ProcessLookupError:
                    # Process is already gone
                    pass
        except (ProcessLookupError, OSError) as e:
            if self.debug: print( f"Error stopping vLLM server: {str( e )}" )
            # Process is already gone or we can't send signal
            # Just ensure we kill the direct process
            try:
                process.terminate()
            except:
                pass
        
        if self.debug: print( "vLLM server has been stopped" )
        return True

    def _wait_for_gpu_memory_release( self, max_wait_seconds=30, target_free_pct=0.90 ):
        """
        Polls GPU memory until sufficient memory is free after process termination.

        Requires:
            - torch.cuda is available
            - max_wait_seconds is a positive integer
            - target_free_pct is between 0.0 and 1.0

        Ensures:
            - Returns True when all GPUs have >= target_free_pct memory free
            - Returns False if timeout reached (caller should handle)
            - Prints progress during wait

        Raises:
            - None (returns False on failure)
        """
        gpu_count = torch.cuda.device_count()
        if gpu_count == 0: return True

        print( f"Waiting for GPU memory release (target: {target_free_pct * 100:.0f}% free)..." )

        for elapsed in range( max_wait_seconds ):
            all_clear = True
            for i in range( gpu_count ):
                free, total = torch.cuda.mem_get_info( i )
                free_pct    = free / total
                if free_pct < target_free_pct:
                    all_clear = False
                    break

            if all_clear:
                print( f"GPU memory released after {elapsed}s" )
                return True

            if elapsed % 5 == 0 and elapsed > 0:
                # Show progress every 5 seconds
                for i in range( gpu_count ):
                    free, total = torch.cuda.mem_get_info( i )
                    print( f"  GPU {i}: {free / ( 1024 ** 3 ):.1f} GB free / {total / ( 1024 ** 3 ):.1f} GB total ({free / total * 100:.0f}%)" )

            time.sleep( 1 )

        print( f"WARNING: GPU memory not fully released after {max_wait_seconds}s" )
        return False

    @staticmethod
    def _parse_quantize_bits( quantize_bits: str ) -> list:
        """
        Parse the --quantize-bits CLI argument into a list of int bit widths.

        Requires:
            - quantize_bits is one of "both", "4", or "8"

        Ensures:
            - Returns [4, 8] for "both", [4] for "4", [8] for "8"

        Raises:
            - ValueError if quantize_bits is not a recognized value
        """
        if quantize_bits == "both":
            return [ 4, 8 ]
        elif quantize_bits == "4":
            return [ 4 ]
        elif quantize_bits == "8":
            return [ 8 ]
        else:
            raise ValueError( f"Unknown quantize_bits value: {quantize_bits}. Must be 'both', '4', or '8'" )

    def run_pipeline( self,
        pre_training_stats: bool=False, post_training_stats: bool=False, post_quantization_stats: bool=False, nuclear_kill_button: bool=False,
        validation_sample_size: int=100, sample_size_override: float=None, dry_run: bool=False, quantize_bits: str="both",
        resume_from_merged: str=None
    ) -> None:
        """
        Executes the full training pipeline from fine-tuning to quantization.
        
        Requires:
            - The trainer instance must be properly initialized with valid model_hf_id, model_name, and test_train_path
            - Hugging Face credentials must be available for login
            - If lora_dir is provided, it must be a valid directory path or creatable
            - GPU resources must be available with sufficient VRAM for the model
            - Required datasets must be available at test_train_path
            - The specified model must be one of the supported models
            - If resume_from_merged is provided, it must be a valid directory containing a merged adapter

        Ensures:
            - If resume_from_merged is provided, phases 1-3 (pre-validation, fine-tuning, merge) are skipped
            - If pre_training_stats is True (and not resuming), validation is performed before training
            - The model is fine-tuned with LoRA adapters (unless resuming)
            - The LoRA adapter is merged with the base model (unless resuming)
            - A quantized version of the merged model is created
            - If post_training_stats is True, validation is performed after merging the adapter
            - If post_quantization_stats is True, validation is performed after quantizing the model
            - All processes (including vLLM server) are properly cleaned up regardless of success or failure
            - The pipeline steps are executed in the correct sequence
            - GPU memory is properly released between steps
            - The following instance attributes are updated:
              - self.checkpoint_dir: Set to the path of the last training checkpoint
              - self.merged_adapter_dir: Set to the path of the merged adapter
              - self.quantized_model_dir: Set to the path of the quantized model
        
        Raises:
            - ValueError: If required paths or credentials are invalid
            - RuntimeError: If GPU resources are insufficient or if model loading fails
            - TimeoutError: If the vLLM server does not start within the specified timeout
        """
        timer = Stopwatch( msg=None )

        # Dashboard: collect validation results and stage timings for consolidated summary
        self.validation_results = []
        self.stage_timings      = {}

        self.login_to_hf()

        if resume_from_merged:
            # Resume mode: skip training and merge, jump to validation/quantization
            #
            # KNOWN ISSUE (WILL NOT FIX): --post-quantization-stats causes OOM on the resume
            # path when vLLM starts after 8-bit quantization. Root cause: quantization is the
            # first GPU operation in this process, so PyTorch's CUDA caching allocator creates
            # a monolithic ~16 GB segment. After cleanup, a ~62 MB residual allocation pins
            # the entire segment — empty_cache() cannot release it. The subsequent vLLM
            # subprocess sees only ~10 GB free on GPU 0 and fails with "No available memory
            # for the cache blocks." The happy path avoids this because prior training/merge
            # cycles warm the allocator into a granular block structure. This is intractable
            # at the application level (PyTorch allocator internals).
            # Workaround: skip --post-quantization-stats when resuming, validate manually.
            # See: src/rnd/2026.02.16-peft-resume-oom-cold-allocator-analysis.md
            #
            du.print_banner( f"RESUME MODE: Using existing merged adapter at {resume_from_merged}" )
            if not os.path.isdir( resume_from_merged ):
                raise ValueError( f"Merged adapter directory does not exist: {resume_from_merged}" )
            merged_adapter_dir      = resume_from_merged
            self.merged_adapter_dir = merged_adapter_dir
        else:
            # Normal mode: run pre-validation, fine-tuning, and merge (phases 1-3)

            # Run a pre-training validation using vLLM server
            if pre_training_stats:
                stage_timer = Stopwatch( msg=None )
                vllm_server_process = None
                try:
                    # Start vLLM server for the base model and wait for it to be available
                    vllm_server_process = self._start_vllm_server( self.model_hf_id )

                    # Run validation using the server, pointing it to the HF ID
                    result = self.run_validation(
                        banner_prefix="PRE-training:",
                        model=self.model_hf_id,
                        path_prefix=lupin_root,
                        switch="deepily",
                        device_map="auto",  # Allow using multiple GPUs
                        validation_sample_size=validation_sample_size,
                        debug=self.debug,
                        verbose=self.verbose
                    )
                    self.validation_results.append( result )
                finally:
                    # Always clean up the vLLM server process if it was started
                    if vllm_server_process: self._stop_vllm_server( vllm_server_process )
                    # Release GPU resources
                    release_gpus( [ self.model, self.tokenizer ], nuclear_kill_button=nuclear_kill_button )
                    # Wait for GPU memory to actually be freed (vLLM process cleanup is async)
                    if not self._wait_for_gpu_memory_release():
                        print( "Attempting forced GPU cache clear..." )
                        torch.cuda.empty_cache()
                        gc.collect()
                        time.sleep( 5 )
                    du.print_banner( "Releasing GPU memory... AFTER", prepend_nl=True )
                    print_gpu_memory()
                self.stage_timings[ "pre_training_validation" ] = stage_timer.get_delta_ms()
            else:
                print( f"Skipping pre-training validation for {args.model_name}" )

            # Load model-specific fine-tuning configuration
            model_config = load_model_config( self.model_name )
            fine_tune_params = model_config[ "fine_tune" ]

            # Allow CLI override of sample_size
            if sample_size_override is not None:
                fine_tune_params[ "sample_size" ] = sample_size_override
                print( f"CLI override: sample_size = {sample_size_override}" )

            # Dry-run mode: show training data stats and exit without training
            if dry_run:
                self._print_dry_run_stats( fine_tune_params[ "sample_size" ] )
                return

            # Fine-tune using the dynamically loaded configuration
            stage_timer = Stopwatch( msg=None )
            checkpoint_dir = self.fine_tune(
                sample_size=fine_tune_params[ "sample_size" ],
                batch_size=fine_tune_params[ "batch_size" ],
                gradient_accumulation_steps=fine_tune_params[ "gradient_accumulation_steps" ],
                logging_steps=fine_tune_params[ "logging_steps" ],
                eval_steps=fine_tune_params[ "eval_steps" ],
                device_map=fine_tune_params[ "device_map" ],
                output_dir=args.lora_dir
            )
            self.stage_timings[ "fine_tuning" ] = stage_timer.get_delta_ms()
            release_gpus( [ self.model, self.tokenizer ] )
            du.print_banner( "Releasing GPU memory... AFTER", prepend_nl=True )
            print_gpu_memory()

            # Load and merge the adapter
            stage_timer = Stopwatch( msg=None )
            self.load_and_merge_adapter( checkpoint_dir=checkpoint_dir )
            merged_adapter_dir = self.save_merged_adapter( lora_dir=args.lora_dir )
            self.stage_timings[ "adapter_merge" ] = stage_timer.get_delta_ms()
            release_gpus( [ self.model, self.tokenizer ] )
            du.print_banner( "Releasing GPU memory... AFTER", prepend_nl=True )
            print_gpu_memory()

        if post_training_stats:
            stage_timer = Stopwatch( msg=None )
            vllm_server_process = None
            try:
                # Start vLLM server and wait for it to be available
                vllm_server_process = self._start_vllm_server( merged_adapter_dir )

                # Use the bare directory path — vLLM was started with this exact path as the model name
                model = merged_adapter_dir
                result = self.run_validation(
                    banner_prefix="POST-training:", model=model, path_prefix=lupin_root, switch="deepily", device_map="cuda:0",
                    validation_sample_size=validation_sample_size, debug=self.debug, verbose=self.verbose,
                    vllm_base_url="http://192.168.1.21:3000/v1/completions"
                )
                self.validation_results.append( result )
            finally:
                # Always clean up the vLLM server process if it was started
                if vllm_server_process: self._stop_vllm_server( vllm_server_process )
                # release GPUs -- with prejudice -- before doing anything else
                release_gpus( [ self.model, self.tokenizer ], nuclear_kill_button=nuclear_kill_button )
                # Wait for GPU memory to actually be freed (vLLM process cleanup is async)
                if not self._wait_for_gpu_memory_release():
                    print( "Attempting forced GPU cache clear..." )
                    torch.cuda.empty_cache()
                    gc.collect()
                    time.sleep( 5 )
                du.print_banner( "Releasing GPU memory... AFTER", prepend_nl=True )
                print_gpu_memory()
            self.stage_timings[ "post_training_validation" ] = stage_timer.get_delta_ms()
        else:
            print( f"Skipping post-training validation for {args.model_name}" )

        # Quantize the merged adapter — loop over requested bit widths
        quantize_bits_list = self._parse_quantize_bits( quantize_bits )
        self.quantized_model_dirs = {}

        # Load vllm_config for quantization kernel hint (e.g. gptq_marlin)
        vllm_config = load_model_config( self.model_name ).get( "vllm", {} )

        for bits in quantize_bits_list:

            stage_timer = Stopwatch( msg=None )
            quantized_model_dir = self.quantize_merged_adapter( merged_adapter_dir=merged_adapter_dir, bits=bits )
            self.stage_timings[ f"quantization_{bits}bit" ] = stage_timer.get_delta_ms()

            if post_quantization_stats:
                stage_timer = Stopwatch( msg=None )
                vllm_server_process = None
                quantization_hint = vllm_config.get( "quantization", None )
                try:
                    # Start vLLM server and wait for it to be available
                    vllm_server_process = self._start_vllm_server( quantized_model_dir, quantization=quantization_hint, verbose_server=True )

                    # Use the bare directory path — vLLM was started with this exact path as the model name
                    model = quantized_model_dir
                    result = self.run_validation(
                        banner_prefix=f"POST-quantization ({bits}-bit):", model=model, path_prefix=lupin_root, switch="deepily", device_map="cuda:0",
                        validation_sample_size=validation_sample_size, debug=self.debug, verbose=self.verbose,
                        vllm_base_url="http://192.168.1.21:3000/v1/completions"
                    )
                    self.validation_results.append( result )
                finally:
                    # Always clean up the vLLM server process if it was started
                    if vllm_server_process: self._stop_vllm_server( vllm_server_process )
                    # release GPU before doing anything else
                    release_gpus( [ self.model, self.tokenizer ] )
                    # Wait for GPU memory to actually be freed (vLLM process cleanup is async)
                    if not self._wait_for_gpu_memory_release():
                        print( "Attempting forced GPU cache clear..." )
                        torch.cuda.empty_cache()
                        gc.collect()
                        time.sleep( 5 )
                    du.print_banner( "Releasing GPU memory... AFTER", prepend_nl=True )
                    print_gpu_memory()
                self.stage_timings[ f"post_quantization_{bits}bit_validation" ] = stage_timer.get_delta_ms()
            else:
                print( f"Skipping post-quantization ({bits}-bit) validation for {args.model_name}" )

        # Print completion information
        print()
        bits_label = " and ".join( [ f"{b}-bit" for b in quantize_bits_list ] )
        if resume_from_merged:
            msg = f"Finished validation and quantizing ({bits_label}) from merged adapter: {resume_from_merged}"
        else:
            msg = f"Finished fine-tuning, merging and quantizing ({bits_label}) {args.model_name}"
        timer.print( msg )
        self.stage_timings[ "total_pipeline" ] = timer.get_delta_ms()
        du.print_banner( msg )
        for bits, qdir in self.quantized_model_dirs.items():
            print( f"Quantized model ({bits}-bit): {qdir}" )
            du.print_simple_file_list( qdir )

        # Print consolidated training summary dashboard
        if self.validation_results:
            self._print_training_summary()

        # Write training results to markdown file
        try:
            results_path = self._write_training_summary_to_file()
            print( f"Training results written to: {results_path}" )
        except Exception as e:
            print( f"Warning: Failed to write training results file: {e}" )

        # Update ~/.lora_env with the latest quantized model path
        try:
            self._update_lora_env()
            du.print_banner( f"Updated ~/.lora_env with new {self.model_name} path" )
            print( "Run 'source ~/.bashrc' or open a new terminal for the changes to take effect." )
        except Exception as e:
            print( f"Warning: Failed to update ~/.lora_env: {e}" )


def check_env() -> str:
    """
    Verifies that required environment variables are set for proper application functioning.

    Requires:
        - None (checks environment state)

    Ensures:
        - All required variables validated
        - Missing variables reported
        - Returns LUPIN_ROOT path
        - Exits if variables missing

    Raises:
        - SystemExit if variables missing
    """
    required_vars = [
        ( "HF_HOME", "/some/foo/path" ),
        ( "NCCL_P2P_DISABLE", "1" ),
        ( "NCCL_IB_DISABLE", "1" ),
        ( "LUPIN_ROOT", "/some/foo/path" ),
        ( "LUPIN_CONFIG_MGR_CLI_ARGS", "" ),
        ( "DEEPILY_PROJECTS_DIR", "/mnt/DATA01/include/www.deepily.ai/projects" )
    ]
    
    missing_vars = False
    
    for name, val in required_vars:
        if not os.getenv( name ):
            print( f"Please set env variable {name}={val}" )
            missing_vars = True
    
    if missing_vars:
        print( "Exiting due to missing environment variables" )
        sys.exit( 1 )
    
    return os.getenv( "LUPIN_ROOT" )


def check_privileges(debug: bool=False) -> None:
    """
    Checks if the script is running with root privileges or with sudo.
    
    Requires:
        - None (checks process state)
    
    Ensures:
        - Root/sudo status checked
        - Confirmation messages printed
        - Exits if not elevated
    
    Raises:
        - SystemExit if not elevated
    """
    print( "Checking credentials..." )
    if is_root():
        if invoked_with_sudo():
            if debug: print( "✅ Running under sudo (uid 0, SUDO_UID present)" )
        else:
            if debug: print( "⚠️ Running as root but not via sudo (e.g. direct root or setuid)" )
    else:
        du.print_banner( "❌ Wait! You're not running with elevated privileges?!?", prepend_nl=True )
        print( "This is a long running -- up to three or four hours -- process that occasionally needs to hit the nuclear reset button for GPU memory." )
        print( "Because of this you will need to execute this module using `sudo` as a prefix so that we can dislodge the occasional pesky stuck memory" )
        print( "allocations w/o having to wake you up at midnight to present your credentials just so we can finish the last 1/3 of the run." )
        print()
        print( "You'll need to insert the following [bits] *between* 'sudo' and the Python interpreter:" )
        print( 'sudo [--preserve-env=HF_HOME,NCCL_P2P_DISABLE,NCCL_IB_DISABLE,LUPIN_ROOT,LUPIN_CONFIG_MGR_CLI_ARGS,DEEPILY_PROJECTS_DIR env "PATH=$PATH"] python -m cosa.training.peft_trainer ...' )
        print()
        sys.exit( 1 )


def parse_arguments() -> argparse.Namespace:
    """
    Parses command line arguments for the PEFT trainer application.

    Requires:
        - Script run with command line arguments

    Ensures:
        - Arguments parsed and validated
        - Returns Namespace with arguments
        - Required args present
        - Optional args have defaults

    Returns:
        - argparse.Namespace: Parsed arguments
    """
    
    parser = argparse.ArgumentParser( description="PEFT trainer for language models" )
    
    # Required arguments
    parser.add_argument( "--model",                type=str, help="Model HuggingFace ID" )
    parser.add_argument( "--model-name",           type=str, help="Model name" )
    parser.add_argument( "--test-train-path",      type=str, help="Path to test/train data" )
    parser.add_argument( "--lora-dir",             type=str, help="Directory for LORA files" )
    
    # Optional arguments
    parser.add_argument( "--debug",                   action="store_true", help="Enable debug mode",                          default=False )
    parser.add_argument( "--verbose",                 action="store_true", help="Enable verbose mode",                        default=False )
    parser.add_argument( "--pre-training-stats",      action="store_true", help="Run validation before training",             default=False )
    parser.add_argument( "--post-training-stats",     action="store_true", help="Run validation after training and merging",  default=False )
    parser.add_argument( "--post-quantization-stats", action="store_true", help="Run validation after quantization",          default=False )
    parser.add_argument( "--nuclear-kill-button",     action="store_true", help="Enable nuclear option for GPU memory reset", default=False )
    parser.add_argument( "--dry-run",                  action="store_true", help="Show training data stats without training",   default=False )

    parser.add_argument( "--validation-sample-size",  type=int,            help="Sample size for validation",                                  default=100 )
    parser.add_argument( "--sample-size",             type=float,          help="Training data sample size (0.0-1.0, overrides model config)", default=None )
    parser.add_argument( "--quantize-bits",           type=str,            help="Quantization bits: both, 4, or 8",                            default="both",
                                                      choices=[ "both", "4", "8" ] )
    parser.add_argument( "--resume-from-merged",      type=str,            help="Path to existing merged adapter dir; skips training and merge phases", default=None )
    parser.add_argument( "--update-lora-env",         type=str, metavar="RESULTS_FILE",
                                                      help="Update ~/.lora_env from a training results file (skips training entirely)", default=None )

    return parser.parse_args()

# NOTE: The actual __main__ block is below quick_smoke_test()


def quick_smoke_test():
    """
    LIGHTWEIGHT STRUCTURAL smoke test for PeftTrainer - validates architecture only.
    
    ⚠️  IMPORTANT: This test validates STRUCTURE ONLY, not runtime ML behavior.
    ⚠️  This module requires significant GPU resources, datasets, and time for actual operation.
    ⚠️  This smoke test only verifies the module can be imported and basic structure accessed.
    
    This test is essential for v000 deprecation as peft_trainer.py is critical
    for model fine-tuning infrastructure, but too resource-intensive for full testing.
    """
    import cosa.utils.util as du
    
    du.print_banner( "PEFT Trainer STRUCTURAL Smoke Test", prepend_nl=True )
    print( "⚠️  STRUCTURAL TESTING ONLY - No ML operations will be performed" )
    print( "⚠️  This test validates imports and architecture, not runtime behavior" )
    print()
    
    try:
        # Test 1: Core class and function structure
        print( "Testing core PEFT trainer structure..." )
        
        # Test that PeftTrainer class exists and basic methods are present
        expected_methods = [
            "login_to_hf", "get_training_prompt_stats", "fine_tune", "save_model",
            "run_validation", "load_and_merge_adapter", "save_merged_adapter", 
            "quantize_merged_adapter", "get_prompt", "set_hf_env_vars", 
            "set_lupin_env_vars", "run_pipeline"
        ]
        
        methods_found = 0
        for method_name in expected_methods:
            if hasattr( PeftTrainer, method_name ):
                methods_found += 1
            else:
                print( f"⚠ Missing method: {method_name}" )
        
        if methods_found == len( expected_methods ):
            print( f"✓ All {len( expected_methods )} core PeftTrainer methods present" )
        else:
            print( f"⚠ Only {methods_found}/{len( expected_methods )} PeftTrainer methods present" )
        
        # Test static utility functions
        utility_functions = [ "is_root", "invoked_with_sudo", "print_gpu_memory", "release_gpus" ]
        utils_found = 0
        for func_name in utility_functions:
            if func_name in globals():
                utils_found += 1
            else:
                print( f"⚠ Missing utility function: {func_name}" )
        
        if utils_found == len( utility_functions ):
            print( f"✓ All {len( utility_functions )} utility functions present" )
        else:
            print( f"⚠ Only {utils_found}/{len( utility_functions )} utility functions present" )
        
        # Test module-level functions
        module_functions = [ "check_env", "check_privileges", "parse_arguments" ]
        module_funcs_found = 0
        for func_name in module_functions:
            if func_name in globals():
                module_funcs_found += 1
            else:
                print( f"⚠ Missing module function: {func_name}" )
        
        if module_funcs_found == len( module_functions ):
            print( f"✓ All {len( module_functions )} module functions present" )
        else:
            print( f"⚠ Only {module_funcs_found}/{len( module_functions )} module functions present" )
        
        # Test 2: Critical import validation (lightweight - no actual ML loading)
        print( "Testing critical import statements..." )
        
        # Test standard library imports
        try:
            import gc, sys, json, pandas, argparse, time, subprocess, threading, requests
            print( "✓ Standard library imports successful" )
        except ImportError as e:
            print( f"✗ Standard library imports failed: {e}" )
        
        # Test ML framework imports (just import, don't use)
        try:
            import torch, os, multiprocessing
            from typing import Optional, Union, List, Dict, Tuple, Any, Iterable
            print( "✓ Core framework imports successful" )
        except ImportError as e:
            print( f"✗ Core framework imports failed: {e}" )
        
        # Test PEFT and transformer imports
        try:
            from peft import LoraConfig, prepare_model_for_kbit_training, PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed
            from datasets import Dataset
            from trl import SFTTrainer, SFTConfig
            print( "✓ ML library imports successful" )
        except ImportError as e:
            print( f"⚠ ML library imports failed (may be expected in test env): {e}" )
        
        # Test CoSA internal imports
        try:
            from cosa.training.conf.model_config_loader import load_model_config
            import cosa.utils.util as du
            import cosa.utils.util_pytorch as dupt
            from cosa.training.quantizer import Quantizer
            from cosa.utils.util_stopwatch import Stopwatch
            from cosa.training.xml_coordinator import XmlCoordinator
            print( "✓ CoSA internal imports successful" )
        except ImportError as e:
            print( f"⚠ CoSA internal imports failed: {e}" )
        
        # Test 3: Configuration integration (without loading models)
        print( "Testing configuration integration..." )
        try:
            # Test that we can access model config loading (without calling it)
            if callable( load_model_config ):
                print( "✓ Model config loading function available" )
            else:
                print( "✗ Model config loading function not callable" )
        except Exception as e:
            print( f"⚠ Configuration integration issues: {e}" )
        
        # Test 4: Basic PeftTrainer instantiation (minimal params)
        print( "Testing basic PeftTrainer instantiation..." )
        try:
            # Test with minimal mock parameters - should not trigger ML operations
            test_trainer = PeftTrainer(
                model_hf_id="mock_model_id",
                model_name="Mistral-7B-Instruct-v0.2",  # Use a known supported model
                test_train_path="/mock/path",
                debug=False,
                verbose=False
            )
            
            # Check basic attributes are set
            if ( hasattr( test_trainer, 'model_hf_id' ) and 
                 hasattr( test_trainer, 'model_name' ) and
                 hasattr( test_trainer, 'debug' ) ):
                print( "✓ PeftTrainer basic instantiation working" )
            else:
                print( "✗ PeftTrainer instantiation missing attributes" )
                
        except Exception as e:
            print( f"⚠ PeftTrainer instantiation issues: {e}" )
        
        # Test 5: Argument parsing validation
        print( "Testing argument parsing..." )
        try:
            # Test parse_arguments function structure (not actual parsing)
            if callable( parse_arguments ):
                print( "✓ Argument parsing function available" )
            else:
                print( "✗ Argument parsing function not callable" )
        except Exception as e:
            print( f"⚠ Argument parsing issues: {e}" )
        
        # Test 6: Environment checking capability
        print( "Testing environment validation..." )
        try:
            # Test check_env function exists and is callable
            if callable( check_env ):
                print( "✓ Environment checking function available" )
            else:
                print( "✗ Environment checking function not callable" )
                
            # Test check_privileges function
            if callable( check_privileges ):
                print( "✓ Privileges checking function available" )
            else:
                print( "✗ Privileges checking function not callable" )
        except Exception as e:
            print( f"⚠ Environment validation issues: {e}" )
        
        # Test 7: Critical v000 dependency scanning
        print( "\\n🔍 Scanning for v000 dependencies..." )
        
        # Scan the file for v000 patterns
        import inspect
        source_file = inspect.getfile( PeftTrainer )
        
        v000_found = False
        v000_patterns = []
        
        with open( source_file, 'r' ) as f:
            content = f.read()
            
            # Split content and exclude smoke test function
            lines = content.split( '\\n' )
            in_smoke_test = False
            
            for i, line in enumerate( lines ):
                stripped_line = line.strip()
                
                # Track if we're in the smoke test function
                if "def quick_smoke_test" in line:
                    in_smoke_test = True
                    continue
                elif in_smoke_test and line.startswith( "def " ):
                    in_smoke_test = False
                elif in_smoke_test:
                    continue
                
                # Skip comments and docstrings
                if ( stripped_line.startswith( '#' ) or 
                     stripped_line.startswith( '"""' ) or
                     stripped_line.startswith( "'" ) ):
                    continue
                
                # Look for actual v000 code references
                if "v000" in stripped_line and any( pattern in stripped_line for pattern in [
                    "import", "from", "cosa.agents.v000", ".v000."
                ] ):
                    v000_found = True
                    v000_patterns.append( f"Line {i+1}: {stripped_line}" )
        
        if v000_found:
            print( "🚨 CRITICAL: v000 dependencies detected!" )
            print( "   Found v000 references:" )
            for pattern in v000_patterns[ :3 ]:  # Show first 3
                print( f"     • {pattern}" )
            if len( v000_patterns ) > 3:
                print( f"     ... and {len( v000_patterns ) - 3} more v000 references" )
            print( "   ⚠️  These dependencies MUST be resolved before v000 deprecation!" )
        else:
            print( "✅ EXCELLENT: No v000 dependencies found!" )
        
        # Test 8: Supported models validation
        print( "\\nTesting supported models configuration..." )
        try:
            # Create instance to check supported models
            test_trainer = PeftTrainer(
                model_hf_id="mock_model_id",
                model_name="Mistral-7B-Instruct-v0.2",
                test_train_path="/mock/path"
            )
            
            if hasattr( test_trainer, 'supported_model_names' ):
                model_count = len( test_trainer.supported_model_names )
                print( f"✓ Supported models list available ({model_count} models)" )
            else:
                print( "⚠ Supported models list not found" )
                
        except Exception as e:
            print( f"⚠ Supported models validation issues: {e}" )
        
        # Test 9: Method signature validation
        print( "\\nTesting critical method signatures..." )
        try:
            critical_methods = [ 'fine_tune', 'run_pipeline', 'quantize_merged_adapter' ]
            
            for method_name in critical_methods:
                if hasattr( PeftTrainer, method_name ):
                    method = getattr( PeftTrainer, method_name )
                    if callable( method ):
                        print( f"✓ {method_name} method is callable" )
                    else:
                        print( f"✗ {method_name} method is not callable" )
                else:
                    print( f"✗ Missing critical method: {method_name}" )
                    
        except Exception as e:
            print( f"⚠ Method signature validation issues: {e}" )
    
    except Exception as e:
        print( f"✗ Error during PEFT trainer structural testing: {e}" )
        import traceback
        traceback.print_exc()
    
    # Summary
    print( "\\n" + "="*70 )
    print( "🔧 STRUCTURAL TEST SUMMARY - PEFT TRAINER" )
    print( "="*70 )
    
    if v000_found:
        print( "🚨 CRITICAL ISSUE: PEFT trainer has v000 dependencies!" )
        print( "   Status: NOT READY for v000 deprecation" )
        print( "   Priority: IMMEDIATE ACTION REQUIRED" )
        print( "   Risk Level: CRITICAL - ML training infrastructure will break" )
    else:
        print( "✅ PEFT trainer structural validation completed successfully!" )
        print( "   Status: ML training infrastructure structure ready for v000 deprecation" )
        print( "   Risk Level: LOW" )
    
    print()
    print( "⚠️  IMPORTANT REMINDER:" )
    print( "   This was a STRUCTURAL test only - no ML operations were performed" )
    print( "   Runtime validation requires GPU resources, datasets, and extensive time" )
    print( "   Full training pipeline validation should be done separately in ML environment" )
    print()
    print( "✓ PEFT trainer structural smoke test completed" )


if __name__ == "__main__":
    import sys
    
    # Check if this is being run as a smoke test
    if len( sys.argv ) == 1 or (len( sys.argv ) == 2 and sys.argv[1] == "--smoke-test"):
        quick_smoke_test()
        sys.exit( 0 )
    
    # Otherwise run normal training pipeline

    # Check for required environment variables
    lupin_root = check_env()

    # Validate command line arguments
    args = parse_arguments()

    # Standalone env update mode: parse results file, update ~/.lora_env, exit
    if args.update_lora_env:
        import yaml
        results_file = args.update_lora_env
        if not os.path.exists( results_file ):
            print( f"Error: Results file not found: {results_file}" )
            sys.exit( 1 )

        # Parse YAML frontmatter from the results file
        with open( results_file, "r" ) as f:
            content = f.read()
        if not content.startswith( "---" ):
            print( f"Error: Results file does not contain YAML frontmatter: {results_file}" )
            sys.exit( 1 )

        # Extract frontmatter between first and second ---
        parts      = content.split( "---", 2 )
        # Note: yaml.unsafe_load needed because training results contain numpy-serialized scalars
        frontmatter = yaml.unsafe_load( parts[ 1 ] )

        model_name           = frontmatter[ "model_name" ]
        quantized_model_dirs = {}
        for bits_str, path in frontmatter.get( "quantized_model_dirs", {} ).items():
            quantized_model_dirs[ int( bits_str ) ] = path

        if not quantized_model_dirs:
            print( f"Error: No quantized_model_dirs found in results file" )
            sys.exit( 1 )

        du.print_banner( f"Updating ~/.lora_env from results file: {results_file}" )
        print( f"Model: {model_name}" )
        for bits, path in sorted( quantized_model_dirs.items() ):
            print( f"  {bits}-bit: {path}" )

        # Create a minimal trainer-like object to call _update_lora_env
        # We use __new__ to avoid __init__'s GPU/model validation
        trainer                      = object.__new__( PeftTrainer )
        trainer.model_name           = model_name
        trainer.quantized_model_dirs = quantized_model_dirs
        trainer.debug                = args.debug if hasattr( args, "debug" ) else False
        trainer._update_lora_env()

        # Print the updated env vars
        env_file = os.path.expanduser( "~/.lora_env" )
        if os.path.exists( env_file ):
            print()
            with open( env_file, "r" ) as f:
                print( f.read() )
        print( "Run 'source ~/.bashrc' or open a new terminal for the changes to take effect." )
        sys.exit( 0 )

    # Check for nuclear_kill_button + elevated privileges
    if args.nuclear_kill_button:
        if args.debug: print( "Nuclear kill button is enabled..." )
        check_privileges( debug=args.debug )
    else:
        if args.debug: print( "Nuclear kill button is disabled..." )

    # instantiate a trainer...
    trainer = PeftTrainer(
        args.model, args.model_name, args.test_train_path, lora_dir=args.lora_dir, debug=args.debug, verbose=args.verbose
    )

    # ... And you're off to the races!
    trainer.run_pipeline(
        pre_training_stats=args.pre_training_stats,
        post_training_stats=args.post_training_stats,
        post_quantization_stats=args.post_quantization_stats,
        validation_sample_size=args.validation_sample_size,
        nuclear_kill_button=args.nuclear_kill_button,
        sample_size_override=args.sample_size,
        dry_run=args.dry_run,
        quantize_bits=args.quantize_bits,
        resume_from_merged=args.resume_from_merged
    )
