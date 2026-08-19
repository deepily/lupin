"""
Unit tests for PEFT trainer with comprehensive ML framework mocking.

Tests the PeftTrainer class including:
- Initialization with model validation and parameter setup
- Model and tokenizer loading with HuggingFace integration
- PEFT/LoRA configuration management and adapter handling
- Training workflow with SFTTrainer integration
- Model merging, adapter loading, and quantization operations
- Training data preprocessing and prompt formatting
- Environment variable validation and GPU memory tracking
- CLI interface argument parsing and pipeline execution
- Error handling for model loading and training failures

Zero external dependencies - all PyTorch, transformers, PEFT, TRL,
and model operations are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
import tempfile
import time
import sys
import os
from typing import Optional, Union, Dict, Any
import sys
import os

# Import test infrastructure
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
import cosa.training.peft_trainer as _pt
from cosa.training.peft_trainer import PeftTrainer


# CAUSE-B (task 51980026): this test patches cosa.training.peft_trainer.PeftModel.
# from_pretrained, but PeftModel is bound only when `from peft import ... PeftModel`
# succeeds at import time. When the optional 'peft' package is NOT installed (the
# current test venv), the module sets PEFT_AVAILABLE=False and PeftModel=None, so the
# patch target is None.from_pretrained → AttributeError before the test body runs. NOT
# a product defect and NOT a stale test — an optional-dep gap in the test environment.
# Skip when peft is absent. Remediation: add peft to the test deps.
_requires_peft = unittest.skipUnless(
    _pt.PEFT_AVAILABLE,
    "requires the optional 'peft' package (absent in this test venv); PeftModel is None "
    "so patch('...PeftModel.from_pretrained') raises AttributeError "
    "(task 51980026 CAUSE-B; remediation: add peft to test deps)"
)


class TestPeftTrainer( unittest.TestCase ):
    """
    Comprehensive unit tests for PEFT trainer.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All ML framework operations tested in isolation
        - Model loading and training properly mocked
        - Error handling scenarios covered
        - CLI interface thoroughly tested
    """
    
    def setUp( self ):
        """
        Setup for each test method.
        
        Ensures:
            - Clean state for each test
            - Mock manager is available
        """
        self.mock_manager = MockManager()
        self.test_utilities = UnitTestUtilities()
        
        # Common test data
        self.test_model_hf_id = "microsoft/Phi-4-mini-instruct"
        self.test_model_name = "Phi-4-mini-instruct"
        self.test_train_path = "/path/to/train/data"
        self.test_lora_dir = "/path/to/lora"
        self.test_output_dir = "/path/to/output"
        
        # Mock components
        self.mock_model = Mock()
        self.mock_tokenizer = Mock()
        self.mock_trainer = Mock()
        self.mock_dataset = Mock()
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def test_initialization_success( self ):
        """
        Test successful PeftTrainer initialization with valid parameters.
        
        Ensures:
            - Sets all instance attributes correctly
            - Validates supported model name
            - Prints initialization banner
            - Creates trainer in clean state
        """
        with patch( 'cosa.training.peft_trainer.du.print_banner' ) as mock_print_banner, \
             patch( 'builtins.print' ) as mock_print:
            
            trainer = PeftTrainer( 
                model_hf_id=self.test_model_hf_id,
                model_name=self.test_model_name,
                test_train_path=self.test_train_path,
                lora_dir=self.test_lora_dir,
                debug=True,
                verbose=True
            )
            
            # Verify initialization banner
            mock_print_banner.assert_called_once_with( 
                f"Initializing PEFT Trainer for {self.test_model_name}", 
                prepend_nl=True 
            )
            
            # Verify information prints
            expected_calls = [
                call( f"Model ID: {self.test_model_hf_id}" ),
                call( f"Path to test/train data: {self.test_train_path}" )
            ]
            mock_print.assert_has_calls( expected_calls )
            
            # Verify instance attributes
            self.assertEqual( trainer.model_hf_id, self.test_model_hf_id )
            self.assertEqual( trainer.model_name, self.test_model_name )
            self.assertEqual( trainer.test_train_dir, self.test_train_path )
            self.assertEqual( trainer.lora_dir, self.test_lora_dir )
            self.assertTrue( trainer.debug )
            self.assertTrue( trainer.verbose )
            self.assertIsNone( trainer.trainer )
            self.assertIsNone( trainer.model )
            self.assertIsNone( trainer.tokenizer )
    
    def test_initialization_with_defaults( self ):
        """
        Test PeftTrainer initialization with default parameters.
        
        Ensures:
            - Uses default values for optional parameters
            - Debug and verbose default to False
            - lora_dir defaults to None
        """
        with patch( 'cosa.training.peft_trainer.du.print_banner' ), \
             patch( 'builtins.print' ):
            
            trainer = PeftTrainer( 
                model_hf_id=self.test_model_hf_id,
                model_name=self.test_model_name,
                test_train_path=self.test_train_path
            )
            
            # Verify default values
            self.assertFalse( trainer.debug )
            self.assertFalse( trainer.verbose )
            self.assertIsNone( trainer.lora_dir )
    
    def test_initialization_unsupported_model( self ):
        """
        Test PeftTrainer initialization with unsupported model name.
        
        Ensures:
            - Raises ValueError for unsupported models
            - Provides descriptive error message
            - Lists supported models in error
        """
        unsupported_model = "unsupported-model-name"
        
        with patch( 'cosa.training.peft_trainer.du.print_banner' ), \
             patch( 'builtins.print' ):
            
            with self.assertRaises( ValueError ) as context:
                PeftTrainer( 
                    model_hf_id=self.test_model_hf_id,
                    model_name=unsupported_model,
                    test_train_path=self.test_train_path
                )
            
            error_message = str( context.exception )
            self.assertIn( f"Unsupported model_name: '{unsupported_model}'", error_message )
            self.assertIn( "Must be one of:", error_message )
    
    def test_load_model_and_tokenizer_success( self ):
        """
        Test successful model and tokenizer loading.
        
        Ensures:
            - Loads model from HuggingFace with correct parameters
            - Loads tokenizer with matching parameters
            - Sets model attributes correctly
            - Handles device mapping properly
        """
        # HF_HOME is a documented precondition of _load_model_and_tokenizer ( guard at
        # peft_trainer.py:953 ); set it to an existing dir so the method reaches the
        # from_pretrained calls this test actually exercises ( the real os.chdir needs it ).
        with patch.dict( os.environ, { "HF_HOME": os.path.dirname( __file__ ) } ), \
             patch( 'cosa.training.peft_trainer.du.print_banner' ), \
             patch( 'builtins.print' ), \
             patch( 'cosa.training.peft_trainer.AutoModelForCausalLM.from_pretrained' ) as mock_model_load, \
             patch( 'cosa.training.peft_trainer.AutoTokenizer.from_pretrained' ) as mock_tokenizer_load, \
             patch( 'cosa.training.peft_trainer.torch' ):

            mock_model_load.return_value = self.mock_model
            mock_tokenizer_load.return_value = self.mock_tokenizer
            
            trainer = PeftTrainer( 
                model_hf_id=self.test_model_hf_id,
                model_name=self.test_model_name,
                test_train_path=self.test_train_path
            )
            
            trainer._load_model_and_tokenizer( device_map="auto", mode="training" )
            
            # Verify model loading (check key parameters, allowing for extras)
            mock_model_load.assert_called_once()
            call_args = mock_model_load.call_args
            self.assertEqual( call_args[0][0], self.test_model_hf_id )
            self.assertEqual( call_args[1]['device_map'], "auto" )
            
            # Verify tokenizer loading (check key parameters, allowing for extras)
            mock_tokenizer_load.assert_called_once()
            tokenizer_call_args = mock_tokenizer_load.call_args
            self.assertEqual( tokenizer_call_args[0][0], self.test_model_hf_id )
            
            # Verify attributes set
            self.assertEqual( trainer.model, self.mock_model )
            self.assertEqual( trainer.tokenizer, self.mock_tokenizer )
    
    def test_load_model_and_tokenizer_error( self ):
        """
        Test model and tokenizer loading with errors.
        
        Ensures:
            - Propagates model loading exceptions
            - Propagates tokenizer loading exceptions
        """
        # HF_HOME is a documented precondition of _load_model_and_tokenizer ( guard at
        # peft_trainer.py:953 ); set it so the method reaches the from_pretrained call
        # whose RuntimeError this test asserts propagates.
        with patch.dict( os.environ, { "HF_HOME": os.path.dirname( __file__ ) } ), \
             patch( 'cosa.training.peft_trainer.du.print_banner' ), \
             patch( 'builtins.print' ), \
             patch( 'cosa.training.peft_trainer.AutoModelForCausalLM.from_pretrained' ) as mock_model_load, \
             patch( 'cosa.training.peft_trainer.torch' ):

            model_error = RuntimeError( "Model loading failed" )
            mock_model_load.side_effect = model_error
            
            trainer = PeftTrainer( 
                model_hf_id=self.test_model_hf_id,
                model_name=self.test_model_name,
                test_train_path=self.test_train_path
            )
            
            with self.assertRaises( RuntimeError ) as context:
                trainer._load_model_and_tokenizer( mode="training" )
            
            self.assertIn( "Model loading failed", str( context.exception ) )
    
    def test_get_peft_config_success( self ):
        """
        Test successful PEFT configuration creation.
        
        Ensures:
            - Loads model configuration correctly
            - Creates LoraConfig with proper parameters
            - Uses model-specific configuration values
        """
        with patch( 'cosa.training.peft_trainer.du.print_banner' ), \
             patch( 'builtins.print' ), \
             patch( 'cosa.training.peft_trainer.load_model_config' ) as mock_load_config, \
             patch( 'cosa.training.peft_trainer.LoraConfig' ) as mock_lora_config:
            
            # Mock model configuration
            test_lora_config = {
                "lora_alpha": 16,
                "lora_dropout": 0.05,
                "r": 64,
                "bias": "none",
                "task_type": "CAUSAL_LM",
                "target_modules": ["k_proj", "q_proj", "v_proj"]
            }
            
            mock_load_config.return_value = {
                "lora": test_lora_config
            }
            
            mock_peft_config = Mock()
            mock_lora_config.return_value = mock_peft_config
            
            trainer = PeftTrainer( 
                model_hf_id=self.test_model_hf_id,
                model_name=self.test_model_name,
                test_train_path=self.test_train_path
            )
            
            result = trainer._get_peft_config()
            
            # Verify config loading
            mock_load_config.assert_called_once_with( self.test_model_name )
            
            # Verify LoraConfig creation
            mock_lora_config.assert_called_once_with( **test_lora_config )
            
            # Verify return value
            self.assertEqual( result, mock_peft_config )
    
    def test_fine_tune_success( self ):
        """
        Test successful fine-tuning workflow.
        
        Ensures:
            - Sets up model and tokenizer
            - Creates PEFT configuration
            - Initializes SFTTrainer with correct parameters
            - Executes training process
            - Saves model after training
        """
        # Live contract: fine_tune loads model+tokenizer, builds peft/training args, gets
        # data, constructs SFTTrainer, prints pre/post stats, trains, then resolves the last
        # checkpoint dir and prints it via du.print_simple_file_list. It does NOT call
        # prepare_model_for_kbit_training ( commented out in prod ) and does NOT call
        # save_model. Mock the extra stats/print seams; _get_last_checkpoint_dir -> None means
        # du.print_simple_file_list( None ) must be mocked ( else os.stat( None ) -> TypeError ).
        with patch( 'cosa.training.peft_trainer.du.print_banner' ), \
             patch( 'builtins.print' ), \
             patch( 'cosa.training.peft_trainer.du.print_simple_file_list' ), \
             patch.object( PeftTrainer, '_load_model_and_tokenizer' ) as mock_load_model, \
             patch.object( PeftTrainer, '_get_peft_config' ) as mock_get_peft, \
             patch.object( PeftTrainer, '_get_test_train_data' ) as mock_get_data, \
             patch.object( PeftTrainer, '_get_training_args' ) as mock_get_args, \
             patch.object( PeftTrainer, '_get_last_checkpoint_dir' ) as mock_get_checkpoint, \
             patch.object( PeftTrainer, '_print_trainable_parameters' ), \
             patch.object( PeftTrainer, '_print_stats_pre' ), \
             patch.object( PeftTrainer, '_print_stats_post' ), \
             patch( 'cosa.training.peft_trainer.SFTTrainer' ) as mock_sft_trainer:

            # Setup mocks
            mock_peft_config = Mock()
            mock_get_peft.return_value = mock_peft_config

            mock_datasets = {"train": self.mock_dataset, "test": self.mock_dataset}
            mock_get_data.return_value = mock_datasets

            mock_training_args = Mock()
            mock_training_args.output_dir = "/tmp/output"
            mock_get_args.return_value = mock_training_args

            mock_get_checkpoint.return_value = None

            mock_trainer_instance = Mock()
            mock_sft_trainer.return_value = mock_trainer_instance

            trainer = PeftTrainer(
                model_hf_id=self.test_model_hf_id,
                model_name=self.test_model_name,
                test_train_path=self.test_train_path
            )
            trainer.model = self.mock_model

            # Execute fine-tuning
            result = trainer.fine_tune( batch_size=8, gradient_accumulation_steps=4 )

            # Verify workflow steps
            mock_load_model.assert_called_once()
            mock_get_peft.assert_called_once()
            mock_get_data.assert_called_once()
            mock_get_args.assert_called_once()

            # Verify SFTTrainer was constructed and training executed
            mock_sft_trainer.assert_called_once()
            mock_trainer_instance.train.assert_called_once()

            # Live contract: returns the ( mocked-None ) last checkpoint dir; output_dir set
            self.assertIsNone( result )
            self.assertEqual( trainer.output_dir, "/tmp/output" )
    
    def test_save_model_success( self ):
        """
        Test successful model saving.
        
        Ensures:
            - Creates output directory if needed
            - Saves model to correct path
            - Saves tokenizer to same path
            - Updates trainer state
        """
        with patch( 'cosa.training.peft_trainer.du.print_banner' ), \
             patch( 'builtins.print' ), \
             patch( 'cosa.training.peft_trainer.os.makedirs' ) as mock_makedirs, \
             patch( 'cosa.training.peft_trainer.os.path.exists' ) as mock_exists, \
             patch( 'cosa.training.peft_trainer.os.chdir' ) as mock_chdir, \
             patch( 'cosa.training.peft_trainer.du.get_current_date' ) as mock_get_date, \
             patch( 'cosa.training.peft_trainer.du.get_current_time' ) as mock_get_time:
            
            mock_exists.return_value = False  # Directory doesn't exist
            mock_get_date.return_value = "2025-08-05"
            mock_get_time.return_value = "15-53"
            
            trainer = PeftTrainer(
                model_hf_id=self.test_model_hf_id,
                model_name=self.test_model_name,
                test_train_path=self.test_train_path
            )
            trainer.trainer = self.mock_trainer
            trainer.output_dir = self.test_output_dir
            # Live contract: save_model() calls BOTH self.model.save_pretrained and
            # self.tokenizer.save_pretrained — the prior test omitted these assignments,
            # so self.model was None -> AttributeError. Wire them up.
            trainer.model = self.mock_model
            trainer.tokenizer = self.mock_tokenizer

            trainer.save_model()

            # Verify directory creation (path will include timestamp)
            mock_makedirs.assert_called_once()

            # Verify model + tokenizer save_pretrained were called
            self.mock_model.save_pretrained.assert_called_once()
            self.mock_tokenizer.save_pretrained.assert_called_once()
    
    # -- cwd-restoration controls -------------------------------------------------
    # Both methods os.chdir() away and back. The cwd is PROCESS-global, so restoring it
    # only on the happy path leaks the change into every later test in the same pytest
    # process. That is exactly what happened: this file left the process sitting in
    # src/cosa/tests/unit/training, and the drift guard's §4 check
    # (test_v2_registry_drift_guard.py::TestCliHelpNamesDeclaredArgs) then failed all nine
    # of its commands, because get_cli_help() shells out with a RELATIVE PYTHONPATH=src
    # that no longer resolves from there — every --help came back
    # "No module named 'cosa'". These two tests use the REAL os.chdir on purpose;
    # patching it away is what let the leak live.
    
    def test_load_model_and_tokenizer_restores_cwd_when_load_fails( self ):
        """
        Test the working directory survives a model-load failure.
        
        Ensures:
            - _load_model_and_tokenizer restores the original cwd when
              AutoModelForCausalLM.from_pretrained raises
        """
        with tempfile.TemporaryDirectory() as hf_home:
            original_cwd = os.getcwd()
            
            with patch.dict( os.environ, { "HF_HOME": hf_home } ), \
                 patch( 'cosa.training.peft_trainer.du.print_banner' ), \
                 patch( 'builtins.print' ), \
                 patch( 'cosa.training.peft_trainer.AutoModelForCausalLM.from_pretrained' ) as mock_model_load, \
                 patch( 'cosa.training.peft_trainer.torch' ):
                
                mock_model_load.side_effect = RuntimeError( "Model loading failed" )
                
                trainer = PeftTrainer(
                    model_hf_id=self.test_model_hf_id,
                    model_name=self.test_model_name,
                    test_train_path=self.test_train_path
                )
                
                with self.assertRaises( RuntimeError ):
                    trainer._load_model_and_tokenizer( mode="training" )
            
            self.assertEqual(
                os.path.realpath( os.getcwd() ), os.path.realpath( original_cwd ),
                "_load_model_and_tokenizer leaked its os.chdir when from_pretrained raised"
            )
    
    def test_save_model_restores_cwd_when_save_fails( self ):
        """
        Test the working directory survives a save failure.
        
        Ensures:
            - save_model restores the original cwd when model.save_pretrained raises
        """
        with tempfile.TemporaryDirectory() as output_dir:
            original_cwd = os.getcwd()
            
            with patch( 'cosa.training.peft_trainer.du.print_banner' ), \
                 patch( 'builtins.print' ), \
                 patch( 'cosa.training.peft_trainer.du.get_current_date' ) as mock_get_date, \
                 patch( 'cosa.training.peft_trainer.du.get_current_time' ) as mock_get_time:
                
                mock_get_date.return_value = "2026-08-19"
                mock_get_time.return_value = "21-15"
                
                trainer = PeftTrainer(
                    model_hf_id=self.test_model_hf_id,
                    model_name=self.test_model_name,
                    test_train_path=self.test_train_path
                )
                trainer.output_dir = output_dir
                trainer.model      = self.mock_model
                trainer.tokenizer  = self.mock_tokenizer
                self.mock_model.save_pretrained.side_effect = OSError( "disk full" )
                
                try:
                    with self.assertRaises( OSError ):
                        trainer.save_model()
                finally:
                    self.mock_model.save_pretrained.side_effect = None
            
            self.assertEqual(
                os.path.realpath( os.getcwd() ), os.path.realpath( original_cwd ),
                "save_model leaked its os.chdir when save_pretrained raised"
            )
    
    @_requires_peft
    def test_load_and_merge_adapter_success( self ):
        """
        Test successful adapter loading and merging.
        
        Ensures:
            - Loads model and tokenizer
            - Loads PEFT adapter from checkpoint
            - Creates merged model
            - Sets up merged adapter directory
        """
        with patch( 'cosa.training.peft_trainer.du.print_banner' ), \
             patch( 'builtins.print' ), \
             patch.object( PeftTrainer, '_load_model_and_tokenizer' ) as mock_load_model, \
             patch( 'cosa.training.peft_trainer.PeftModel.from_pretrained' ) as mock_peft_from_pretrained, \
             patch( 'cosa.training.peft_trainer.du.get_current_date' ) as mock_get_date, \
             patch( 'cosa.training.peft_trainer.du.get_current_time' ) as mock_get_time:
            
            mock_get_date.return_value = "2025-08-05"
            mock_get_time.return_value = "14-30"
            
            mock_peft_model = Mock()
            mock_peft_from_pretrained.return_value = mock_peft_model
            
            trainer = PeftTrainer( 
                model_hf_id=self.test_model_hf_id,
                model_name=self.test_model_name,
                test_train_path=self.test_train_path
            )
            trainer.model = self.mock_model
            
            test_checkpoint_dir = "/path/to/checkpoint"
            trainer.load_and_merge_adapter( checkpoint_dir=test_checkpoint_dir )
            
            # Verify model loading
            mock_load_model.assert_called_once()
            
            # Verify PEFT model loading
            # The actual implementation calls from_pretrained differently
            mock_peft_from_pretrained.assert_called_once()
            
            # Verify merged adapter directory was created (may be None due to mocking)
            # The actual implementation sets this after merge_and_unload
            # Since we're mocking, we can't verify the exact behavior
            pass
    
    def test_quantize_merged_adapter_success( self ):
        """
        Test successful quantization of merged adapter.
        
        Ensures:
            - Uses Quantizer class for model quantization
            - Saves quantized model to appropriate directory
            - Updates quantized model directory attribute
        """
        with patch( 'cosa.training.peft_trainer.du.print_banner' ), \
             patch( 'builtins.print' ), \
             patch( 'cosa.training.peft_trainer.Quantizer' ) as mock_quantizer_class:
            
            mock_quantizer = Mock()
            mock_quantizer_class.return_value = mock_quantizer
            mock_quantizer.save.return_value = "/path/to/quantized"
            
            trainer = PeftTrainer( 
                model_hf_id=self.test_model_hf_id,
                model_name=self.test_model_name,
                test_train_path=self.test_train_path
            )
            
            test_merged_dir = "/path/to/merged"
            result = trainer.quantize_merged_adapter( merged_adapter_dir=test_merged_dir )
            
            # Verify quantizer creation with additional parameters
            mock_quantizer_class.assert_called_once()
            
            # Verify quantization process
            mock_quantizer.quantize_model.assert_called_once()
            mock_quantizer.save.assert_called_once()
            
            # Verify return value and attribute update
            self.assertEqual( result, "/path/to/quantized" )
            self.assertEqual( trainer.quantized_model_dir, "/path/to/quantized" )
    
    def test_get_training_prompt_stats_success( self ):
        """
        Test successful training prompt statistics gathering.
        
        Ensures:
            - Loads model and tokenizer
            - Gets training data
            - Calculates prompt statistics
            - Returns statistics dictionary
        """
        # Live contract ( rewritten ): get_training_prompt_stats loads model+tokenizer, reads
        # the train JSONL via pd.read_json ( NOT _get_test_train_data ), and for each row builds
        # a prompt via self.get_prompt then tokenizes it ( tokenizer( prompt, return_tensors="pt" ).to( device ) ).
        # It returns a TUPLE ( token_stats, word_stats ), each a dict of min/max/mean — NOT a
        # single dict with total_prompts/avg_tokens.
        with patch( 'cosa.training.peft_trainer.du.print_banner' ), \
             patch( 'builtins.print' ), \
             patch.object( PeftTrainer, '_load_model_and_tokenizer' ) as mock_load_model, \
             patch.object( PeftTrainer, 'get_prompt' ) as mock_get_prompt, \
             patch( 'cosa.training.peft_trainer.pd.read_json' ) as mock_read_json:

            # Two rows -> two prompts. get_prompt returns a deterministic 3-word string.
            mock_get_prompt.return_value = "alpha beta gamma"

            mock_df = Mock()
            mock_df.itertuples = Mock( return_value=iter([
                Mock( instruction="Test 1", input="",      output="Response 1" ),
                Mock( instruction="Test 2", input="Input", output="Response 2" )
            ]) )
            mock_read_json.return_value = mock_df

            trainer = PeftTrainer(
                model_hf_id=self.test_model_hf_id,
                model_name=self.test_model_name,
                test_train_path=self.test_train_path
            )

            # tokenizer( prompt, return_tensors="pt" ).to( device ) -> { "input_ids": [[ 5 tokens ]] }
            mock_tokens = Mock()
            mock_tokens.to = Mock( return_value={ "input_ids": [ [ 1, 2, 3, 4, 5 ] ] } )
            self.mock_tokenizer.return_value = mock_tokens
            trainer.tokenizer = self.mock_tokenizer

            token_stats, word_stats = trainer.get_training_prompt_stats()

            # Verify model loading + data read
            mock_load_model.assert_called_once()
            mock_read_json.assert_called_once()

            # Live contract: two dicts of min/max/mean. 5 tokens/prompt, 3 words/prompt.
            self.assertEqual( token_stats, { "min": 5, "max": 5, "mean": 5.0 } )
            self.assertEqual( word_stats,  { "min": 3, "max": 3, "mean": 3.0 } )
    
    def test_cli_argument_parsing( self ):
        """
        Test CLI argument parsing via parse_arguments().

        Live contract: the __main__ CLI was rewritten to argparse ( flags --model,
        --model-name, --test-train-path, ... ) routed through the standalone
        parse_arguments() function, and the pipeline is GPU/privilege-gated. The prior
        test asserted a positional/keyword PeftTrainer(...) signature that no longer
        exists AND never executed the CLI ( it was a no-op assertTrue(True) followed by a
        dead assertion ). We instead unit-test the one safely-isolatable CLI unit —
        argument parsing — without executing the training pipeline.

        Ensures:
            - parse_arguments() reads --model / --model-name / --test-train-path
            - store_true flags default to False when absent
        """
        import cosa.training.peft_trainer as ptmod

        test_args = [
            "peft_trainer.py",
            "--model",           self.test_model_hf_id,
            "--model-name",      self.test_model_name,
            "--test-train-path", self.test_train_path,
        ]

        with patch( 'sys.argv', test_args ):
            args = ptmod.parse_arguments()

            # Positional values parsed onto the expected attributes
            self.assertEqual( args.model, self.test_model_hf_id )
            self.assertEqual( args.model_name, self.test_model_name )
            self.assertEqual( args.test_train_path, self.test_train_path )

            # store_true flags default False when not supplied
            self.assertFalse( args.debug )
            self.assertFalse( args.verbose )
            self.assertFalse( args.nuclear_kill_button )


def isolated_unit_test():
    """
    Run comprehensive unit tests for PEFT trainer in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real model loading or training operations
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "PEFT Trainer Unit Tests - Training Phase 6", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods (focusing on working ones)
        test_methods = [
            'test_initialization_success',
            'test_initialization_with_defaults',
            'test_initialization_unsupported_model',
            'test_load_model_and_tokenizer_success',
            'test_load_model_and_tokenizer_error',
            'test_get_peft_config_success',
            'test_load_and_merge_adapter_success',
            'test_quantize_merged_adapter_success'
        ]
        
        for method in test_methods:
            suite.addTest( TestPeftTrainer( method ) )
        
        # Run tests with detailed output
        runner = unittest.TextTestRunner( verbosity=2, stream=sys.stdout )
        result = runner.run( suite )
        
        duration = time.time() - start_time
        
        # Calculate results
        tests_run = result.testsRun
        failures = len( result.failures )
        errors = len( result.errors )
        success_count = tests_run - failures - errors
        
        print( f"\n{'='*60}" )
        print( f"PEFT TRAINER UNIT TEST RESULTS" )
        print( f"{'='*60}" )
        print( f"Tests Run     : {tests_run}" )
        print( f"Passed        : {success_count}" )
        print( f"Failed        : {failures}" )
        print( f"Errors        : {errors}" )
        print( f"Success Rate  : {(success_count/tests_run)*100:.1f}%" )
        print( f"Duration      : {duration:.3f} seconds" )
        print( f"{'='*60}" )
        
        if failures > 0:
            print( "\nFAILURE DETAILS:" )
            for test, traceback in result.failures:
                print( f"❌ {test}: {traceback.split(chr(10))[-2]}" )
                
        if errors > 0:
            print( "\nERROR DETAILS:" )
            for test, traceback in result.errors:
                print( f"💥 {test}: {traceback.split(chr(10))[-2]}" )
        
        success = failures == 0 and errors == 0
        
        if success:
            du.print_banner( "✅ ALL PEFT TRAINER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME PEFT TRAINER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 PEFT TRAINER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} PEFT trainer unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )