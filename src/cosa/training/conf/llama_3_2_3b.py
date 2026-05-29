"""
Configuration for fine-tuning Llama-3.2-3B-Instruct model.

This configuration module defines the parameters required by the PEFT Trainer to fine-tune
Meta's Llama-3.2-3B-Instruct model. The configuration is structured into five dictionaries
that specify different aspects of the training process optimized for this model's unique
architecture and requirements:

1. fine_tune_config: Training parameters customized for Llama-3.2-3B:
   - sample_size: Uses 100% of the training data (1.0)
   - batch_size: Moderate batch size (6) balancing throughput and memory usage
   - gradient_accumulation_steps: Medium value (4) for stable optimization
   - logging/eval_steps: Regular progress tracking at 10% epoch intervals
   - device_map: Automatic GPU memory allocation and management

2. lora_config: Low-Rank Adaptation settings specific to Llama's architecture:
   - lora_alpha: Scaling factor (16) for LoRA parameter updates
   - lora_dropout: Standard 5% dropout for regularization
   - r: Higher rank (64) allowing more expressive fine-tuning for this model
   - target_modules: Llama-specific attention and MLP components for adaptation

3. tokenizer_config: Llama-specific tokenization settings:
   - pad_token: Uses Llama 3.2's dedicated finetune right pad token (128004)
   - padding_side: Right padding for training batches, left padding for inference

4. model_config: Llama-specific parameters:
   - max_seq_length: Context window size (683 tokens)
   - prompt_template: Llama 3.2 native chat format with special header tokens
   - last_tag_func: Ensures proper sequence termination with <|eot_id|> token

5. vllm_config: vLLM serving parameters for validation stages:
   - max_model_len: 1024 tokens (generous for validation prompts + max_new_tokens)
   - gpu_memory_utilization: Conservative 0.70 for V1 engine warmup headroom
   - tensor_parallel_size: 1 (3B model fits on single GPU)
   - max_num_seqs: 64 (prevents OOM during V1 engine warmup)
   - quantization: "gptq_marlin" forces Marlin kernel for 2.6x faster GPTQ inference

The PEFT Trainer uses this configuration through the load_model_config() function to
properly initialize and fine-tune the Llama model with settings optimized for its
architecture. This configuration accounts for Llama 3.2's specific tokenization approach,
memory requirements, and architectural characteristics that differ from other models in
the collection.
"""

from typing import Union, Callable

fine_tune_config: dict[ str, Union[ float, int, str ] ] = {
    "sample_size"                : 1.0,
    "batch_size"                 : 6,
    "gradient_accumulation_steps": 4,
    "logging_steps"              : 0.10,
    "eval_steps"                 : 0.10,
    "device_map"                 : "auto"
}

lora_config: dict[ str, Union[ int, float, str, list[ str ] ] ] = {
    "lora_alpha"     : 16,
    "lora_dropout"   : 0.05,
    "r"              : 64,
    "bias"           : "none",
    "task_type"      : "CAUSAL_LM",
    "target_modules" : [ "k_proj", "q_proj", "v_proj", "o_proj", "gate_proj", "down_proj", "up_proj" ]
}

tokenizer_config: dict[ str, Union[ str, int, dict[ str, str ] ] ] = {
    "pad_token"    : "<|finetune_right_pad_id|>",
    "pad_token_id" : 128004,
    "padding_side" : {
        "training"  : "right",
        "inference" : "left"
    }
}

model_config: dict[ str, Union[ int, str, Callable[ [ str ], str ] ] ] = {
    "max_seq_length"  : 683,
    "prompt_template" : """<|begin_of_text|><|start_header_id|>user<|end_header_id|>

{instruction}

{input}<|eot_id|><|start_header_id|>assistant<|end_header_id|>

{output}{last_tag}""",
    "last_tag_func" : lambda output: "<|eot_id|>" if output else ""
}

vllm_config: dict[ str, Union[ int, float, str ] ] = {
    "max_model_len"          : 1024,          # Training uses max_seq_length=683; 1024 is generous for validation prompts + 128 max_new_tokens
    "gpu_memory_utilization" : 0.70,          # V1 engine (vLLM 0.8.5+) needs headroom for warmup allocations
    "tensor_parallel_size"   : 1,             # 3B model (~6 GB bf16) fits on 1 GPU — no sharding needed
    "max_num_seqs"           : 64,            # V1 engine warms up with this many dummy requests (default 256 causes OOM)
    "quantization"           : "gptq_marlin", # Force Marlin kernel for GPTQ — 2.6x faster than naive GPTQ (JarvisLabs benchmarks)
}
