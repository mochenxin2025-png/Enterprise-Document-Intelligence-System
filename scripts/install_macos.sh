#!/bin/bash
# EDIS macOS Install Script
set -e
echo "EDIS macOS Installer"

python3 --version || { echo "Python 3.10+ required"; exit 1; }

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "Created .venv"
fi

source .venv/bin/activate
pip install uv
uv pip install -r requirements-base.txt
uv pip install -r requirements-macos.txt

echo "EDIS installed. Run: .venv/bin/python main.py"
