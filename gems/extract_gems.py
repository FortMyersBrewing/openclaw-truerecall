#!/usr/bin/env python3
"""
TrueRecall Gems Extractor
Processes conversation turns and extracts important "gems" using an LLM.
Provider-agnostic: works with any OpenAI-compatible chat completions API.
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

# LLM Config (any OpenAI-compatible provider)
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.inceptionlabs.ai/v1/chat/completions")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "mercury-2")

# Qdrant Config
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "memories_tr")

# Ollama Config (for embeddings)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "snowflake-arctic-embed2")

# Rate limiting
RATE_LIMIT_RPM = int(os.getenv("RATE_LIMIT_RPM", "180"))  # stay under 200
RATE_INTERVAL = 60.0 / RATE_LIMIT_RPM

# Gem categories
CATEGORIES = [
    "decision",      # choices made, things approved/rejected
    "preference",    # likes, dislikes, how they want things done
    "fact",          # personal info, names, dates, relationships
    "solution",      # how a problem was solved, what worked
    "todo",          # tasks, reminders, things to follow up on
    "architecture",  # technical decisions, system design
    "credential",    # API keys, passwords, endpoints (flag but don't store value)
    "relationship",  # people, roles, connections
]

SYSTEM_PROMPT = f"""You are a memory curator. Your job is to read a single conversation turn and decide if it contains information worth remembering long-term.

Extract "gems" — concise, standalone facts that would be useful to recall weeks or months later.

Categories: {', '.join(CATEGORIES)}

Rules:
- Only extract genuinely useful information. Most turns are NOT gems.
- Skip: greetings, acknowledgments, filler, status updates, routine tool output, heartbeat checks, short responses (OMG, yes, ok, lemme try, etc.)
- Skip: anything that is just conversational noise without lasting informational value
- Extract: decisions, preferences, personal facts, solutions to problems, architectural choices, important todos
- Each gem should be a complete, standalone sentence that makes sense without context
- If a turn contains a credential/secret, note that a credential exists but DO NOT include the actual value
- Return valid JSON only

Respond with EXACTLY this JSON format:
{{"gems": []}}

Or if there are gems:
{{"gems": [{{"text": "concise standalone fact", "category": "category_name"}}]}}

Maximum 3 gems per turn. Fewer is better."""

running = True


def signal_handler(signum, frame):
    global running
    running = False


def repair_json(s):
    """Try to repair truncated/malformed JSON from the LLM."""
    s = s.strip()
    if not s:
        return None
    # Try as-is first
    try:
        return json.loads(s)
    except:
        pass
    # Try closing unclosed strings and braces
    # Count unclosed braces/brackets
    import re
    # Remove trailing incomplete key-value pairs
    s = re.sub(r',\s*"[^"]*$', '', s)
    s = re.sub(r',\s*$', '', s)
    # Close any unclosed strings
    if s.count('"') % 2 == 1:
        s += '"'
    # Close arrays and objects
    opens = s.count('[') - s.count(']')
    for _ in range(opens):
        s += ']'
    opens = s.count('{') - s.count('}')
    for _ in range(opens):
        s += '}'
    try:
        return json.loads(s)
    except:
        return None


def llm_extract(content, role, max_retries=2):
    """Send a turn to the LLM for gem extraction with retry and JSON repair."""
    user_msg = f"[{role}]: {content}"

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg}
        ],
        "temperature": 0.5,
        "max_tokens": 1000,
        "reasoning_effort": "low",
        "response_format": {"type": "json_object"}
    }

    for attempt in range(max_retries + 1):
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            LLM_API_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LLM_API_KEY}"
            }
        )

        try:
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read())
            choice = result["choices"][0]
            content_str = choice["message"]["content"]
            finish_reason = choice.get("finish_reason", "")
            
            # If the model ran out of tokens, the JSON is likely truncated
            if finish_reason == "length":
                usage = result.get("usage", {})
                reasoning = usage.get("reasoning_tokens", 0)
                print(f"  ⚠️ Truncated response (reasoning used {reasoning} tokens)", file=sys.stderr, flush=True)

            # Try direct parse first
            try:
                parsed = json.loads(content_str)
                return parsed.get("gems", [])
            except json.JSONDecodeError:
                # Try repair
                parsed = repair_json(content_str)
                if parsed and isinstance(parsed, dict):
                    return parsed.get("gems", [])

                if attempt < max_retries:
                    time.sleep(RATE_INTERVAL)
                    continue
                return []
        except Exception as e:
            if attempt < max_retries:
                time.sleep(RATE_INTERVAL)
                continue
            return []


def get_embedding(text):
    """Get embedding from Ollama."""
    data = json.dumps({"model": EMBEDDING_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embeddings",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read())["embedding"]
    except Exception as e:
        print(f"  Embedding error: {e}", file=sys.stderr, flush=True)
        return None


def store_gem(gem_text, category, source_turn_id, source_agent, source_session, source_timestamp, user_id):
    """Embed and store a gem in Qdrant."""
    vector = get_embedding(gem_text)
    if vector is None:
        return False

    hash_bytes = hashlib.sha256(f"gem:{gem_text}".encode()).digest()[:8]
    point_id = abs(int.from_bytes(hash_bytes, byteorder="big") % (2**63))

    payload = {
        "user_id": user_id,
        "content": gem_text,
        "category": category,
        "source": "gems-extractor",
        "curated": True,
        "source_turn_id": source_turn_id,
        "source_agent": source_agent,
        "source_session": source_session,
        "timestamp": source_timestamp,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }

    data = json.dumps({"points": [{"id": point_id, "vector": vector, "payload": payload}]}).encode()
    req = urllib.request.Request(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points",
        data=data,
        headers={"Content-Type": "application/json"},
        method="PUT"
    )

    try:
        urllib.request.urlopen(req, timeout=30)
        return True
    except Exception as e:
        print(f"  Qdrant error: {e}", file=sys.stderr, flush=True)
        return False


def get_unprocessed_turns(limit=100, offset_id=None):
    """Fetch turns from Qdrant that haven't been gem-processed yet."""
    body = {
        "filter": {
            "must": [
                {"key": "curated", "match": {"value": False}},
            ],
            "must_not": [
                {"key": "gems_processed", "match": {"value": True}}
            ]
        },
        "limit": limit,
        "with_payload": True,
        "with_vector": False,
    }

    if offset_id:
        body["offset"] = offset_id

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/scroll",
        data=data,
        headers={"Content-Type": "application/json"}
    )

    try:
        result = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return result["result"]["points"], result["result"].get("next_page_offset")
    except Exception as e:
        print(f"Scroll error: {e}", file=sys.stderr, flush=True)
        return [], None


