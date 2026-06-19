"""
Configuration for fine-tuning Phi-4-mini-instruct model.

This configuration module defines the specific parameters needed by the PEFT Trainer
to fine-tune the Microsoft Phi-4-mini-instruct model. The parameters are organized
into four distinct configuration dictionaries that control different aspects of the
fine-tuning process:

1. fine_tune_config: Controls training parameters specific to this model, including:
   - sample_size: Fraction of training data to use (0.01 = 1% for faster experimentation)
   - batch_size: Number of samples processed in each training step
   - gradient_accumulation_steps: Number of forward passes before parameter update
   - logging/eval_steps: Frequency of progress logging and evaluation (0.50 = every half epoch)
   - device_map: How to distribute model across available devices

2. lora_config: Low-Rank Adaptation parameters for efficient fine-tuning:
   - lora_alpha: Scaling factor for LoRA updates
   - lora_dropout: Dropout probability for LoRA layers
   - r: Rank of the LoRA matrices (lower = more efficient, higher = more expressive)
   - target_modules: Which model components to apply LoRA to (attention layers)

3. tokenizer_config: Model-specific tokenization settings:
   - pad_token/pad_token_id: Token used for padding sequences
   - padding_side: Different padding approaches for training vs. inference

4. model_config: Model-specific parameters:
   - max_seq_length: Maximum sequence length the model can handle
   - prompt_template: Formatting template for instructions and responses
   - last_tag_func: Function to properly close the sequence

When the PEFT Trainer imports this configuration via load_model_config(), 
it uses these parameters to properly initialize the model, tokenizer, and 
training process specifically optimized for Phi-4-mini.
"""

from typing import Union, Callable

fine_tune_config: dict[str, Union[float, int, str]] = {
    "sample_size": 0.01,
    "batch_size": 8,
    "gradient_accumulation_steps": 4,
    "logging_steps": 0.50,
    "eval_steps": 0.50,
    "device_map": "auto"
}

lora_config: dict[str, Union[int, float, str, list[str]]] = {
    "lora_alpha": 16,
    "lora_dropout": 0.05,
    "r": 64,
    "bias": "none",
    "task_type": "CAUSAL_LM",
    "target_modules": ["k_proj", "q_proj", "v_proj", "o_proj", "gate_proj", "down_proj", "up_proj"]
}

tokenizer_config: dict[str, Union[str, dict[str, str]]] = {
    "pad_token": "unk_token",
    "pad_token_id": "converted_from_unk_token",  # Will be resolved by the trainer
    "padding_side": {
        "training": "right",
        "inference": "left"
    }
}

model_config: dict[str, Union[int, str, Callable[[str], str]]] = {
    "max_seq_length": 683,
    "prompt_template": """<s>[INST]{instruction}

            {input}
            [/INST]
            {output}
            {last_tag}""",
    "last_tag_func": lambda output: "</s>" if output else ""
}
