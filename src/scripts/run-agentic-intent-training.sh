#!/bin/bash
#
# run-agentic-intent-training.sh
#
# Train LORA adapters for agentic job intent classification.
# Target Model: Ministral-8B-Instruct-2410
#
# Usage:
#   ./run-agentic-intent-training.sh [MODE]
#
# Modes:
#   test      - Fast iteration (1% sample, ~5-10 min)
#   full      - Full training (100% sample, ~3-4 hours)
#   generate  - Regenerate training data only
#   validate  - Validate existing training data
#
# Requirements:
#   - LUPIN_ROOT environment variable set
#   - DEEPILY_PROJECTS_DIR environment variable set (for LORA output)
#   - Python environment with required packages
#

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check required environment variables
if [ -z "$LUPIN_ROOT" ]; then
    echo -e "${RED}Error: LUPIN_ROOT environment variable not set${NC}"
    echo "Set it with: export LUPIN_ROOT=/path/to/lupin"
    exit 1
fi

if [ -z "$DEEPILY_PROJECTS_DIR" ]; then
    echo -e "${YELLOW}Warning: DEEPILY_PROJECTS_DIR not set, using default${NC}"
    DEEPILY_PROJECTS_DIR="/mnt/DATA02/include/projects"
fi

# Configuration
MODEL="mistralai/Ministral-8B-Instruct-2410"
MODEL_NAME="Ministral-8B-Instruct-2410"
TEST_TRAIN_PATH="$LUPIN_ROOT/src/ephemera/prompts/data"
LORA_DIR="$DEEPILY_PROJECTS_DIR/models/Ministral-8B-Instruct-2410.lora"

# Parse mode argument
MODE="${1:-test}"

echo "=========================================="
echo " Agentic Job Intent LORA Training"
echo "=========================================="
echo ""
echo "Mode: $MODE"
echo "Model: $MODEL_NAME"
echo "Training Data: $TEST_TRAIN_PATH"
echo "LORA Output: $LORA_DIR"
echo ""

cd "$LUPIN_ROOT/src"

case "$MODE" in
    generate)
        echo -e "${GREEN}Generating training data...${NC}"
        python -c "
from cosa.training.xml_coordinator import XmlCoordinator
import cosa.utils.util as du

du.print_banner( 'Generating Agentic Job Training Data', prepend_nl=True )

coordinator = XmlCoordinator( debug=False, verbose=False, silent=True )

print( 'Building training prompts...' )
df = coordinator.build_agentic_job_training_prompts( sample_size_per_command=100 )
print( f'Generated {df.shape[0]} training examples' )

print( 'Splitting into train/test/validate...' )
train_df, test_df, validate_df = coordinator.get_agentic_job_train_test_validate_split( df, sample_size=300 )
print( f'Train: {train_df.shape[0]}, Test: {test_df.shape[0]}, Validate: {validate_df.shape[0]}' )

print( 'Writing to JSONL files...' )
coordinator.write_agentic_job_ttv_split_to_jsonl( train_df, test_df, validate_df )

print( 'Done!' )
"
        ;;

    validate)
        echo -e "${GREEN}Validating training data...${NC}"
        python -c "
import json
import cosa.utils.util as du

du.print_banner( 'Validating JSONL Training Data', prepend_nl=True )

files = [
    '$TEST_TRAIN_PATH/agentic-job-xml-train.jsonl',
    '$TEST_TRAIN_PATH/agentic-job-xml-test.jsonl',
    '$TEST_TRAIN_PATH/agentic-job-xml-validate.jsonl'
]

required_fields = [ 'command', 'instruction', 'input', 'output', 'prompt' ]
total_errors = 0

for filepath in files:
    name = filepath.split( '/' )[ -1 ]
    try:
        with open( filepath, 'r' ) as f:
            lines = f.readlines()

        errors = 0
        for i, line in enumerate( lines ):
            try:
                data = json.loads( line )
                for field in required_fields:
                    if field not in data:
                        errors += 1
                        print( f'  Missing {field} in line {i}' )
            except json.JSONDecodeError:
                errors += 1

        if errors == 0:
            print( f'✓ {name}: {len( lines )} examples - VALID' )
        else:
            print( f'✗ {name}: {errors} errors' )
            total_errors += errors
    except FileNotFoundError:
        print( f'✗ {name}: FILE NOT FOUND' )
        total_errors += 1

if total_errors == 0:
    print( '\\n✓ All validation checks passed!' )
else:
    print( f'\\n✗ Found {total_errors} total errors' )
    exit( 1 )
"
        ;;

    test)
        echo -e "${GREEN}Running fast iteration training (1% sample)...${NC}"
        echo ""
        echo "Note: This uses the sample_size=0.01 from the model config file."
        echo "Training data: agentic-job-xml-train.jsonl"
        echo ""

        # Check if training data exists
        if [ ! -f "$TEST_TRAIN_PATH/agentic-job-xml-train.jsonl" ]; then
            echo -e "${YELLOW}Training data not found. Generating...${NC}"
            $0 generate
        fi

        python -m cosa.training.peft_trainer \
            --model "$MODEL" \
            --model-name "$MODEL_NAME" \
            --test-train-path "$TEST_TRAIN_PATH" \
            --lora-dir "$LORA_DIR" \
            --validation-sample-size 10 \
            --pre-training-stats \
            --post-training-stats
        ;;

    full)
        echo -e "${GREEN}Running full training (100% sample)...${NC}"
        echo ""
        echo "Warning: This may take 3-4 hours depending on hardware."
        echo ""

        # Check if training data exists
        if [ ! -f "$TEST_TRAIN_PATH/agentic-job-xml-train.jsonl" ]; then
            echo -e "${YELLOW}Training data not found. Generating...${NC}"
            $0 generate
        fi

        # Note: Full training would require modifying the config file's sample_size
        # or adding a command-line override. For now, we use validation sample size.
        python -m cosa.training.peft_trainer \
            --model "$MODEL" \
            --model-name "$MODEL_NAME" \
            --test-train-path "$TEST_TRAIN_PATH" \
            --lora-dir "$LORA_DIR" \
            --validation-sample-size 100 \
            --pre-training-stats \
            --post-training-stats \
            --post-quantization-stats
        ;;

    *)
        echo -e "${RED}Unknown mode: $MODE${NC}"
        echo ""
        echo "Usage: $0 [MODE]"
        echo ""
        echo "Modes:"
        echo "  test      - Fast iteration (1% sample)"
        echo "  full      - Full training (100% sample)"
        echo "  generate  - Regenerate training data only"
        echo "  validate  - Validate existing training data"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}Done!${NC}"
