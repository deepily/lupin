"""
Smoke test for LoRA env update and ConfigurationManager env var resolution chain.

Tests the full pipeline:
  1. PeftTrainer._update_lora_env() writes a temp env file
  2. Env var is set in the current process
  3. os.path.expandvars() resolves ${VAR} in a vllm:// connection string
  4. ConfigurationManager resolves the env var in config values

Run: pytest src/tests/smoke/test_lora_env_update_smoke.py -v -s
"""

import os
import pytest
import tempfile

# Skip if config env not set
pytestmark = [
    pytest.mark.skipif(
        not os.environ.get( "LUPIN_CONFIG_MGR_CLI_ARGS" ),
        reason="LUPIN_CONFIG_MGR_CLI_ARGS not set"
    ),
]

# Real path from latest training run (2026-02-18)
MINISTRAL_8B_PATH = "/mnt/DATA01/include/www.deepily.ai/projects/models/Ministral-8B-Instruct-2410.lora/merged-on-2026-02-18-at-01-25/autoround-8-bits-sym.gptq/2026-02-18-at-01-50"
QWEN3_4B_PATH     = "/mnt/DATA01/include/www.deepily.ai/projects/models/Qwen3-4B-Base.lora/merged-on-2026-02-11-at-00-14/autoround-4-bits-sym.gptq/2026-02-11-at-00-26"

ENV_VAR_NAME     = "LUPIN_ROUTER_LORA_MINISTRAL_8B_PATH"
ENV_VAR_NAME_Q   = "LUPIN_ROUTER_LORA_QWEN3_4B_PATH"


