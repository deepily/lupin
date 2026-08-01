#!/usr/bin/env python3
"""
Prompt Template Processor - Part of the io_models XML utilities.

Replaces hardcoded XML examples in prompt templates with dynamically
generated examples from Pydantic models using their get_example_for_template() methods.

This processor maps agent routing commands to their corresponding XML model classes
and generates template examples using the models' own example methods, eliminating
redundancy and ensuring single source of truth for XML structures.
"""

from cosa.agents.io_models.xml_models import (
    CodeBrainstormResponse, CalendarResponse, CodeResponse,
    IterativeDebuggingFullResponse, IterativeDebuggingMinimalistResponse,
    BugInjectionResponse, ReceptionistResponse, WeatherResponse,
    VoxCommandResponse, AgentRouterResponse, GistResponse, ConfirmationResponse,
    QualifierClassification, FuzzyFileMatchResponse
)
from cosa.agents.runtime_argument_expeditor.xml_models import ExpeditorResponse, ArgConfirmationResponse
from cosa.agents.notification_proxy.xml_models import ScriptMatcherResponse, BatchScriptMatcherResponse, VerificationResponse
from cosa.agents.dm_quality_judge.xml_models import DmQualityJudgeResponse
from cosa.agents.dm_quality_judge.xml_models_v2 import DmDirectnessExtraction, DmToneJudgement
from cosa.crud_for_dataframes.xml_models import CRUDIntent
from cosa.agents.calculator.xml_models import CalcIntent


