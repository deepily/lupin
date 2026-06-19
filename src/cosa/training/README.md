# COSA's Easy PEFT Trainer

## What's Easy PEFT?

*A very long lever*

<a href="../docs/images/bender-is-broken.png" target="_blank">
  <img src="../docs/images/bender-is-broken.png" alt="PEFT diagram" width="1024px">
</a>

This directory contains tools for Parameter-Efficient Fine-Tuning (PEFT) of large language models using LoRA (Low-Rank Adaptation).

## Overview

The PEFT Trainer provides a streamlined pipeline for:
1. Fine-tuning models with LoRA adapters
2. Merging adapters with the base model
3. Quantizing models for efficient deployment
4. Validating model performance at various stages

## Requirements

- Python 3.8+
- PyTorch 2.0+
- Hugging Face Transformers
- PEFT library
- vLLM (for serving quantized models)
- DEEPILY_PROJECTS_DIR environment variable set
- Root privileges (only if using the `--nuclear-kill-button` flag)

## Usage

### Basic Command

```bash
# Run with basic options (no nuclear kill button)
python peft_trainer.py \
  --model <huggingface_model_id> \
  --model-name <model_config_name> \
  --test-train-path <path_to_training_data> \
  --lora-dir <output_directory_for_lora_adapters>

# Run with nuclear kill button option (requires sudo)
sudo python peft_trainer.py \
  --model <huggingface_model_id> \
  --model-name <model_config_name> \
  --test-train-path <path_to_training_data> \
  --lora-dir <output_directory_for_lora_adapters> \
  --nuclear-kill-button
```

> **Nuclear Kill Button**: The `--nuclear-kill-button` flag enables forceful GPU memory cleanup when needed. When this flag is used, the script must be run with `sudo` privileges. If the flag is set but the script is not run with sudo, it will exit with instructions to rerun with proper permissions. Without this flag, no privilege checks are performed.

### Arguments

- `--model`: Hugging Face model ID (e.g., "mistralai/Mistral-7B-Instruct-v0.2")
- `--model-name`: Model name as defined in conf/ directory (e.g., "Mistral-7B-Instruct-v0.2")
- `--test-train-path`: Path to directory containing training, testing, and validation data
- `--lora-dir`: Directory for saving LoRA adapter files

### Optional Flags

- `--debug`: Enable debug mode with additional logging
- `--verbose`: Enable verbose mode with detailed outputs
- `--pre-training-stats`: Run validation before training
- `--post-training-stats`: Run validation after training and merging
- `--post-quantization-stats`: Run validation after quantization
- `--nuclear-kill-button`: Enable forceful GPU memory reset when needed (requires sudo)
- `--validation-sample-size`: Number of samples to use for validation (default: 100)

## Data Format

The trainer expects data in the following format and locations:
- Training data: `<test_train_path>/voice-commands-xml-train.jsonl`
- Testing data: `<test_train_path>/voice-commands-xml-test.jsonl`
- Validation data: `<test_train_path>/voice-commands-xml-validate.jsonl`

Each file should contain JSONL entries with:
```json
{
  "instruction": "Task instruction",
  "input": "User input",
  "output": "Expected output",
  "command": "Command category"
}
```

## Model Configuration

Model-specific configurations are defined in the `conf/` directory. To add support for a new model:

1. Create a new Python file in `conf/` (e.g., `new_model.py`)
2. Define configurations for:
   - Fine-tuning parameters
   - LoRA parameters
   - Tokenizer settings
   - Model-specific settings (sequence length, prompt template)
3. Add the model to the `MODEL_CONFIG_MAP` in `conf/__init__.py`

## Pipeline Stages

The full training pipeline consists of:

1. **Pre-training validation** (optional)
   - Tests model performance before training
   
2. **Fine-tuning with LoRA**
   - Applies parameter-efficient fine-tuning
   - Creates adapter checkpoints

3. **Merging LoRA adapter**
   - Combines adapter weights with base model
   - Produces a standalone model with fine-tuning applied

4. **Post-training validation** (optional)
   - Tests model performance after fine-tuning
   - Uses vLLM server for inference

5. **Quantization**
   - Reduces model size and inference requirements
   - Uses AutoRound for high-quality quantization

6. **Post-quantization validation** (optional)
   - Tests model performance after quantization
   - Uses vLLM server for inference

## Examples

### Basic Usage

```bash
# Basic example (no nuclear kill option)
python peft_trainer.py \
  --model "mistralai/Ministral-8B-Instruct-2410" \
  --model-name "Ministral-8B-Instruct-2410" \
  --test-train-path "/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/ephemera/prompts/data" \
  --lora-dir "/mnt/DATA01/include/www.deepily.ai/projects/models/Ministral-8B-Instruct-2410.lora" \
  --post-training-stats \
  --post-quantization-stats \
  --validation-sample-size 100
```

### Advanced Usage with GPU Memory Management

When using the `--nuclear-kill-button` flag for advanced GPU memory management, the trainer must be run with sudo. **It is critical to preserve environment variables and your PATH** when using sudo, otherwise the training will fail:

```bash
# Real-world example using the nuclear-kill-button for GPU memory management
sudo --preserve-env=HF_HOME,NCCL_P2P_DISABLE,NCCL_IB_DISABLE,LUPIN_ROOT,LUPIN_CONFIG_MGR_CLI_ARGS,DEEPILY_PROJECTS_DIR \
  env "PATH=$PATH" \
  python -m cosa.training.peft_trainer \
    --model mistralai/Ministral-8B-Instruct-2410 \
    --model-name Ministral-8B-Instruct-2410 \
    --test-train-path $LUPIN_ROOT/src/ephemera/prompts/data \
    --lora-dir $HF_HOME/Ministral-8B-Instruct-2410.lora \
    --pre-training-stats \
    --post-training-stats \
    --post-quantization-stats \
    --validation-sample-size 1000 \
    --nuclear-kill-button
```

> **Note:** The `--preserve-env` and `env "PATH=$PATH"` arguments are essential when using sudo, as they ensure that all necessary environment variables and paths are available to the trainer process running with elevated privileges.

### Alternative with Simpler Nuclear Option

```bash
# Example with nuclear kill button (requires sudo)
sudo python peft_trainer.py \
  --model "mistralai/Ministral-8B-Instruct-2410" \
  --model-name "Ministral-8B-Instruct-2410" \
  --test-train-path "/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/ephemera/prompts/data" \
  --lora-dir "/mnt/DATA01/include/www.deepily.ai/projects/models/Ministral-8B-Instruct-2410.lora" \
  --post-training-stats \
  --post-quantization-stats \
  --nuclear-kill-button \
  --validation-sample-size 100
```

## Debugging

For development and debugging, you can use the `run_pipeline_adhoc` method by uncommenting it in the main script. This version allows selective enabling/disabling of specific pipeline steps.

## Environment Variables

Required environment variables:
- `NCCL_P2P_DISABLE=1`
- `NCCL_IB_DISABLE=1`
- `LUPIN_ROOT=/path/to/lupin`
- `LUPIN_CONFIG_MGR_CLI_ARGS`
- `DEEPILY_PROJECTS_DIR=/path/to/projects`

## Output Directory Structure

```
<lora_dir>/
├── training-YYYY-MM-DD-at-HH-MM/
│   └── checkpoint-N/
├── merged-on-YYYY-MM-DD-at-HH-MM/
└── merged-on-YYYY-MM-DD-at-HH-MM/autoround-4-bits-sym.gptq/YYYY-MM-DD-at-HH-MM/
```