class TestLoraEnvUpdate:
    """Smoke tests for the LoRA env update → config resolution chain."""

    def test_update_lora_env_writes_file( self ):
        """
        PeftTrainer._update_lora_env() writes correct export lines to a temp file.

        Requires:
            - PeftTrainer class is importable
            - No GPU or model loading needed

        Ensures:
            - Temp file contains export line for the correct env var
            - Path value matches the quantized_model_dirs entry
        """
        from cosa.training.peft_trainer import PeftTrainer

        with tempfile.NamedTemporaryFile( mode="w", suffix=".env", delete=False ) as tmp:
            tmp_path = tmp.name

        try:
            # Create a minimal trainer via __new__ (skip __init__ which needs GPU)
            trainer                      = object.__new__( PeftTrainer )
            trainer.model_name           = "Ministral-8B-Instruct-2410"
            trainer.quantized_model_dirs = { 8: MINISTRAL_8B_PATH }
            trainer.debug                = False

            trainer._update_lora_env( env_file_path=tmp_path )

            # Read back and verify
            with open( tmp_path, "r" ) as f:
                content = f.read()

            assert f'export {ENV_VAR_NAME}="{MINISTRAL_8B_PATH}"' in content, \
                f"Expected export line not found in env file. Content:\n{content}"
            print( f"  env file written OK: {tmp_path}" )
            print( f"  Contains: export {ENV_VAR_NAME}=\"...\"" )
        finally:
            os.unlink( tmp_path )

    def test_update_preserves_other_models( self ):
        """
        Updating one model's path preserves other models' entries.

        Requires:
            - PeftTrainer class is importable

        Ensures:
            - Both Ministral and Qwen entries present after sequential updates
        """
        from cosa.training.peft_trainer import PeftTrainer

        with tempfile.NamedTemporaryFile( mode="w", suffix=".env", delete=False ) as tmp:
            tmp_path = tmp.name

        try:
            # First update: Ministral
            trainer1                      = object.__new__( PeftTrainer )
            trainer1.model_name           = "Ministral-8B-Instruct-2410"
            trainer1.quantized_model_dirs = { 8: MINISTRAL_8B_PATH }
            trainer1.debug                = False
            trainer1._update_lora_env( env_file_path=tmp_path )

            # Second update: Qwen
            trainer2                      = object.__new__( PeftTrainer )
            trainer2.model_name           = "Qwen3-4B-Base"
            trainer2.quantized_model_dirs = { 4: QWEN3_4B_PATH }
            trainer2.debug                = False
            trainer2._update_lora_env( env_file_path=tmp_path )

            # Read back and verify both entries present
            with open( tmp_path, "r" ) as f:
                content = f.read()

            assert f'export {ENV_VAR_NAME}="{MINISTRAL_8B_PATH}"' in content, \
                "Ministral entry was lost after Qwen update"
            assert f'export {ENV_VAR_NAME_Q}="{QWEN3_4B_PATH}"' in content, \
                "Qwen entry not found after Qwen update"
            print( "  Both model entries preserved after sequential updates" )
        finally:
            os.unlink( tmp_path )

    def test_expandvars_resolves_connection_string( self ):
        """
        os.path.expandvars() resolves ${LUPIN_ROUTER_LORA_MINISTRAL_8B_PATH} in a vllm:// string.

        Requires:
            - Nothing (pure stdlib test)

        Ensures:
            - Connection string contains the full resolved path
            - No ${...} patterns remain
        """
        original_value = os.environ.get( ENV_VAR_NAME )
        try:
            os.environ[ ENV_VAR_NAME ] = MINISTRAL_8B_PATH

            connection_string = "vllm://192.168.1.21:3000@${LUPIN_ROUTER_LORA_MINISTRAL_8B_PATH}"
            resolved = os.path.expandvars( connection_string )

            assert "${" not in resolved, f"Unresolved env var in: {resolved}"
            assert MINISTRAL_8B_PATH in resolved, f"Path not found in resolved string: {resolved}"
            print( f"  Resolved: {resolved}" )
        finally:
            if original_value is not None:
                os.environ[ ENV_VAR_NAME ] = original_value
            elif ENV_VAR_NAME in os.environ:
                del os.environ[ ENV_VAR_NAME ]

    def test_configuration_manager_resolves_env_var( self ):
        """
        ConfigurationManager.get() resolves ${ENV_VAR} in config values end-to-end.

        Requires:
            - LUPIN_CONFIG_MGR_CLI_ARGS environment variable set
            - lupin-app.ini uses ${LUPIN_ROUTER_LORA_MINISTRAL_8B_PATH} in the connection string

        Ensures:
            - get( "deepily/ministral_8b_2410_ft_lora" ) returns a string with no ${...} patterns
            - The resolved string contains the expected model path
        """
        original_value = os.environ.get( ENV_VAR_NAME )
        try:
            os.environ[ ENV_VAR_NAME ] = MINISTRAL_8B_PATH

            from cosa.config.configuration_manager import ConfigurationManager
            cm = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", silent=True, mute_splainer=True )

            value = cm.get( "deepily/ministral_8b_2410_ft_lora" )

            assert "${" not in value, f"Unresolved env var in config value: {value}"
            assert MINISTRAL_8B_PATH in value, f"Expected path not found in config value: {value}"
            assert value.startswith( "vllm://" ), f"Expected vllm:// prefix, got: {value}"
            print( f"  ConfigurationManager resolved: {value}" )
        finally:
            if original_value is not None:
                os.environ[ ENV_VAR_NAME ] = original_value
            elif ENV_VAR_NAME in os.environ:
                del os.environ[ ENV_VAR_NAME ]

    def test_unset_env_var_fails_loudly( self ):
        """
        When env var is NOT set, the ${...} pattern is left as-is (fail-fast).

        Requires:
            - LUPIN_ROUTER_LORA_MINISTRAL_8B_PATH is NOT in os.environ

        Ensures:
            - os.path.expandvars() leaves ${VAR} literal in the string
            - This causes vLLM connection to fail at runtime (correct behavior)
        """
        # Temporarily remove the env var if set
        original_value = os.environ.pop( ENV_VAR_NAME, None )
        try:
            connection_string = "vllm://192.168.1.21:3000@${LUPIN_ROUTER_LORA_MINISTRAL_8B_PATH}"
            resolved = os.path.expandvars( connection_string )

            assert "${" in resolved, f"Expected literal ${{...}} for unset var, got: {resolved}"
            print( f"  Unset var correctly left as literal: {resolved}" )
        finally:
            if original_value is not None:
                os.environ[ ENV_VAR_NAME ] = original_value

    def test_prefers_8bit_over_4bit( self ):
        """
        _update_lora_env() prefers 8-bit path when both 4 and 8 bit paths are available.

        Requires:
            - PeftTrainer class is importable

        Ensures:
            - When both 4-bit and 8-bit paths exist, 8-bit is written to env file
        """
        from cosa.training.peft_trainer import PeftTrainer

        path_4bit = "/fake/path/to/4-bit-model"
        path_8bit = "/fake/path/to/8-bit-model"

        with tempfile.NamedTemporaryFile( mode="w", suffix=".env", delete=False ) as tmp:
            tmp_path = tmp.name

        try:
            trainer                      = object.__new__( PeftTrainer )
            trainer.model_name           = "Ministral-8B-Instruct-2410"
            trainer.quantized_model_dirs = { 4: path_4bit, 8: path_8bit }
            trainer.debug                = False

            trainer._update_lora_env( env_file_path=tmp_path )

            with open( tmp_path, "r" ) as f:
                content = f.read()

            assert path_8bit in content, f"Expected 8-bit path in env file, got:\n{content}"
            assert path_4bit not in content, f"4-bit path should not be in env file when 8-bit available"
            print( f"  Correctly preferred 8-bit path over 4-bit" )
        finally:
            os.unlink( tmp_path )


if __name__ == "__main__":
    pytest.main( [ __file__, "-v", "-s" ] )
