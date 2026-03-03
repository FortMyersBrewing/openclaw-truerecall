#!/usr/bin/env python3
"""
Add memory-qdrant plugin config to openclaw.json
Run: python3 scripts/setup-plugin-config.py
"""
import json
import os
from pathlib import Path

config_path = Path.home() / ".openclaw" / "openclaw.json"

if not config_path.exists():
    print(f"ERROR: {config_path} not found")
    exit(1)

with open(config_path, "r") as f:
    config = json.load(f)

if "plugins" not in config:
    config["plugins"] = {}

# Ensure allow list includes memory-qdrant
allow = config["plugins"].get("allow", [])
if "memory-qdrant" not in allow:
    allow.append("memory-qdrant")
    config["plugins"]["allow"] = allow
    print("Added memory-qdrant to plugins.allow")

# Ensure slots.memory points to memory-qdrant
if "slots" not in config["plugins"]:
    config["plugins"]["slots"] = {}
if config["plugins"]["slots"].get("memory") != "memory-qdrant":
    config["plugins"]["slots"]["memory"] = "memory-qdrant"
    print("Set plugins.slots.memory = memory-qdrant")

# Ensure entries has memory-qdrant config
if "entries" not in config["plugins"]:
    config["plugins"]["entries"] = {}
if "memory-qdrant" not in config["plugins"]["entries"]:
    config["plugins"]["entries"]["memory-qdrant"] = {
        "enabled": True,
        "config": {
            "qdrantUrl": "http://localhost:6333",
            "ollamaUrl": "http://localhost:11434",
            "embeddingModel": "snowflake-arctic-embed2",
            "collection": "memories_tr",
            "vectorDim": 1024,
            "autoRecall": True,
            "autoCapture": False
        }
    }
    print("Added memory-qdrant entry with config")
else:
    print("memory-qdrant entry already exists")

# Backup and save
backup = str(config_path) + ".bak"
with open(backup, "w") as f:
    json.dump(json.loads(open(config_path).read()), f, indent=4)
print(f"Backup saved to {backup}")

with open(config_path, "w") as f:
    json.dump(config, f, indent=4)

print("\nDone! Now run: openclaw gateway restart")
