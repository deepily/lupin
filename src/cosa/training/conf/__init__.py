"""
Model configuration package for fine-tuning different language models.

This package provides a standardized configuration system for the PEFT (Parameter-Efficient Fine-Tuning) Trainer,
allowing different language models to be fine-tuned with model-specific settings. Each model has its own
configuration file in this directory that defines four essential configuration dictionaries.

NOTE: All functionality moved to model_config_loader.py to keep __init__.py clean and prevent
any potential import issues. Use direct imports:

    from cosa.training.conf.model_config_loader import load_model_config, MODEL_CONFIG_MAP

Previous imports that should now be updated:
    - from cosa.training.conf import load_model_config  → from cosa.training.conf.model_config_loader import load_model_config
    - from cosa.training.conf import MODEL_CONFIG_MAP   → from cosa.training.conf.model_config_loader import MODEL_CONFIG_MAP
"""
