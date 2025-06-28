#!/bin/bash

# Set the vLLM API endpoint
VLLM_URL="http://127.0.0.1:3000/v1/chat/completions"

# Set the model path
MODEL_PATH="/mnt/DATA01/include/www.deepily.ai/projects/models/Ministral-8B-Instruct-2410-autoround-4-bits-sym.gptq/2025-01-24-at-20-48"

# Define the prompt file path
PROMPT_FILE="conf/prompts/vox-command-template-completion-mistral-8b.txt"

if [ -f "$PROMPT_FILE" ]; then
    PROMPT=$(jq -Rs . < "$PROMPT_FILE")  # Read from file safely
else
    echo "Error: No prompt found. Set PROMPT_CONTENT or ensure $PROMPT_FILE exists."
    exit 1
fi

# Construct JSON request using jq
JSON_PAYLOAD=$(jq -n \
    --arg model "$MODEL_PATH" \
    --arg content "$PROMPT" \
    '{
        model: $model,
        messages: [
            {role: "system", content: "You are a helpful AI assistant."},
            {role: "user", content: $content}
        ],
        max_tokens: 128
    }')

# Measure execution time in milliseconds
START_TIME=$(date +%s%3N)

# Send the request
RESPONSE=$(curl -s -o response.json -w "%{time_total}" -X POST "$VLLM_URL" \
    -H "Content-Type: application/json" \
    -d "$JSON_PAYLOAD")

END_TIME=$(date +%s%3N)

# Calculate elapsed time
ELAPSED_TIME=$((END_TIME - START_TIME))

# Print response
echo "Response saved in response.json"
echo "Total time taken: ${ELAPSED_TIME} ms"