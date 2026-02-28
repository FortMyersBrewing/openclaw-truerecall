#!/bin/bash
cd /Users/ava/projects/openclaw-true-recall-base
source venv/bin/activate
export QDRANT_URL="http://localhost:6333"
export OLLAMA_URL="http://localhost:11434"
export USER_ID="ava"
export SESSIONS_DIR="/Users/ava/.openclaw/agents/main/sessions"
exec python -u watcher/realtime_qdrant_watcher.py "$@"
