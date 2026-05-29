# LLM Prompt Format Analysis (2025-04-16)

## Overview
This document contains a comprehensive analysis of prompt formats used by various language models in the CoSA framework. The analysis distinguishes between models optimized for chat-style (message-based) interactions versus completion-style (instruction-based) interactions.

## Chat-Style Models

### OpenAI Models
- **GPT-4 Turbo** (gpt-4-turbo-2024-04-09)
- **GPT-3.5 Turbo** (gpt-3.5-turbo-0125)
- **GPT-01 Mini** (o1-mini-2024-09-12)
- **Format**: Messages with roles (system/user/assistant)
- **Implementation**: Uses chat completions API with structured JSON

### Groq Models
- **Mixtral 8x7B** (mixtral-8x7b-32768)
- **LLaMA 2/3/3.1 variants**
- **Format**: OpenAI-compatible chat format with role-based messages
- **Implementation**: `_query_llm_groq` method uses system/user message structure

### Google Models
- **Gemini 1.5 Pro** (gemini-1.5-pro-latest)
- **Gemini 1.5 Flash** (gemini-1.5-flash)
- **Format**: Google's native chat format
- **Implementation**: `_query_llm_google` method

### Anthropic Models
- **Claude 3.5 Sonnet** (claude-3-5-sonnet-latest)
- **Format**: Native chat format with system/user/assistant roles
- **Implementation**: Used with Agent wrapper through pydantic_ai

### Meta Models
- **Llama-3.2-3B-Instruct**
- **Format**: Messages structured as dictionaries with roles
- **Example Format**:
  ```python
  messages = [
      {"role": "system", "content": "You are a helpful assistant"},
      {"role": "user", "content": "Who are you?"}
  ]
  ```

### Microsoft Models
- **Phi-4-mini-instruct**
- **Format**: Special token-based chat format
- **Example Format**:
  ```
  <|system|>Insert System Message<|end|>
  <|user|>Insert User Message<|end|>
  <|assistant|>
  ```

## Completion-Style Models

### Mistral Models
- **Mistral-7B-Instruct-v0.2**
- **Format**: Instruction bracketing with `[INST]` and `[/INST]` tags
- **Example Format**:
  ```
  <s>[INST] What is your favourite condiment? [/INST]
  "Well, I'm quite partial to a good squeeze of fresh lemon juice..." </s>
  ```
- **Implementation**: Used with completions API

### Ministral Models
- **Ministral-8B-Instruct-2410**
- **Format**: Similar to Mistral with `[INST]` bracketing
- **Implementation**: Used with local completions endpoint and `completion_mode=True`

### Local Quantized Models
- **Qwen 2.5 Coder 32B**
- **Phi-4 14B**
- **Format**: Varies, but primarily used with completion API
- **Implementation**: Accessed through vLLM server completions endpoints

## Implementation Patterns

### API Switching in LlmClient
```python
def __init__(self,
    base_url: str = "http://192.168.1.21:3001/v1",
    model_name: str = "F00",
    completion_mode: bool = False,
    # ...other parameters...
):
    # ...
    if completion_mode:
        self.model = LlmCompletion(base_url=base_url, model_name=model_name, api_key=api_key, **generation_args)
    else:
        # For normal chat mode, use the Agent class
        if self.debug: print(f"Using Agent with model: 'openai:{model_name}'")
        self.model = Agent(f"openai:{model_name}", **generation_args)
```

### Prompt Templates
Each model's training configuration includes specific prompt templates designed for that model's preferred format:

#### Chat-Style Template (Llama-3.2, Phi-4)
```python
model_config = {
    "prompt_template": """<s>[INST]{instruction}

            {input}
            [/INST]
            {output}
            {last_tag}""",
    "last_tag_func": lambda output: "</s>" if output else ""
}
```

#### Completion-Style Template (Mistral)
```python
model_config = {
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
```

## Refactoring Approach
The codebase is transitioning to a more vendor-agnostic approach through:

1. **Unified Client Interface**: The `LlmClient` class abstracts away differences between chat and completion APIs
2. **Format Handling**: The `completion_mode` parameter determines which API to use
3. **Factory Pattern**: `LlmClientFactory` creates appropriate clients for each model
4. **Configuration-Driven**: Uses configuration manager to supply model-specific parameters

This approach enables smoother transitions between different models regardless of their native format preferences.