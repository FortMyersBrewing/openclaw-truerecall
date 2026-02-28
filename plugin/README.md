# memory-qdrant — OpenClaw Plugin

Drop-in replacement for the built-in `memory-lancedb` plugin. Uses Qdrant + Ollama for fully local vector memory with auto-recall.

## Install

```bash
# Copy plugin to OpenClaw extensions
cp -r memory-qdrant ~/.openclaw/extensions/

# Install dependency
cd ~/.openclaw/extensions/memory-qdrant && npm install
```

## Configure (openclaw.json)

```json
{
  "plugins": {
    "allow": ["memory-qdrant"],
    "slots": {
      "memory": "memory-qdrant"
    },
    "entries": {
      "memory-qdrant": {
        "enabled": true,
        "config": {
          "qdrantUrl": "http://localhost:6333",
          "ollamaUrl": "http://localhost:11434",
          "embeddingModel": "snowflake-arctic-embed2",
          "collection": "memories_tr",
          "vectorDim": 1024,
          "autoRecall": true,
          "autoCapture": false,
          "minScore": 0.4,
          "maxResults": 5
        }
      }
    }
  }
}
```

## Prerequisites
- Qdrant running (Docker or native)
- Ollama running with `snowflake-arctic-embed2` model pulled
- A `memories_tr` collection created with 1024-dim cosine vectors

## Features
- **Auto-Recall:** Injects relevant memories before each prompt via `before_agent_start` hook
- **Tools:** `memory_recall`, `memory_store`, `memory_forget`
- **Security:** Prompt injection detection, XML escaping
- **Graceful degradation:** If Qdrant/Ollama are down, agent continues normally
- **Zero external API dependencies:** Everything runs locally
