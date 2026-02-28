#!/usr/bin/env python3
"""
TrueRecall Multi-Agent Watcher
Monitors ALL OpenClaw agent session directories and stores to Qdrant.
Adapted from realtime_qdrant_watcher.py for multi-agent support.
"""

import os
import sys
import json
import time
import signal
import hashlib
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import re

# Config
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "memories_tr")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "snowflake-arctic-embed2")
USER_ID = os.getenv("USER_ID", "ava")
AGENTS_DIR = Path(os.getenv("AGENTS_DIR", os.path.expanduser("~/.openclaw/agents")))
STATE_FILE = Path(os.getenv("STATE_FILE", "/tmp/truerecall-state.json"))

running = True


def signal_handler(signum, frame):
    global running
    print(f"\nShutting down...", file=sys.stderr, flush=True)
    running = False


def get_embedding(text):
    try:
        data = json.dumps({"model": EMBEDDING_MODEL, "prompt": text}).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/embeddings",
            data=data,
            headers={"Content-Type": "application/json"}
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return resp["embedding"]
    except Exception as e:
        print(f"Embedding error: {e}", file=sys.stderr, flush=True)
        return None


def store_point(point_id, vector, payload):
    try:
        data = json.dumps({"points": [{"id": point_id, "vector": vector, "payload": payload}]}).encode()
        req = urllib.request.Request(
            f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points",
            data=data,
            headers={"Content-Type": "application/json"},
            method="PUT"
        )
        urllib.request.urlopen(req, timeout=30)
        return True
    except Exception as e:
        print(f"Qdrant error: {e}", file=sys.stderr, flush=True)
        return False


def clean_content(text):
    text = re.sub(r'Conversation info \(untrusted metadata\):\s*```json\s*\{[\s\S]*?\}\s*```', '', text)
    text = re.sub(r'\[thinking:[^\]]*\]', '', text)
    text = re.sub(r'\[\w{3} \d{4}-\d{2}-\d{2} \d{2}:\d{2} [A-Z]{3}\]', '', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'\n{3,}', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def extract_content(msg):
    content = ""
    if isinstance(msg.get("content"), list):
        for item in msg["content"]:
            if isinstance(item, dict) and "text" in item:
                content += item["text"]
    elif isinstance(msg.get("content"), str):
        content = msg["content"]
    return content


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except:
            pass
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def discover_sessions():
    """Find all JSONL session files across all agents."""
    sessions = []
    for agent_dir in AGENTS_DIR.iterdir():
        if not agent_dir.is_dir():
            continue
        sessions_dir = agent_dir / "sessions"
        if not sessions_dir.exists():
            continue
        agent_name = agent_dir.name
        for f in sessions_dir.glob("*.jsonl"):
            sessions.append((agent_name, f))
    return sessions


def process_file(agent_name, filepath, state):
    """Process new lines from a session file. Returns number of turns stored."""
    key = str(filepath)
    file_state = state.get(key, {"position": 0, "turn_count": 0})
    pos = file_state["position"]
    turn_count = file_state["turn_count"]
    
    current_size = filepath.stat().st_size
    if current_size <= pos:
        return 0
    
    stored = 0
    session_id = filepath.stem
    
    with open(filepath, "r") as f:
        f.seek(pos)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            if entry.get("type") != "message" or "message" not in entry:
                continue
            
            msg = entry["message"]
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            
            content = clean_content(extract_content(msg))
            if not content or len(content) < 5:
                continue
            
            turn_count += 1
            content_truncated = content[:2000]
            
            # Deterministic ID
            hash_bytes = hashlib.sha256(f"{agent_name}:{session_id}:turn:{turn_count}".encode()).digest()[:8]
            point_id = abs(int.from_bytes(hash_bytes, byteorder="big") % (2**63))
            
            vector = get_embedding(content_truncated)
            if vector is None:
                continue
            
            payload = {
                "user_id": USER_ID,
                "agent": agent_name,
                "role": role,
                "content": content_truncated,
                "turn": turn_count,
                "session_id": session_id,
                "timestamp": entry.get("timestamp", datetime.now(timezone.utc).isoformat()),
                "source": "multi-agent-watcher",
                "curated": False,
            }
            
            if store_point(point_id, vector, payload):
                stored += 1
                print(f"✅ [{agent_name}] turn {turn_count} ({role}) → Qdrant", flush=True)
        
        new_pos = f.tell()
    
    state[key] = {"position": new_pos, "turn_count": turn_count}
    return stored


def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print(f"🔍 TrueRecall Multi-Agent Watcher", flush=True)
    print(f"📍 Qdrant: {QDRANT_URL}/{QDRANT_COLLECTION}", flush=True)
    print(f"🧠 Ollama: {OLLAMA_URL}/{EMBEDDING_MODEL}", flush=True)
    print(f"👤 User: {USER_ID}", flush=True)
    print(f"📁 Agents: {AGENTS_DIR}", flush=True)
    print(f"💾 State: {STATE_FILE}", flush=True)
    print(flush=True)
    
    state = load_state()
    
    while running:
        sessions = discover_sessions()
        total_stored = 0
        
        for agent_name, filepath in sessions:
            if not running:
                break
            total_stored += process_file(agent_name, filepath, state)
        
        if total_stored > 0:
            save_state(state)
        
        # Poll every 2 seconds
        for _ in range(20):
            if not running:
                break
            time.sleep(0.1)
    
    save_state(state)
    print("State saved. Goodbye.", flush=True)


if __name__ == "__main__":
    main()