def mark_processed(point_id):
    """Mark a turn as gems-processed in Qdrant."""
    data = json.dumps({
        "points": [point_id],
        "payload": {"gems_processed": True}
    }).encode()
    req = urllib.request.Request(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/payload",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"  Mark error: {e}", file=sys.stderr, flush=True)


def process_batch(batch_size=100, user_id="ava", dry_run=False):
    """Process a batch of unprocessed turns."""
    turns, next_offset = get_unprocessed_turns(limit=batch_size)

    if not turns:
        return 0, 0

    gems_found = 0
    processed = 0

    for turn in turns:
        if not running:
            break

        point_id = turn["id"]
        payload = turn["payload"]
        content = payload.get("content", "")
        role = payload.get("role", "unknown")

        # Skip very short content (< 50 chars or < 5 words = not worth LLM processing)
        if len(content) < 50 or len(content.split()) < 5:
            if not dry_run:
                mark_processed(point_id)
            processed += 1
            continue

        # Rate limit
        time.sleep(RATE_INTERVAL)

        gems = llm_extract(content, role)

        if dry_run:
            if gems:
                for g in gems:
                    print(f"  💎 [{g.get('category', '?')}] {g.get('text', '?')}", flush=True)
            processed += 1
            continue

        for gem in gems:
            gem_text = gem.get("text", "").strip()
            category = gem.get("category", "fact")

            if not gem_text or len(gem_text) < 30 or len(gem_text.split()) < 5:
                continue

            if category not in CATEGORIES:
                category = "fact"

            if store_gem(
                gem_text, category,
                source_turn_id=point_id,
                source_agent=payload.get("agent", "unknown"),
                source_session=payload.get("session_id", ""),
                source_timestamp=payload.get("timestamp", ""),
                user_id=user_id
            ):
                gems_found += 1
                print(f"  💎 [{category}] {gem_text}", flush=True)

        mark_processed(point_id)
        processed += 1

    return processed, gems_found


def daemon_mode(user_id="ava", dry_run=False):
    """Run continuously, processing new turns as they arrive."""
    print(f"🔮 TrueRecall Gems Extractor — Daemon Mode", flush=True)
    print(f"🧠 LLM: {LLM_API_URL} / {LLM_MODEL}", flush=True)
    print(f"📍 Qdrant: {QDRANT_URL}/{QDRANT_COLLECTION}", flush=True)
    print(f"⏱️  Rate: {RATE_LIMIT_RPM} req/min", flush=True)
    if dry_run:
        print(f"🧪 DRY RUN MODE", flush=True)
    print(flush=True)

    total_processed = 0
    total_gems = 0

    while running:
        processed, gems = process_batch(batch_size=50, user_id=user_id, dry_run=dry_run)
        total_processed += processed
        total_gems += gems

        if processed > 0:
            print(f"📊 Batch: {processed} turns → {gems} gems (total: {total_processed} turns, {total_gems} gems)", flush=True)

        if processed == 0:
            # No unprocessed turns, wait before checking again
            for _ in range(300):  # 30 seconds
                if not running:
                    break
                time.sleep(0.1)

    print(f"\n🏁 Final: {total_processed} turns processed, {total_gems} gems extracted", flush=True)


def main():
    import argparse

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    parser = argparse.ArgumentParser(description="TrueRecall Gems Extractor")
    parser.add_argument("--daemon", "-d", action="store_true", help="Run continuously")
    parser.add_argument("--batch", "-b", type=int, default=50, help="Batch size (default: 50)")
    parser.add_argument("--user-id", "-u", default="ava", help="User ID")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Don't store gems, just print")

    args = parser.parse_args()

    if not LLM_API_KEY:
        print("Error: LLM_API_KEY environment variable is required", file=sys.stderr)
        sys.exit(1)

    if args.daemon:
        daemon_mode(user_id=args.user_id, dry_run=args.dry_run)
    else:
        processed, gems = process_batch(batch_size=args.batch, user_id=args.user_id, dry_run=args.dry_run)
        print(f"\n📊 Processed {processed} turns, extracted {gems} gems", flush=True)


if __name__ == "__main__":
    main()
