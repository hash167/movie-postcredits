#!/bin/bash

# Daily batch processing script for Movie Post-Credits

# Set script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Activate virtual environment
source venv/bin/activate

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Run the batch processor
echo "Starting daily batch processing at $(date)"
python -m src.run_batch

# Check exit status
if [ $? -eq 0 ]; then
    echo "Batch processing completed successfully at $(date)"
else
    echo "Batch processing failed at $(date)"
    exit 1
fi

# Optional: Upload to storage
# python -m src.storage_uploader

echo "Daily run completed at $(date)"

