#!/usr/bin/env python3
"""
TrueRecall Search CLI
Usage: recall.py "search query" [--limit N] [--agent NAME] [--min-score 0.3]
"""

import os
import sys
import json
import urllib.request
import argparse

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "memories_tr")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "snowflake-arctic-embed2")


def get_embedding(text):
    data = json.dumps({"model": EMBEDDING_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embeddings",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read())["embedding"]


def search(query, limit=5, agent=None, min_score=0.0):
    vector = get_embedding(query)
    
    body = {
        "vector": vector,
        "limit": limit,
        "with_payload": True,
    }
    
    # Optional filter by agent
    if agent:
        body["filter"] = {
            "must": [{"key": "agent", "match": {"value": agent}}]
        }
    
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/search",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    results = json.loads(urllib.request.urlopen(req, timeout=30).read())["result"]
    
    filtered = [r for r in results if r["score"] >= min_score]
    return filtered


def main():
    parser = argparse.ArgumentParser(description="Search TrueRecall memories")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--limit", "-l", type=int, default=5, help="Max results (default: 5)")
    parser.add_argument("--agent", "-a", help="Filter by agent name")
    parser.add_argument("--min-score", "-m", type=float, default=0.3, help="Minimum similarity score (default: 0.3)")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    
    args = parser.parse_args()
    results = search(args.query, args.limit, args.agent, args.min_score)
    
    if args.json:
        output = []
        for r in results:
            output.append({
                "score": round(r["score"], 4),
                "agent": r["payload"].get("agent", "unknown"),
                "role": r["payload"]["role"],
                "content": r["payload"]["content"],
                "session_id": r["payload"].get("session_id", ""),
                "timestamp": r["payload"].get("timestamp", ""),
            })
        print(json.dumps(output, indent=2))
    else:
        if not results:
            print(f"No results above {args.min_score} similarity for: {args.query}")
            return
        
        for i, r in enumerate(results, 1):
            agent = r["payload"].get("agent", r["payload"].get("source_agent", "?"))
            role = r["payload"].get("role", "gem")
            score = r["score"]
            content = r["payload"]["content"][:200]
            ts = r["payload"].get("timestamp", "")[:19]
            print(f"[{i}] score={score:.3f} agent={agent} role={role} ts={ts}")
            print(f"    {content}")
            print()


if __name__ == "__main__":
    main()