class PromptTemplateProcessor:
    """
    Process prompt templates to inject model-generated XML examples.
    
    Uses the models' own get_example_for_template() methods to generate
    XML examples, ensuring consistency between models and templates.
    """
    
    # Clean mapping of routing commands to model classes
    MODEL_MAPPING = {
        'agent router go to math': CodeBrainstormResponse,
        'agent router go to datetime': CodeBrainstormResponse,
        'agent router go to calendar': CalendarResponse,
        'agent router go to todo': CodeResponse,
        'agent router go to debugger': IterativeDebuggingFullResponse,
        'agent router go to debugger minimalist': IterativeDebuggingMinimalistResponse,
        'agent router go to bug injector': BugInjectionResponse,
        'agent router go to receptionist': ReceptionistResponse,
        'agent router go to weather': WeatherResponse,
        # New mappings for utility prompts
        'agent router': AgentRouterResponse,
        'vox command': VoxCommandResponse,
        'gist generation': GistResponse,
        'confirmation dialog': ConfirmationResponse,
        'fuzzy file matching'          : FuzzyFileMatchResponse,
        'qualifier classification'     : QualifierClassification,
        'runtime argument expeditor'              : ExpeditorResponse,
        'argument confirmation'                   : ArgConfirmationResponse,
        'agent router go to crud for dataframes'  : CRUDIntent,
        'agent router go to calculator'            : CalcIntent,
        # Notification proxy models
        'notification proxy script matcher'        : ScriptMatcherResponse,
        'notification proxy batch script matcher'  : BatchScriptMatcherResponse,
        'notification proxy answer verifier'       : VerificationResponse,
        # DM Quality Judge (Phase 2 DM Verbosity Reduction)
        'dm quality judge'                         : DmQualityJudgeResponse,
        # DM Quality Judge v2 — one routing command per dimension, because v2 splits
        # the single v1 call into two so jargon has no path to the directness answer.
        'dm quality judge v2 directness'           : DmDirectnessExtraction,
        'dm quality judge v2 tone'                 : DmToneJudgement,
    }
    
    def __init__( self, debug: bool = False, verbose: bool = False ):
        """
        Initialize processor with debug options.
        
        Args:
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.debug = debug
        self.verbose = verbose
    
    def get_example_for_agent( self, routing_command: str ) -> str:
        """
        Get XML example for agent using model's own template method.
        
        Args:
            routing_command: Agent routing command (e.g., 'agent router go to math')
            
        Returns:
            XML string from model's get_example_for_template().to_xml() or None if not found
        """
        model_class = self.MODEL_MAPPING.get( routing_command )
        
        if model_class and hasattr( model_class, 'get_example_for_template' ):
            if self.debug:
                print( f"Generating XML example for: {routing_command}" )
            example = model_class.get_example_for_template()
            return example.to_xml()
        
        if self.verbose:
            print( f"No model mapping for: {routing_command}" )
        return None
    
    def process_template( self, template: str, routing_command: str ) -> str:
        """
        Process a prompt template, replacing markers with model-generated XML.
        
        Searches for {{PYDANTIC_XML_EXAMPLE}} markers and replaces them
        with XML generated from the appropriate Pydantic model's example method.
        
        Args:
            template: Raw template string with possible markers
            routing_command: Agent routing command to determine which model to use
            
        Returns:
            Processed template with XML examples injected
        """
        if '{{PYDANTIC_XML_EXAMPLE}}' not in template:
            if self.debug:
                print( "No XML markers found in template" )
            return template
        
        xml_example = self.get_example_for_agent( routing_command )
        
        if xml_example:
            # Append </stop> sentinel for vLLM stop token termination
            # This ensures LLM generates complete XML (including </response>) before stopping
            # The </stop> token is configured in model params as the stop sequence
            xml_with_sentinel = xml_example.rstrip() + "</stop>"
            processed = template.replace( '{{PYDANTIC_XML_EXAMPLE}}', xml_with_sentinel )
            if self.debug:
                print( f"✓ Replaced XML marker with {len(xml_with_sentinel)} chars of XML (includes </stop> sentinel)" )
            return processed
        else:
            if self.debug:
                print( f"⚠ No XML generator for {routing_command}, keeping template unchanged" )
            return template
    
    @classmethod
    def quick_smoke_test( cls, debug: bool = True ) -> bool:
        """
        Quick smoke test for PromptTemplateProcessor.
        
        Tests XML generation and template processing using models' own example methods.
        Follows CoSA convention for module-level testing.
        
        Args:
            debug: Enable debug output
            
        Returns:
            True if all tests pass
        """
        if debug:
            print( "Testing PromptTemplateProcessor..." )
        
        try:
            processor = cls( debug=False, verbose=False )
            
            # Test 1: Generate XML for each agent type
            if debug:
                print( "  - Testing XML generation using model example methods..." )
            agents_to_test = list( cls.MODEL_MAPPING.keys() )
            
            # Agents that use a non-standard root tag
            custom_root_tags = {
                'agent router go to crud for dataframes': 'intent',
            }

            for agent in agents_to_test:
                xml = processor.get_example_for_agent( agent )
                if xml:
                    root_tag = custom_root_tags.get( agent, 'response' )
                    assert f'<{root_tag}>' in xml, f"Missing <{root_tag}> tag for {agent}"
                    assert f'</{root_tag}>' in xml, f"Missing </{root_tag}> tag for {agent}"
                    if debug:
                        print( f"    ✓ {agent}: {len(xml)} chars (root: <{root_tag}>)" )
                else:
                    if debug:
                        print( f"    ✗ {agent}: No XML generated" )
                    return False
            
            # Test 2: Template processing with marker
            if debug:
                print( "  - Testing template processing..." )
            test_template = "Instructions here\\n{{PYDANTIC_XML_EXAMPLE}}\\nMore instructions"
            processed = processor.process_template( test_template, 'agent router go to math' )
            assert '{{PYDANTIC_XML_EXAMPLE}}' not in processed, "Marker not replaced"
            assert '<response>' in processed, "XML not injected"
            assert '<brainstorm>' in processed, "Math agent specific XML missing"
            assert '</stop>' in processed, "Sentinel marker not added"
            if debug:
                print( "    ✓ Template marker replacement works (with </stop> sentinel)" )
            
            # Test 3: Template without marker (should pass through)
            if debug:
                print( "  - Testing template without marker..." )
            unchanged_template = "No markers here"
            processed = processor.process_template( unchanged_template, 'agent router go to math' )
            assert processed == unchanged_template, "Template changed when it shouldn't"
            if debug:
                print( "    ✓ Template without marker unchanged" )
            
            # Test 4: Unknown agent type
            if debug:
                print( "  - Testing unknown agent handling..." )
            processed = processor.process_template( test_template, 'unknown agent' )
            assert processed == test_template, "Template changed for unknown agent"
            if debug:
                print( "    ✓ Unknown agent handled gracefully" )
            
            # Test 5: Verify models have the required methods
            if debug:
                print( "  - Testing model method availability..." )
            for routing_command, model_class in cls.MODEL_MAPPING.items():
                assert hasattr( model_class, 'get_example_for_template' ), f"{model_class} missing get_example_for_template method"
                example = model_class.get_example_for_template()
                assert hasattr( example, 'to_xml' ), f"{model_class} example missing to_xml method"
            if debug:
                print( "    ✓ All models have required methods" )
            
            if debug:
                print( "✓ PromptTemplateProcessor smoke test PASSED" )
            return True
            
        except Exception as e:
            if debug:
                print( f"✗ PromptTemplateProcessor smoke test FAILED: {e}" )
                import traceback
                traceback.print_exc()
            return False


def quick_smoke_test():
    """
    Module-level smoke test following CoSA convention.
    
    Returns:
        True if smoke test passes
    """
    return PromptTemplateProcessor.quick_smoke_test( debug=True )


if __name__ == "__main__":
    # Run smoke test when executed directly
    success = quick_smoke_test()
    exit( 0 if success else 1 )