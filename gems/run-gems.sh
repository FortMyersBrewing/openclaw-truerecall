#!/bin/bash
cd "$(dirname "$0")/.."
source venv/bin/activate
export QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
export OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
export LLM_API_URL="${LLM_API_URL:-https://api.inceptionlabs.ai/v1/chat/completions}"
export LLM_MODEL="${LLM_MODEL:-mercury-2}"
# LLM_API_KEY must be set in environment (e.g. via launchd plist or .env file)
if [ -z "$LLM_API_KEY" ]; then
    echo "Error: LLM_API_KEY environment variable is required" >&2
    exit 1
fi
exec python -u gems/extract_gems.py "$@"
