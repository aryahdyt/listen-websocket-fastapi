#!/bin/bash
# Shell script for Linux/Mac

echo "Activating virtual environment..."
source venv/bin/activate

echo ""
echo "Starting Projection BPP Listener Service..."
echo ""

python run.py
