#!/usr/bin/env python3
"""
Standalone diagnostic: reproduce the exact CRUD agent → Phi-4 14B call.

Tests both stream=False and stream=True to isolate empty response root cause.
No server required — calls vLLM endpoint directly.

Usage:
    export PYTHONPATH="/mnt/DATA01/include/www.deepily.ai/projects/lupin/src:$PYTHONPATH"
    export LUPIN_ROOT="/mnt/DATA01/include/www.deepily.ai/projects/lupin"
    python src/scripts/debug/debug_crud_llm_call.py
"""

import json
import sys
import os
import requests

# Bootstrap
lupin_root = os.environ.get( "LUPIN_ROOT", "/mnt/DATA01/include/www.deepily.ai/projects/lupin" )
src_path   = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

import cosa.utils.util as cu

# --- Config ---
ENDPOINT   = "http://192.168.1.21:3001/v1/completions"
MODEL_NAME = "kaitchup/Phi-4-AutoRound-GPTQ-4bit"
QUESTION   = "add buy milk to my grocery list"

# --- Build the exact same prompt as CrudForDataFramesAgent.__init__() ---
print( "=" * 80 )
print( "STEP 1: Building prompt (same as CrudForDataFramesAgent)" )
print( "=" * 80 )

from cosa.crud_for_dataframes.xml_models import CRUDIntent
from cosa.crud_for_dataframes.storage import DataFrameStorage

# Load the prompt template
template_path = cu.get_project_root() + "/src/conf/prompts/crud-for-dataframes/intent-extraction.txt"
with open( template_path, "r" ) as f:
    prompt_template = f.read()

# Build context (same as agent.__init__)
storage         = DataFrameStorage( user_email="ricardo.felipe.ruiz@gmail.com", base_path=cu.get_project_root() + "/io/dfs" )
available_lists = storage.get_all_lists_metadata()
intent_example  = CRUDIntent.get_example_for_template().to_xml( root_tag="intent" )

# Format available lists (same as agent._format_lists_for_prompt)
if available_lists:
    lists_str = "\n".join( [ f"- {m[ 'list_name' ]} ({m[ 'schema_type' ]}, {m[ 'item_count' ]} items)" for m in available_lists ] )
else:
    lists_str = "No lists created yet."

prompt = prompt_template.format(
    query           = QUESTION,
    available_lists = lists_str,
    intent_example  = intent_example
)

print( f"Prompt length: {len( prompt )} chars" )
print()
print( "--- FULL EXPANDED PROMPT ---" )
print( prompt )
print( "--- END PROMPT ---" )
print()

# --- Test 1: Non-streaming ---
print( "=" * 80 )
print( "STEP 2: Sending to vLLM (stream=False)" )
print( "=" * 80 )

payload = {
    "model"       : MODEL_NAME,
    "prompt"      : prompt,
    "max_tokens"  : 4096,
    "temperature" : 0.25,
    "top_p"       : 0.25,
    "stop"        : [ "</s>", "</stop>" ],
    "stream"      : False
}

headers = { "Content-Type": "application/json" }

try:
    response = requests.post( ENDPOINT, json=payload, headers=headers, timeout=60 )
    print( f"HTTP Status: {response.status_code}" )
    print( f"Response Headers: {dict( response.headers )}" )
    print( f"Raw Body Length: {len( response.text )}" )
    print( f"Raw Body (first 2000 chars):\n{response.text[ :2000 ]}" )
    print()

    if response.status_code == 200:
        result = response.json()
        text   = result.get( "choices", [ {} ] )[ 0 ].get( "text", "" )
        print( f"Parsed text length: {len( text )}" )
        print( f"Parsed text:\n{text}" )
    else:
        print( f"ERROR: Non-200 status code" )

except requests.exceptions.ConnectionError as e:
    print( f"CONNECTION ERROR: Cannot reach {ENDPOINT}" )
    print( f"  → Is the vLLM server running on 192.168.1.21:3001?" )
    print( f"  → Error: {e}" )

except requests.exceptions.Timeout:
    print( f"TIMEOUT: No response within 60s" )

except Exception as e:
    print( f"UNEXPECTED ERROR: {type( e ).__name__}: {e}" )

print()

# --- Test 2: Streaming ---
print( "=" * 80 )
print( "STEP 3: Sending to vLLM (stream=True)" )
print( "=" * 80 )

payload[ "stream" ] = True

try:
    response = requests.post( ENDPOINT, json=payload, headers=headers, timeout=60, stream=True )
    print( f"HTTP Status: {response.status_code}" )
    print( f"Response Headers: {dict( response.headers )}" )
    print()

    if response.status_code == 200:
        chunks    = []
        full_text = ""
        for i, line in enumerate( response.iter_lines() ):
            if line:
                decoded = line.decode( "utf-8" )
                if decoded.startswith( "data: " ):
                    data_str = decoded[ 6: ]
                    if data_str.strip() == "[DONE]":
                        print( f"  Chunk {i}: [DONE]" )
                        break
                    try:
                        chunk      = json.loads( data_str )
                        chunk_text = chunk.get( "choices", [ {} ] )[ 0 ].get( "text", "" )
                        full_text += chunk_text
                        chunks.append( chunk_text )
                        if i < 5 or i % 20 == 0:
                            print( f"  Chunk {i}: '{chunk_text}'" )
                    except json.JSONDecodeError:
                        print( f"  Chunk {i}: PARSE ERROR: {decoded[ :100 ]}" )
                else:
                    if i < 5:
                        print( f"  Line {i}: {decoded[ :100 ]}" )

        print( f"\nTotal chunks: {len( chunks )}" )
        print( f"Reconstructed text length: {len( full_text )}" )
        print( f"Reconstructed text:\n{full_text}" )
    else:
        print( f"ERROR: Non-200 status code" )
        print( f"Body: {response.text[ :1000 ]}" )

except requests.exceptions.ConnectionError as e:
    print( f"CONNECTION ERROR: Cannot reach {ENDPOINT}" )
    print( f"  → Error: {e}" )

except requests.exceptions.Timeout:
    print( f"TIMEOUT: No response within 60s" )

except Exception as e:
    print( f"UNEXPECTED ERROR: {type( e ).__name__}: {e}" )

print()
print( "=" * 80 )
print( "DIAGNOSTIC COMPLETE" )
print( "=" * 80 )
