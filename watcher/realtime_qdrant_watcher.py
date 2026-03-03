#!/usr/bin/env python3
"""
TrueRecall v1 - Real-time Qdrant Watcher
Monitors OpenClaw sessions and stores to memories_tr instantly.

This is the CAPTURE component. For curation and injection, install v2.
"""

import os
import sys
import json
import time
import signal
import hashlib
import argparse
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

# Config
QDRANT_URL = os.getenv("QDRANT_URL", "http://10.0.0.40:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "memories_tr")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://10.0.0.10:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "snowflake-arctic-embed2")
USER_ID = os.getenv("USER_ID", "rob")

# Paths
SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", "/root/.openclaw/agents/main/sessions"))

# State
running = True
last_position = 0
current_file = None
turn_counter = 0


def signal_handler(signum, frame):
    global running
    print(f"\nReceived signal {signum}, shutting down...", file=sys.stderr)
    running = False


def get_embedding(text: str) -> List[float]:
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": text},
            timeout=30
        )
        response.raise_for_status()
        return response.json()["embedding"]
    except Exception as e:
        print(f"Error getting embedding: {e}", file=sys.stderr)
        return None


def clean_content(text: str) -> str:
    import re
    
    # Remove metadata JSON blocks
    text = re.sub(r'Conversation info \(untrusted metadata\):\s*```json\s*\{[\s\S]*?\}\s*```', '', text)
    
    # Remove thinking tags
    text = re.sub(r'\[thinking:[^\]]*\]', '', text)
    
    # Remove timestamp lines
    text = re.sub(r'\[\w{3} \d{4}-\d{2}-\d{2} \d{2}:\d{2} [A-Z]{3}\]', '', text)
    
    # Remove markdown tables
    text = re.sub(r'\|[^\n]*\|', '', text)
    text = re.sub(r'\|[-:]+\|', '', text)
    
    # Remove markdown formatting
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'```[\s\S]*?```', '', text)
    
    # Remove horizontal rules
    text = re.sub(r'---+', '', text)
    text = re.sub(r'\*\*\*+', '', text)
    
    # Remove excess whitespace
    text = re.sub(r'\n{3,}', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    
    return text.strip()


def store_to_qdrant(turn: Dict[str, Any], dry_run: bool = False) -> bool:
    if dry_run:
        print(f"[DRY RUN] Would store turn {turn['turn']} ({turn['role']}): {turn['content'][:60]}...")
        return True
    
    vector = get_embedding(turn['content'])
    if vector is None:
        print(f"Failed to get embedding for turn {turn['turn']}", file=sys.stderr)
        return False
    
    payload = {
        "user_id": turn.get('user_id', USER_ID),
        "role": turn['role'],
        "content": turn['content'],
        "turn": turn['turn'],
        "timestamp": turn.get('timestamp', datetime.now(timezone.utc).isoformat()),
        "date": datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        "source": "true-recall-base",
        "curated": False
    }
    
    # Generate deterministic ID
    turn_id = turn.get('turn', 0)
    hash_bytes = hashlib.sha256(f"{USER_ID}:turn:{turn_id}:{datetime.now().strftime('%H%M%S')}".encode()).digest()[:8]
    point_id = int.from_bytes(hash_bytes, byteorder='big') % (2**63)
    
    try:
        response = requests.put(
            f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points",
            json={
                "points": [{
                    "id": abs(point_id),
                    "vector": vector,
                    "payload": payload
                }]
            },
            timeout=30
        )
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Error writing to Qdrant: {e}", file=sys.stderr)
        return False


def get_current_session_file():
    if not SESSIONS_DIR.exists():
        return None
    
    files = list(SESSIONS_DIR.glob("*.jsonl"))
    if not files:
        return None
    
    return max(files, key=lambda p: p.stat().st_mtime)


def parse_turn(line: str, session_name: str) -> Optional[Dict[str, Any]]:
    global turn_counter
    
    try:
        entry = json.loads(line.strip())
    except json.JSONDecodeError:
        return None
    
    if entry.get('type') != 'message' or 'message' not in entry:
        return None
    
    msg = entry['message']
    role = msg.get('role')
    
    if role in ('toolResult', 'system', 'developer'):
        return None
    
    if role not in ('user', 'assistant'):
        return None
    
    content = ""
    if isinstance(msg.get('content'), list):
        for item in msg['content']:
            if isinstance(item, dict) and 'text' in item:
                content += item['text']
    elif isinstance(msg.get('content'), str):
        content = msg['content']
    
    if not content:
        return None
    
    content = clean_content(content)
    if not content or len(content) < 5:
        return None
    
    # Skip media attachment boilerplate and other noise
    if content.startswith("[media attached:") or content.startswith("[Slack file:"):
        return None
    if "To send an image back, prefer the message tool" in content:
        return None
    # Skip very short messages (< 5 words)
    if len(content.split()) < 5:
        return None
    
    turn_counter += 1
    
    return {
        'turn': turn_counter,
        'role': role,
        'content': content[:2000],
        'timestamp': entry.get('timestamp', datetime.now(timezone.utc).isoformat()),
        'user_id': USER_ID
    }


def process_new_lines(f, session_name: str, dry_run: bool = False):
    global last_position
    
    f.seek(last_position)
    
    for line in f:
        line = line.strip()
        if not line:
            continue
        
        turn = parse_turn(line, session_name)
        if turn:
            if store_to_qdrant(turn, dry_run):
                print(f"✅ Turn {turn['turn']} ({turn['role']}) → Qdrant")
    
    last_position = f.tell()


def watch_session(session_file: Path, dry_run: bool = False):
    global last_position, turn_counter
    
    session_name = session_file.name.replace('.jsonl', '')
    print(f"Watching session: {session_file.name}")
    
    try:
        with open(session_file, 'r') as f:
            for line in f:
                turn_counter += 1
        last_position = session_file.stat().st_size
        print(f"Session has {turn_counter} existing turns, starting from position {last_position}")
    except Exception as e:
        print(f"Warning: Could not read existing turns: {e}", file=sys.stderr)
        last_position = 0
    
    with open(session_file, 'r') as f:
        while running:
            if not session_file.exists():
                print("Session file removed, looking for new session...")
                return None
            
            process_new_lines(f, session_name, dry_run)
            time.sleep(0.1)
    
    return session_file


def watch_loop(dry_run: bool = False):
    global current_file, turn_counter
    
    while running:
        session_file = get_current_session_file()
        
        if session_file is None:
            print("No active session found, waiting...")
            time.sleep(1)
            continue
        
        if current_file != session_file:
            print(f"\nNew session detected: {session_file.name}")
            current_file = session_file
            turn_counter = 0
            last_position = 0
        
        result = watch_session(session_file, dry_run)
        
        if result is None:
            current_file = None
            time.sleep(0.5)


def main():
    global USER_ID
    
    parser = argparse.ArgumentParser(description="TrueRecall v1 - Real-time Memory Capture")
    parser.add_argument("--daemon", "-d", action="store_true", help="Run as daemon")
    parser.add_argument("--once", "-o", action="store_true", help="Process once then exit")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Don't write to Qdrant")
    parser.add_argument("--user-id", "-u", default=USER_ID, help=f"User ID (default: {USER_ID})")
    
    args = parser.parse_args()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    if args.user_id:
        USER_ID = args.user_id
    
    print(f"🔍 TrueRecall v1 - Real-time Memory Capture")
    print(f"📍 Qdrant: {QDRANT_URL}/{QDRANT_COLLECTION}")
    print(f"🧠 Ollama: {OLLAMA_URL}/{EMBEDDING_MODEL}")
    print(f"👤 User: {USER_ID}")
    print()
    
    if args.once:
        print("Running once...")
        session_file = get_current_session_file()
        if session_file:
            watch_session(session_file, args.dry_run)
        else:
            print("No session found")
    else:
        print("Running as daemon (Ctrl+C to stop)...")
        watch_loop(args.dry_run)


if __name__ == "__main__":
    main()
