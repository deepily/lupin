"""
Configuration for fine-tuning Mistral-7B-Instruct-v0.2 model.

This configuration module provides the specific parameters required by the PEFT Trainer
to fine-tune the Mistral-7B-Instruct-v0.2 model. The configuration is structured into
four key dictionaries that define different aspects of the fine-tuning process tailored
for this larger 7B parameter model:

1. fine_tune_config: Training hyperparameters optimized for Mistral-7B:
   - sample_size: Uses 100% of the training data (1.0)
   - batch_size: Smaller batch size (4) due to the model's larger memory requirements
   - gradient_accumulation_steps: Higher (6) to compensate for smaller batch size
   - logging/eval_steps: Frequent evaluation (every 10% of an epoch)
   - device_map: Automatic GPU memory management

2. lora_config: Low-Rank Adaptation settings specific to Mistral's architecture:
   - lora_alpha: Scaling factor for LoRA updates (16)
   - lora_dropout: Regularization with 5% dropout probability
   - r: Low rank of 4 for memory efficiency with this large model
   - target_modules: Attention and MLP layers to be adapted with LoRA

3. tokenizer_config: Mistral-specific tokenization configuration:
   - pad_token: Uses the end-of-sequence token for padding
   - padding_side: Right padding for training, left padding for inference

4. model_config: Mistral-specific model parameters:
   - max_seq_length: Longer sequence length (779) than other models
   - prompt_template: Structured instruction template with Task/Input/Response format

The PEFT Trainer loads this configuration through the load_model_config() function
to correctly initialize the Mistral model with its specific architectural requirements
and training parameters. These settings are optimized for the Mistral model's unique
characteristics and memory footprint.
"""

from typing import Union

fine_tune_config: dict[str, Union[float, int, str]] = {
    "sample_size": 1.0,
    "batch_size": 4,
    "gradient_accumulation_steps": 6,
    "logging_steps": 0.10,
    "eval_steps": 0.10,
    "device_map": "auto"
}

lora_config: dict[str, Union[int, float, str, list[str]]] = {
    "lora_alpha": 16,
    "lora_dropout": 0.05,
    "r": 4,
    "bias": "none",
    "task_type": "CAUSAL_LM",
    "target_modules": ["k_proj", "q_proj", "v_proj", "o_proj", "gate_proj", "down_proj", "up_proj"]
}

tokenizer_config: dict[str, Union[str, dict[str, str]]] = {
    "pad_token": "eos_token",
    "padding_side": {
        "training": "right",
        "inference": "left"
    }
}

model_config: dict[str, Union[int, str]] = {
    "max_seq_length": 779,
    "prompt_template": """### Instruction:
            Use the Task below and the Input given to write a Response that can solve the following Task:
    
            ### Task:
            {instruction}
    
            ### Input:
            {input}
    
            ### Response:
            {output}
            """
}
