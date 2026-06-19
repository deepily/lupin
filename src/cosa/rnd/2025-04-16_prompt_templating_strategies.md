# Prompt Templating Strategies (2025-04-16)

## Overview
This document outlines a strategy for dynamically templating prompts based on model requirements. The goal is to support three common LLM prompt formats while allowing a single set of inputs (instructions, input, output) to be used for both inference and training.

## Prompt Format Types

### 1. Instruction-Based Completion Format
```
<s>[INST] {instructions}

{input} [/INST]
{output}
</s>
```
- Used by: Mistral, Ministral, some LLaMA models
- Single text block with instruction tags
- Treats entire interaction as a completion

### 2. Special Token Chat Format
```
<|system|>{instructions}<|end|>
<|user|>{input}<|end|>
<|assistant|>{output}<|end|>
```
- Used by: Phi-4, various open models
- Model-specific tokens for each role
- Structured but not JSON-based

### 3. JSON Message Format
```python
messages = [
    {"role": "system", "content": "{instructions}"},
    {"role": "user", "content": "{input}"},
    {"role": "assistant", "content": "{output}"}
]
```
- Used by: OpenAI, Claude, Groq API, etc.
- Standard API format for many services
- Programmatically clear separation of roles

## Reading Format Type From Configuration

The primary approach is to read the prompt format directly from configuration, with a fallback to an inference method:

```python
def get_prompt_format(self, model_name):
    """
    Determine which prompt format type to use based on configuration.
    
    Args:
        model_name: String identifier for the model
        
    Returns:
        String: "instruction_completion", "special_token", or "json_message"
    """
    # First check if there's a specific format defined for this model
    format_key = f"prompt_format_{model_name}"
    
    if self.config_mgr.exists(format_key):
        return self.config_mgr.get(format_key)
    
    # If no explicit configuration, check if there's a format for the model family
    for prefix in ["openai", "groq", "anthropic", "phi", "mistral", "llama"]:
        if prefix in model_name.lower():
            family_format_key = f"prompt_format_{prefix}_default"
            if self.config_mgr.exists(family_format_key):
                return self.config_mgr.get(family_format_key)
    
    # Last resort: make a best guess
    return self._get_prompt_format_best_guess(model_name)

def _get_prompt_format_best_guess(self, model_name):
    """
    Make a best guess at the appropriate prompt format based on model name patterns.
    Only used as a fallback when no configuration is available.
    
    Args:
        model_name: String identifier for the model
        
    Returns:
        String: "instruction_completion", "special_token", or "json_message"
    """
    # Check patterns in the model name to infer the likely format
    model_name_lower = model_name.lower()
    
    # JSON Message format models (API-based services)
    if any(prefix in model_name_lower for prefix in ["openai:", "groq:", "anthropic:", "claude", "gpt"]):
        return "json_message"
    
    # Special token format models
    if any(token in model_name_lower for token in ["phi-", "phi_", "phi4"]):
        return "special_token"
    
    # Instruction completion format models
    if any(name in model_name_lower for name in ["mistral", "llama", "ministral"]):
        return "instruction_completion"
    
    # Default to the most widely supported format if we can't determine
    default_format = self.config_mgr.get("prompt_format_default", "json_message")
    return default_format
```

## Applying the Format

Once the format is determined, we apply the template from the appropriate source:

```python
def format_prompt(self, model_name, instructions, input_text, output=""):
    """
    Format a prompt according to the appropriate template for the model.
    Uses template files for consistent formatting across the system.
    
    Args:
        model_name: String identifier for the model
        instructions: System instructions or context
        input_text: User query or input
        output: Optional output for training examples
        
    Returns:
        Formatted prompt string in the appropriate structure for the model
    """
    format_type = self.get_prompt_format(model_name)
    
    if format_type == "instruction_completion":
        # Load template from file system based on format type
        template_path = os.path.join(self.TEMPLATE_DIR, "instruction_completion.txt")
        template = self._load_template(template_path)
        
        # Format with the provided values
        prompt = template.format(
            instructions=instructions,
            input=input_text,
            output=output if output else ""
        )
        return prompt
        
    elif format_type == "special_token":
        # For special token formats, load model-specific template
        # Extract model identifier for template selection
        model_id = self._extract_model_id(model_name)
        template_path = os.path.join(self.TEMPLATE_DIR, f"special_token_{model_id}.txt")
        
        if not os.path.exists(template_path):
            # Fallback to generic template if model-specific one doesn't exist
            template_path = os.path.join(self.TEMPLATE_DIR, "special_token_default.txt")
            
        template = self._load_template(template_path)
        prompt = template.format(
            instructions=instructions,
            input=input_text,
            output=output if output else ""
        )
        return prompt
        
    elif format_type == "json_message":
        # Create messages list
        messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": input_text}
        ]
        
        if output:
            messages.append({"role": "assistant", "content": output})
            
        # Convert to JSON string for consistent return type
        return json.dumps(messages)
    
    else:
        raise ValueError(f"Unknown prompt format type: {format_type}")

def _load_template(self, template_path):
    """
    Load a template file from the file system.
    
    Args:
        template_path: Path to the template file
        
    Returns:
        String template content
    """
    try:
        with open(template_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        raise ValueError(f"Template file not found: {template_path}")

def _extract_model_id(self, model_name):
    """
    Extract a clean model identifier from the model name for template selection.
    
    Args:
        model_name: String identifier for the model
        
    Returns:
        Clean model identifier for template matching
    """
    # Handle different formats: phi-4, llm_deepily_phi_4_14b, etc.
    # This would be expanded to handle all model naming patterns
    model_name_lower = model_name.lower()
    
    # Extract common model identifiers
    if "phi-4" in model_name_lower or "phi_4" in model_name_lower:
        return "phi_4"
    elif "phi-3" in model_name_lower:
        return "phi_3"
    elif "llama-3" in model_name_lower or "llama_3" in model_name_lower:
        return "llama_3"
    elif "mistral-7b" in model_name_lower:
        return "mistral_7b"
    # Add more model patterns as needed
    
    # Fallback: sanitize the model name by keeping alphanumeric and underscores
    import re
    return re.sub(r'[^a-z0-9_]', '_', model_name_lower)
```

## Template Examples

### Example Template Files

#### `instruction_completion.txt`
```
<s>[INST] {instructions}

{input} [/INST]
{output}</s>
```

#### `special_token_phi_4.txt`
```
<|system|>{instructions}<|end|>
<|user|>{input}<|end|>
<|assistant|>{output}<|end|>
```

#### `special_token_llama_3.txt`
```
<s> [INST] <<SYS>> {instructions} <</SYS>>

{input} [/INST] {output} </s>
```

## Configuration Example

Example configuration in the `gib-app.ini` file:

```ini
[LLM_FORMATS]
# Template directory
template_directory = src/conf/templates/

# Default format if not specified
prompt_format_default = json_message

# Model-specific prompt formats
prompt_format_llm_deepily_ministral_8b_2410 = instruction_completion
prompt_format_llm_deepily_phi_4_14b         = special_token
prompt_format_groq_llama_3_1_8b             = json_message

# Family defaults
prompt_format_openai_default                = json_message
prompt_format_groq_default                  = json_message
prompt_format_anthropic_default             = json_message
prompt_format_phi_default                   = special_token
prompt_format_mistral_default               = instruction_completion
prompt_format_llama_default                 = instruction_completion
```

This template-based approach provides several advantages:
1. Templates can be updated without code changes
2. Model-specific formats are isolated to their own files
3. All formats return strings, creating a consistent interface
4. New models can be added by creating new template files