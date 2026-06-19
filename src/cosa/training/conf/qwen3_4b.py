"""
Configuration for fine-tuning Qwen3-4B-Base model.

This configuration module defines the parameters needed by the PEFT Trainer to fine-tune
the Qwen3-4B-Base model. As a base (non-instruct) model, it uses Alpaca-style prompt
formatting to learn instruction-following behavior during fine-tuning.

1. fine_tune_config: Training parameters tailored for Qwen3-4B:
   - sample_size: Full data (100%) by default (use --sample-size CLI arg to override)
   - batch_size: Larger batch size (4) since the 4B model fits more comfortably in GPU memory
   - gradient_accumulation_steps: Lower value (4) compared to Ministral's 8, since larger batches
     already provide sufficient gradient estimation
   - logging/eval_steps: Regular evaluation at 10% epoch intervals
   - device_map: Automatic GPU memory management

2. lora_config: LoRA parameters customized for Qwen3's architecture:
   - lora_alpha: Standard scaling factor (32) for 4B-class models
   - lora_dropout: 5% dropout for regularization
   - r: Lower rank (16) sufficient for the smaller model
   - target_modules: Attention and MLP layers (Qwen3 uses same names as Mistral family)

3. tokenizer_config: Qwen3-specific tokenization settings:
   - pad_token: Uses end-of-sequence token for padding
   - padding_side: Right padding during training, left padding for inference

4. model_config: Parameters specific to Qwen3-4B usage:
   - max_seq_length: Moderate sequence length (683 tokens) matching training data constraints
   - prompt_template: Alpaca format (base model learns instruction-following during fine-tuning)
   - last_tag_func: Uses Qwen3 EOS token <|endoftext|> when output is present
"""

from typing import Union, Callable

fine_tune_config: dict[ str, Union[ float, int, str ] ] = {
    "sample_size"                : 1.0,
    "batch_size"                 : 4,
    "gradient_accumulation_steps": 4,
    "logging_steps"              : 0.10,
    "eval_steps"                 : 0.10,
    "device_map"                 : "auto"
}

lora_config: dict[ str, Union[ int, float, str, list[ str ] ] ] = {
    "lora_alpha"     : 32,
    "lora_dropout"   : 0.05,
    "r"              : 16,
    "bias"           : "none",
    "task_type"      : "CAUSAL_LM",
    "target_modules" : [ "k_proj", "q_proj", "v_proj", "o_proj", "gate_proj", "down_proj", "up_proj" ]
}

tokenizer_config: dict[ str, Union[ str, dict[ str, str ] ] ] = {
    "pad_token"    : "eos_token",
    "padding_side" : {
        "training"  : "right",
        "inference" : "left"
    }
}

model_config: dict[ str, Union[ int, str, Callable[ [ str ], str ] ] ] = {
    "max_seq_length"  : 683,
    "prompt_template" : """### Instruction:
{instruction}

### Input:
{input}

### Response:
{output}{last_tag}""",
    "last_tag_func" : lambda output: "<|endoftext|>" if output else ""
}

vllm_config: dict[ str, Union[ int, float ] ] = {
    "max_model_len"          : 1024,  # Training uses max_seq_length=683; 1024 is generous for validation prompts + 128 max_new_tokens
    "gpu_memory_utilization" : 0.70,  # was 0.90 — V1 engine (vLLM 0.8.5+) needs headroom for warmup allocations
    "tensor_parallel_size"   : 1,     # 4B model (~8 GB bf16) fits on 1 GPU — no sharding needed
    "max_num_seqs"           : 64,    # V1 engine warms up with this many dummy requests (default 256 causes OOM)
}
