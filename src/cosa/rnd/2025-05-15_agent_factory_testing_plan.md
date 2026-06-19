# Agent Factory Testing Plan for v010 Migration

> **Created:** 2025-05-15

## Executive Summary

This plan outlines a comprehensive approach to testing all 9 migrated agents through the llm_client_factory.py main block. The goal is to verify proper integration of each agent with the v010 architecture and ensure they work correctly with the factory pattern.

## Agent Analysis for Factory Testing

### Agents Suitable for Direct Factory Testing (6)

1. **date_and_time_agent.py** - Can be tested with time/date queries
2. **math_agent.py** - Can be tested with mathematical calculations  
3. **weather_agent.py** - Can be tested with weather queries
4. **todo_list_agent.py** - Can be tested with todo list queries
5. **calendaring_agent.py** - Can be tested with calendar/event queries
6. **receptionist_agent.py** - Can be tested with general conversational queries

### Agents That Need Special Handling (3)

1. **confirmation_dialog.py** - Requires specific yes/no utterances
2. **bug_injector.py** - Requires existing code to inject bugs into
3. **iterative_debugging_agent.py** - Requires error messages and code files

## Proposed Implementation Plan

### 1. Create Test Data Structure

```python
agent_test_cases = [
    {
        "agent_name": "date_and_time_agent",
        "routing_command": "agent router go to date and time",
        "test_prompts": [
            "What time is it in New York?",
            "What's the current date?",
            "What time is it in Tokyo?"
        ]
    },
    {
        "agent_name": "math_agent",
        "routing_command": "agent router go to math",
        "test_prompts": [
            "What's 42 multiplied by 7?",
            "Calculate the square root of 256",
            "What's 15% of 200?"
        ]
    },
    {
        "agent_name": "weather_agent",
        "routing_command": "agent router go to weather",
        "test_prompts": [
            "What's the weather in London?",
            "Is it raining in Seattle?",
            "What's the temperature in Miami?"
        ]
    },
    {
        "agent_name": "todo_list_agent",
        "routing_command": "agent router go to todo list",
        "test_prompts": [
            "What's on my todo list?",
            "Show me today's tasks",
            "What do I need to do this week?"
        ]
    },
    {
        "agent_name": "calendaring_agent",
        "routing_command": "agent router go to calendar",
        "test_prompts": [
            "What events do I have today?",
            "Show me this week's meetings",
            "When is my next birthday party?"
        ]
    },
    {
        "agent_name": "receptionist_agent",
        "routing_command": "agent router go to receptionist", 
        "test_prompts": [
            "What's your name?",
            "How are you today?",
            "What did we talk about yesterday?"
        ]
    }
]
```

### 2. Enhanced Main Block Structure

```python
if __name__ == "__main__":
    # Initialize factory
    factory = LlmClientFactory()
    
    # Configuration for testing
    test_config = {
        "models_to_test": [
            LlmClient.PHI_4_14B,
            LlmClient.GROQ_LLAMA_3_1_8B,
            LlmClient.GOOGLE_GEMINI_1_5_FLASH,
            LlmClient.ANTHROPIC_CLAUDE_SONNET_3_5
        ],
        "debug": True,
        "verbose": True
    }
    
    # Results tracking
    test_results = []
    
    # Iterate through each agent
    for agent_test in agent_test_cases:
        agent_name = agent_test["agent_name"]
        routing_command = agent_test["routing_command"]
        
        print(f"\n=== Testing {agent_name} ===")
        
        # Get prompt template for agent
        template_key = f"prompt template for {routing_command}"
        prompt_template = load_agent_template(template_key)
        
        # Test each prompt for the agent
        for test_prompt in agent_test["test_prompts"]:
            for model in test_config["models_to_test"]:
                result = test_agent_with_model(
                    factory, model, agent_name, 
                    prompt_template, test_prompt
                )
                test_results.append(result)
    
    # Generate test report
    generate_test_report(test_results)
```

### 3. Special Agent Handling

For the three special agents that require unique testing approaches:

#### confirmation_dialog.py
```python
def test_confirmation_dialog(factory, models):
    """Test the confirmation dialog agent with yes/no utterances"""
    test_utterances = [
        ("Yes, please proceed.", True),
        ("No, don't do that.", False),
        ("I'm not sure...", None)  # Ambiguous
    ]
    
    results = []
    for model in models:
        agent = ConfirmationDialogue(model_name=model, debug=True)
        for utterance, expected in test_utterances:
            result = agent.confirmed(utterance)
            results.append({
                "agent": "confirmation_dialog",
                "model": model,
                "utterance": utterance,
                "expected": expected,
                "actual": result,
                "success": result == expected
            })
    
    return results
```

