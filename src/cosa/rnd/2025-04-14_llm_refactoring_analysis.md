# Refactoring AgentBase to Use LlmClientFactory

## Overview

Currently, `AgentBase` uses the legacy `Llm_v0` class for LLM interactions, while a more modern `LlmClientFactory` and `LlmClient` implementation exists in the `v1` package. This document explores what would be required to update `AgentBase` and all its child classes to use the newer implementation.

## Current Implementation

### In AgentBase:

The interaction with `Llm_v0` happens primarily in the `run_prompt()` method:

```python
def run_prompt(self, model_name=None, temperature=0.5, top_p=0.25, top_k=10, max_new_tokens=1024, stop_sequences=None, include_raw_response=False):
    
    if model_name is not None: self.model_name = model_name
    
    llm = Llm_v0(config_mgr=self.config_mgr, model=self.model_name, debug=self.debug, verbose=self.verbose)
    response = llm.query_llm(prompt=self.prompt, temperature=temperature, top_p=top_p, top_k=top_k, max_new_tokens=max_new_tokens, stop_sequences=stop_sequences, debug=self.debug, verbose=self.verbose)
    
    # Parse XML-esque response
    self.prompt_response_dict = self._update_response_dictionary(response)
    
    # Add raw response if requested. This is useful for creating synthetic datasets
    if include_raw_response:
        self.prompt_response_dict["xml_response"] = response
        self.prompt_response_dict["last_question_asked"] = self.last_question_asked
    
    return self.prompt_response_dict
```

## Required Changes

### 1. Import Changes

**Current:**
```python
from cosa.agents.llm_v0 import Llm_v0
```

**Needed:**

```python
from cosa.agents.v010.llm_client_factory import LlmClientFactory
```

### 2. Method Updates

#### run_prompt() Method

**Current Implementation:**
- Creates a new `Llm_v0` instance each time
- Calls `query_llm()` with parameters
- Processes the response

**New Implementation Needed:**
- Get a client from `LlmClientFactory` using model_name
- Call the client's `run()` method
- Process the response the same way

The new implementation would look like:

```python
def run_prompt(self, model_name=None, temperature=0.5, top_p=0.25, top_k=10, max_new_tokens=1024, stop_sequences=None, include_raw_response=False):
    
    if model_name is not None: self.model_name = model_name
    
    # Get LLM client from factory
    llm_factory = LlmClientFactory()
    llm_client = llm_factory.get_client(self.model_name, debug=self.debug, verbose=self.verbose)
    
    # Call the client's run method
    response = llm_client.run(
        prompt=self.prompt,
        # Note: Parameter handling may differ between implementations
        # May need additional param mapping logic here
    )
    
    # Parse XML-esque response
    self.prompt_response_dict = self._update_response_dictionary(response)
    
    # Add raw response if requested
    if include_raw_response:
        self.prompt_response_dict["xml_response"] = response
        self.prompt_response_dict["last_question_asked"] = self.last_question_asked
    
    return self.prompt_response_dict
```

### 3. Model Name Management

**Current:**
- Models are accessed via dictionary in `_get_models()`
- Each model has a format like `"OpenAI/gpt-4-turbo"` or `"Groq/llama3-70b-8192"`
- `Llm_v0` handles this format internally

**Needed:**
- Update the model format to match what `LlmClientFactory` expects
- Models might need to be registered in config or defined in a way `LlmClientFactory` can understand
- Address the format differences between the two systems

### 4. Parameter Handling

**Current:**
- Parameters like `temperature`, `top_p`, `top_k`, etc. are passed directly to `Llm_v0.query_llm()`

**Needed:**
- Parameter conversion between the formats expected by `AgentBase` callers and what `LlmClient.run()` accepts
- May need a parameter mapping layer

### 5. Response Processing

**Current:**
- Assumes response is a string with XML tags
- Uses `_update_response_dictionary()` to extract tags into a dictionary

**Needed:**
- Verify `LlmClient.run()` returns a compatible text format
- May need to adapt response handling if the format differs

## Challenges and Considerations

### 1. Parameter Compatibility

`LlmClient.run()` has a simpler interface than `Llm_v0.query_llm()`. We need to ensure all the parameters currently used by `AgentBase` have equivalent functionality in the new implementation.

### 2. Model Format Transition

The format for referring to models may differ between implementations:
- `Llm_v0` uses formats like `"OpenAI/gpt-4-turbo"`
- `LlmClientFactory` might use different model identifiers

### 3. Backward Compatibility

Child classes of `AgentBase` might depend on specific behaviors of `Llm_v0`. We need to ensure the refactored code maintains all expected behaviors.

### 4. Configuration Management

Both systems interact with `ConfigurationManager`, but potentially in different ways:
- `Llm_v0` is initialized with a config_mgr
- `LlmClientFactory` creates its own config_mgr

### 5. Testing Strategy

A comprehensive testing strategy is needed:
1. Create unit tests for the new implementation
2. Compare outputs between old and new implementations
3. Test with various model configurations
4. Verify all child classes still work correctly

## Implementation Plan

1. **Create a Wrapper Class:**
   - Implement a transitional wrapper that maintains the same interface as `Llm_v0` but uses `LlmClientFactory` internally
   
2. **Gradual Migration:**
   - Update `AgentBase` to use the wrapper first
   - Test thoroughly with all child classes
   - Replace the wrapper with direct `LlmClientFactory` usage once stable

3. **Configuration Updates:**
   - Update model configuration to match the format needed by `LlmClientFactory`
   - Add any new configuration parameters required

4. **Child Class Review:**
   - Audit all child classes for any direct `Llm_v0` usage
   - Update those references to use the new approach

## Code Example

Example of a transitional wrapper approach:

```python
class LlmWrapper:
    """
    Transitional wrapper providing Llm_v0-compatible interface 
    while using LlmClientFactory internally.
    """
    
    def __init__(self, config_mgr=None, model=None, debug=False, verbose=False):
        self.config_mgr = config_mgr
        self.model_name = model
        self.debug = debug
        self.verbose = verbose
        self.factory = LlmClientFactory()
    
    def query_llm(self, prompt, temperature=0.5, top_p=0.25, top_k=10, 
                  max_new_tokens=1024, stop_sequences=None, debug=None, verbose=None):
        """
        Maintain the same interface as Llm_v0.query_llm but use LlmClientFactory.
        """
        if debug is None: debug = self.debug
        if verbose is None: verbose = self.verbose
        
        client = self.factory.get_client(self.model_name, debug=debug, verbose=verbose)
        
        # Parameter adaptation might be needed here
        # LlmClient.run() might not accept all the same parameters
        
        response = client.run(prompt)
        return response
```

## Conclusion

Migrating from `Llm_v0` to the newer `LlmClientFactory` implementation would provide several benefits:

1. **Unified Interface:** Consistent client interface across different providers
2. **Better Token Handling:** Improved token counting and metrics
3. **Vendor Abstraction:** More robust handling of different LLM vendors
4. **Performance Insights:** Better performance metrics via the new client

The transition requires careful planning and testing, but would result in more maintainable and robust code in the long term. A phased approach with a compatibility wrapper would minimize disruption to existing functionality.