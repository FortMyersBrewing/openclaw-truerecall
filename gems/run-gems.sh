#!/bin/bash
cd /Users/ava/projects/openclaw-true-recall-base
source venv/bin/activate
export QDRANT_URL="http://localhost:6333"
export OLLAMA_URL="http://localhost:11434"
export LLM_API_URL="https://api.inceptionlabs.ai/v1/chat/completions"
export LLM_API_KEY="${LLM_API_KEY}"
export LLM_MODEL="mercury-2"
exec python -u gems/extract_gems.py "$@"