#### bug_injector.py
```python
def test_bug_injector(factory, models):
    """Test the bug injector agent with sample code"""
    test_code = [
        "def hello(name):",
        "    return f'Hello, {name}!'",
        "", 
        "greeting = hello('World')",
        "print(greeting)"
    ]
    
    results = []
    for model in models:
        injector = BugInjector(
            code=test_code.copy(),
            debug=True,
            verbose=True
        )
        
        # Run bug injection
        response = injector.run_prompt()
        
        # Verify bug was injected
        success = injector.prompt_response_dict["code"] != test_code
        
        results.append({
            "agent": "bug_injector",
            "model": model,
            "original_code": test_code,
            "modified_code": injector.prompt_response_dict["code"],
            "success": success
        })
    
    return results
```

#### iterative_debugging_agent.py
```python
def test_iterative_debugging(factory, models):
    """Test the iterative debugging agent with error scenarios"""
    # Create a test file with an error
    test_code = '''
def greeting():
    print("Hello World"
'''
    test_file = "/tmp/test_debug.py"
    with open(test_file, 'w') as f:
        f.write(test_code)
    
    error_message = '''
File "/tmp/test_debug.py", line 3
    print("Hello World"
         ^
SyntaxError: unexpected EOF while parsing
'''
    
    results = []
    for model in models:
        debugger = IterativeDebuggingAgent(
            error_message=error_message,
            path_to_code=test_file,
            debug=True,
            verbose=True
        )
        
        # Run debugging
        response = debugger.run_prompts()
        success = debugger.was_successfully_debugged()
        
        results.append({
            "agent": "iterative_debugging",
            "model": model,
            "error": error_message,
            "success": success
        })
    
    return results
```

## Testing Strategy

### 1. Phased Approach

- **Phase 1:** Test standard agents (6 agents) with direct factory integration
- **Phase 2:** Test special agents (3 agents) with custom handlers
- **Phase 3:** Run comprehensive cross-model compatibility tests

### 2. Multiple Model Testing

- Test each agent with at least 2-3 different models
- Include both local models (PHI, Ministral) and cloud models (Groq, OpenAI, Anthropic)
- Document model-specific behaviors or limitations

### 3. Result Validation

- Check for successful prompt completion without exceptions
- Verify response format matches agent expectations (XML tags, etc.)
- Track success/failure rates per agent/model combination
- Validate that responses are contextually appropriate

### 4. Error Handling

- Gracefully handle and log failures
- Continue testing even if individual agent/model combinations fail
- Collect detailed error information for debugging
- Categorize errors (API errors, format errors, logic errors)

## Success Metrics

### 1. Functional Success

- All agents execute without throwing unhandled exceptions
- Responses contain expected XML tags and structure
- Output is contextually appropriate to the input prompts
- Special agents produce expected behaviors (confirmations, bug injections, debugs)

### 2. Performance Metrics

- Response time per agent/model combination
- Memory usage patterns during execution
- API call success rates for cloud models
- Token usage efficiency

### 3. Compatibility Matrix

Document a comprehensive compatibility matrix showing:
- Which models work with which agents
- Any agent-specific model requirements
- Performance characteristics per combination
- Recommended model choices per agent type

## Implementation Timeline

1. **Week 1:** Implement test framework in llm_client_factory.py
2. **Week 1:** Create helper functions for special agent testing
3. **Week 2:** Run comprehensive tests across all agents
4. **Week 2:** Document results and create compatibility matrix
5. **Week 3:** Update agent documentation based on findings
6. **Week 3:** Create automated test suite for regression testing

## Expected Outcomes

1. **Comprehensive Test Suite:** A reusable test framework for all v010 agents
2. **Compatibility Documentation:** Clear understanding of which models work best with which agents
3. **Performance Baselines:** Established performance metrics for future optimization
4. **Bug Discovery:** Identification and documentation of any issues in the migration
5. **Best Practices:** Recommendations for agent/model pairings in production

## Risk Mitigation

1. **API Rate Limits:** Implement delays between cloud API calls
2. **Cost Management:** Monitor and limit cloud API usage during testing
3. **Environment Dependencies:** Document all required environment variables and configurations
4. **Test Isolation:** Ensure tests don't interfere with each other
5. **Reproducibility:** Create scripts to reproduce test environments

## Next Steps

1. Review and approve this testing plan
2. Assign resources for implementation
3. Set up test environments with necessary API keys
4. Begin Phase 1 implementation
5. Schedule regular progress reviews

This comprehensive testing approach will ensure all migrated agents are properly validated and documented, providing confidence in the v010 migration's success.