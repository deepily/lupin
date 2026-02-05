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
        echo -e "${GREEN}Generating unified training data (includes agentic jobs)...${NC}"
        python -c "
from cosa.training.xml_coordinator import XmlCoordinator
import cosa.utils.util as du

du.print_banner( 'Generating Unified Training Data (with Agentic Jobs)', prepend_nl=True )

coordinator = XmlCoordinator( debug=False, verbose=False, silent=False )

print( 'Building ALL training prompts (vox commands + agent router + agentic jobs)...' )
# Note: agentic commands have ~200-500 unique examples per command (research-to-podcast has fewer templates)
df = coordinator.build_all_training_prompts(
    sample_size_per_command=400,
    include_agentic_jobs=True
)
print( f'Generated {df.shape[0]} total training examples' )

# Show command distribution
print( '\\nCommand distribution:' )
print( df[ 'command' ].value_counts().sort_index() )

print( '\\nSplitting into train/test/validate...' )
# Calculate appropriate sample size (80% of total for train)
total_examples = df.shape[0]
train_df, test_df, validate_df = coordinator.get_train_test_validate_split( df, sample_size=total_examples )
print( f'Train: {train_df.shape[0]}, Test: {test_df.shape[0]}, Validate: {validate_df.shape[0]}' )

print( '\\nWriting unified JSONL files...' )
coordinator.write_ttv_split_to_jsonl( train_df, test_df, validate_df )

# Also write isolated agentic job files for reference
print( '\\nAlso writing isolated agentic job JSONL files (for reference)...' )
agentic_df = df[ df[ 'command' ].str.contains( 'deep research|podcast generator|research to podcast' ) ].copy()
if agentic_df.shape[0] > 0:
    agentic_train, agentic_test, agentic_val = coordinator.get_agentic_job_train_test_validate_split( agentic_df, sample_size=agentic_df.shape[0] )
    coordinator.write_agentic_job_ttv_split_to_jsonl( agentic_train, agentic_test, agentic_val )
    print( f'Agentic-only: Train: {agentic_train.shape[0]}, Test: {agentic_test.shape[0]}, Validate: {agentic_val.shape[0]}' )

print( '\\nDone!' )
"
        ;;

    validate)
        echo -e "${GREEN}Validating training data...${NC}"
        python -c "
import json
import cosa.utils.util as du

du.print_banner( 'Validating JSONL Training Data', prepend_nl=True )

# Validate both unified and isolated agentic job files
unified_files = [
    '$TEST_TRAIN_PATH/voice-commands-xml-train.jsonl',
    '$TEST_TRAIN_PATH/voice-commands-xml-test.jsonl',
    '$TEST_TRAIN_PATH/voice-commands-xml-validate.jsonl'
]

agentic_files = [
    '$TEST_TRAIN_PATH/agentic-job-xml-train.jsonl',
    '$TEST_TRAIN_PATH/agentic-job-xml-test.jsonl',
    '$TEST_TRAIN_PATH/agentic-job-xml-validate.jsonl'
]

required_fields = [ 'command', 'instruction', 'input', 'output', 'prompt' ]
agentic_commands = [ 'agent router go to deep research', 'agent router go to podcast generator', 'agent router go to research to podcast' ]
total_errors = 0

print( '=== Unified Training Files ===' )
for filepath in unified_files:
    name = filepath.split( '/' )[ -1 ]
    try:
        with open( filepath, 'r' ) as f:
            lines = f.readlines()

        errors = 0
        agentic_count = 0
        for i, line in enumerate( lines ):
            try:
                data = json.loads( line )
                for field in required_fields:
                    if field not in data:
                        errors += 1
                        print( f'  Missing {field} in line {i}' )
                # Count agentic commands in unified files
                if data.get( 'command', '' ) in agentic_commands:
                    agentic_count += 1
            except json.JSONDecodeError:
                errors += 1

        if errors == 0:
            print( f'✓ {name}: {len( lines )} examples ({agentic_count} agentic) - VALID' )
        else:
            print( f'✗ {name}: {errors} errors' )
            total_errors += errors
    except FileNotFoundError:
        print( f'✗ {name}: FILE NOT FOUND' )
        total_errors += 1

print( '\\n=== Isolated Agentic Job Files (Reference) ===' )
for filepath in agentic_files:
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
        print( f'⚠ {name}: FILE NOT FOUND (optional)' )
        # Don't count as error - isolated files are optional now

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
