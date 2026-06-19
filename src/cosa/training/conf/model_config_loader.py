"""
Model configuration loader for fine-tuning different language models.

This module provides a standardized configuration system for the PEFT (Parameter-Efficient Fine-Tuning) Trainer,
allowing different language models to be fine-tuned with model-specific settings. Each model has its own
configuration file in this directory that defines four essential configuration dictionaries:

1. fine_tune_config: General training parameters like batch size, gradient accumulation steps, and logging frequency
2. lora_config: LoRA-specific parameters for efficient fine-tuning (ranks, dropout, target modules)
3. tokenizer_config: Tokenizer-specific settings for the model (padding tokens, padding direction)
4. model_config: Model-specific parameters (sequence length, prompt templates)

The PEFT Trainer (peft_trainer.py) imports and uses these configurations via the load_model_config() function,
which dynamically loads the appropriate configuration based on the selected model name. This centralized
configuration approach allows for:

1. Easy addition of new models by adding a new config file and entry in MODEL_CONFIG_MAP
2. Consistent parameter organization across different model architectures
3. Separation of model-specific details from the trainer logic
4. Simplified experiment tracking with standardized configuration format

The relationship between conf files and the PEFT Trainer is defined by the load_model_config() function,
which the trainer calls to obtain all necessary parameters for initializing and fine-tuning a specific model.
"""

from importlib import import_module
import os

# Map model names to their configuration module paths
MODEL_CONFIG_MAP = {
    "Mistral-7B-Instruct-v0.2"  : "mistral_7b",
    "Ministral-8B-Instruct-2410": "ministral_8b",
    "Llama-3.2-3B-Instruct"     : "llama_3_2_3b",
    "Phi-4-mini-instruct"       : "phi_4_mini",
    "Qwen3-4B-Base"             : "qwen3_4b"
}

def load_model_config(model_name):
    """
    Dynamically load the configuration for a specific model.

    Args:
        model_name (str): Name of the model to load configuration for

    Returns:
        dict: Combined configuration dictionary with all settings

    Raises:
        ValueError: If the model name is not found in the configuration map
    """
    if model_name not in MODEL_CONFIG_MAP:
        raise ValueError(f"Unknown model: {model_name}. Available models: {', '.join(MODEL_CONFIG_MAP.keys())}")

    # Import the module from the model configuration map
    config_module = import_module(f".{MODEL_CONFIG_MAP[model_name]}", package="cosa.training.conf")

    # Combine all configurations into a single dictionary
    config = {
        "fine_tune"  : config_module.fine_tune_config,
        "lora"       : config_module.lora_config,
        "tokenizer"  : config_module.tokenizer_config,
        "model"      : config_module.model_config,
        "vllm"       : getattr( config_module, "vllm_config", {} )
    }

    return config