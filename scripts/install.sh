#!/bin/bash

# Movie Post-Credits Installation Script

echo "Installing Movie Post-Credits System..."

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null
then
    echo "Python 3 is required but not installed. Please install Python 3."
    exit 1
fi

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install requirements
echo "Installing dependencies..."
pip install -r requirements.txt

# Copy .env.example to .env if .env doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file from .env.example..."
    cp .env.example .env
    echo "Please edit .env file with your actual credentials."
fi

# Create exports directory if it doesn't exist
mkdir -p exports

echo "Installation complete!"
echo "Next steps:"
echo "1. Edit .env file with your API credentials"
echo "2. Start the database: docker-compose up -d db"
echo "3. Run the batch processor: python -m src.run_batch"

