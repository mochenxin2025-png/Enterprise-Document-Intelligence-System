#!/bin/bash
# EDIS Linux Install Script
set -e
echo "EDIS Linux Installer"

# System deps for PaddleOCR
if command -v apt-get &>/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq libgomp1 libgl1
elif command -v yum &>/dev/null; then
    sudo yum install -y libgomp mesa-libGL
fi

python3 --version || { echo "Python 3.10+ required"; exit 1; }

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "Created .venv"
fi

source .venv/bin/activate
pip install uv
uv pip install -r requirements-base.txt
uv pip install -r requirements-linux.txt

echo "EDIS installed. Run: .venv/bin/python main.py"
