#!/bin/bash
set -e

cd "$(dirname "$0")"

# Check for API key
if [ -z "$OPENROUTER_API_KEY" ]; then
    echo "ERROR: Set OPENROUTER_API_KEY environment variable first"
    echo "  export OPENROUTER_API_KEY=sk-or-..."
    exit 1
fi

# Create venv if needed
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "Installing dependencies..."
pip install -q -r backend/requirements.txt

echo ""
echo "========================================="
echo "  RepoBot running at http://localhost:8877"
echo "========================================="
echo ""

python backend/main.py
