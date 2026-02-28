#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
export QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
export OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
exec python recall.py "$@"
