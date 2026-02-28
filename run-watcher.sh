#!/bin/bash
cd /Users/ava/projects/openclaw-true-recall-base
source venv/bin/activate
export QDRANT_URL="http://localhost:6333"
export OLLAMA_URL="http://localhost:11434"
export USER_ID="ava"
export AGENTS_DIR="/Users/ava/.openclaw/agents"
export STATE_FILE="/Users/ava/.openclaw/truerecall-state.json"
exec python -u watcher/multi_agent_watcher.py "$@"
