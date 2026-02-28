#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
export QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
export OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
export USER_ID="${USER_ID:-ava}"
export AGENTS_DIR="${AGENTS_DIR:-$HOME/.openclaw/agents}"
export STATE_FILE="${STATE_FILE:-$HOME/.openclaw/truerecall-state.json}"
exec python -u watcher/multi_agent_watcher.py "$@"
