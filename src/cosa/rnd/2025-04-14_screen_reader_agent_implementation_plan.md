# Screen Reader Agent Implementation Plan

## Overview

This document outlines the requirements and implementation steps for adding a new "screen reader" agent to the CoSA framework. The screen reader agent would provide text-to-speech and visual description capabilities to help users with accessibility needs.

## Required Changes

### 1. AgentBase Updates

The following methods in `agent_base.py` need to be updated to include the new routing destination:

```python
def _get_prompt_template_paths(self):
    return {
        # Existing entries...
        "agent router go to screen reader": self.config_mgr.get("agent_prompt_for_screen_reader"),
    }

def _get_models(self):
    return {
        # Existing entries...
        "agent router go to screen reader": self.config_mgr.get("agent_model_name_for_screen_reader"),
    }

def _get_serialization_topics(self):
    return {
        # Existing entries...
        "agent router go to screen reader": "screen-reader",
    }
```

### 2. Configuration Requirements

The following configuration entries need to be added to the appropriate config files:

```ini
[agent_settings]
agent_prompt_for_screen_reader=/src/conf/prompts/agents/screen-reader-agent.txt
agent_model_name_for_screen_reader=OpenAI/gpt-4-turbo
```

### 3. Prompt Template

Create a new prompt template file at `/src/conf/prompts/agents/screen-reader-agent.txt`:

```
You are a specialized screen reader agent designed to provide audio descriptions and text-to-speech services. Your primary functions include:

1. Reading text content aloud or providing text descriptions
2. Describing visual elements on the screen
3. Navigating content for users with visual impairments
4. Providing accessibility information about digital content

When describing content, be clear, concise, and focus on the most important elements first.

<example>
User: Describe this webpage to me.
Response: This webpage appears to be a news article. At the top is a header with the site name "News Daily" and a navigation menu with 5 items. Below is a large headline reading "Climate Report Shows Dramatic Changes" with a featured image of melting ice caps. The main content is divided into 3 paragraphs with a pull quote in the middle. On the right side is a sidebar with related articles and an advertisement.
</example>

For your response, use the following XML tags:
<summary>Brief overview of what's on screen</summary>
<description>Detailed description of the visual content</description>
<elements>List of key interactive elements</elements>
<content>The actual text content to be read</content>

User Question: {question}
```

### 4. Synthetic Training Data

Create a new file at `../ephemera/prompts/data/synthetic-data-agent-routing-screen-reader.txt` with content like:

```
Read this page to me.
Describe what's on my screen.
Narrate this document.
Can you explain what's visible on the screen?
What does the current page display?
Provide audio description of this webpage.
Read aloud the text from this window.
Convert this text to speech.
What content is shown on the current screen?
I need screen reading assistance.
Tell me what you can see on the monitor.
Verbalize the screen content.
Describe the elements on this page.
How would this screen appear to a blind person?
Give me an audio description of what's displayed.
Can you tell me what's happening on screen right now?
I'm visually impaired, please describe this page.
Read this document out loud.
Explain the layout of this webpage to me.
What does this image show?
Describe the chart that's displayed.
I can't see well, what's on my screen?
Please narrate what you see on the display.
Screen reader mode on.
Activate voice description.
```

### 5. ScreenReaderAgent Implementation

Create a new file `agents/screen_reader_agent.py`:

```python
import cosa.utils.util as du
import cosa.utils.util_xml as dux

from cosa.agents.agent_base import AgentBase
from cosa.agents.raw_output_formatter import RawOutputFormatter

class ScreenReaderAgent(AgentBase):
    """
    Agent responsible for converting text and visual content to speech or descriptions.
    
    Requires:
        - Access to the current screen or document content
        - Text-to-speech capabilities or descriptive language generation
        
    Ensures:
        - Accurately describes visual content
        - Reads text content aloud or provides text descriptions
        - Handles different content types appropriately
    """
    
    def __init__(self, df_path_key=None, question="", question_gist="", last_question_asked="", 
                 push_counter=-1, routing_command=None, debug=False, verbose=False, 
                 auto_debug=False, inject_bugs=False):
        
        super().__init__(df_path_key, question, question_gist, last_question_asked, 
                        push_counter, routing_command, debug, verbose, auto_debug, inject_bugs)
        
        # Define XML tags expected in the response
        self.xml_response_tag_names = ["summary", "description", "elements", "content", "code", "example"]
        
        # Set the prompt
        self.prompt = self.prompt_template.format(question=self.last_question_asked)
        
    def format_output(self):
        """
        Format the screen reader output in a conversational way.
        
        Requires:
            - prompt_response_dict containing XML response tags
            - code_response_dict containing output from any code execution
            
        Ensures:
            - Returns a conversational response appropriate for text-to-speech
            - Preserves important structural information
        """
        formatter = RawOutputFormatter(self.last_question_asked, 
                                      self.code_response_dict.get("output", ""),
                                      self.routing_command, debug=self.debug, verbose=self.verbose)
        self.answer_conversational = formatter.format_output()
        
        return self.answer_conversational
        
    # Screen reader-specific methods
    def describe_image(self, image_path):
        """
        Generate a description for an image.
        
        Requires:
            - image_path: Valid path to an image file
            
        Ensures:
            - Returns a textual description of the image content
        """
        # Future implementation could use a vision model API
        pass
    
    def read_text(self, text):
        """
        Convert text to speech or provide a reading of it.
        
        Requires:
            - text: String content to be read
            
        Ensures:
            - Returns a structured version of the text optimized for TTS
        """
        # Implementation could integrate with system TTS or cloud TTS APIs
        pass
```

### 6. XML Prompt Generator Updates

Update `training/xml_prompt_generator.py` to include screen reader commands:

```python
def _get_compound_agent_router_commands(self):
    """
    Get the compound commands for the agent router.
    """
    return {
        # Other commands...
        "agent router go to screen reader": [
            "read this screen",
            "describe what's on my screen",
            "narrate this document",
            "read this page aloud",
            "convert this text to speech",
            "screen reader mode",
            "activate screen reader",
            "tell me what you see on screen",
            "audio description please"
        ]
    }
```

## Integration with LLM Client Factory

When implementing the screen reader agent, we should use the new LlmClientFactory instead of the legacy Llm_v0 class. This aligns with our ongoing refactoring efforts.

Example of how the agent would use the new client in its `run_prompt` method (if overridden):

```python
def run_prompt(self, model_name=None, temperature=0.7, top_p=0.25, max_new_tokens=1024, 
              stop_sequences=None, include_raw_response=False):
    
    if model_name is not None: self.model_name = model_name
    
    # Get LLM client from factory (new approach)
    llm_factory = LlmClientFactory()
    llm_client = llm_factory.get_client(self.model_name, debug=self.debug, verbose=self.verbose)
    
    # Call the client's run method
    response = llm_client.run(
        prompt=self.prompt,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_new_tokens,
        stop=stop_sequences
    )
    
    # Parse XML response
    self.prompt_response_dict = self._update_response_dictionary(response)
    
    # Add raw response if requested
    if include_raw_response:
        self.prompt_response_dict["xml_response"] = response
        self.prompt_response_dict["last_question_asked"] = self.last_question_asked
    
    return self.prompt_response_dict
```

## Technical Considerations

1. **Accessing Screen Content**: A production implementation would need to capture screen content, possibly through browser extensions, OS accessibility APIs, or image capture.

2. **Text-to-Speech Integration**: Should support integration with OS-level or cloud TTS services.

3. **Multimodal Capabilities**: Ideally would handle both text and images for comprehensive accessibility support.

4. **Privacy Concerns**: Screen content may contain sensitive information, so proper privacy safeguards should be implemented.

5. **Performance**: Screen reading should be responsive with minimal latency for good user experience.

## Implementation Steps

1. Create the necessary configuration entries
2. Generate synthetic training data for router model
3. Create prompt template file
4. Implement the `ScreenReaderAgent` class
5. Update the AgentBase routing mechanisms
6. Update the XML prompt generator
7. Test with various screen content scenarios
8. Integrate with TTS capabilities

## Future Enhancements

- OCR capabilities for handling text within images
- Structural navigation ("go to next heading", "find form fields")
- Custom verbosity levels (brief vs. detailed descriptions)
- Support for describing dynamic content changes
- Integration with standard accessibility APIs (ARIA, etc.)