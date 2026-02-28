#!/bin/bash
cd /Users/ava/projects/openclaw-true-recall-base
export QDRANT_URL="http://localhost:6333"
export OLLAMA_URL="http://localhost:11434"
./venv/bin/python recall.py "$@"
