# TrueRecall MCP Server

MCP (Model Context Protocol) server for the TrueRecall memory system. Provides semantic search, storage, and management of long-term memories via Qdrant vector database and Ollama embeddings.

## Prerequisites

- **Qdrant** running at `localhost:6333` with a collection named `memories_tr` (1024 dimensions)
- **Ollama** running at `localhost:11434` with the `snowflake-arctic-embed2` model pulled

## Setup

```bash
cd mcp-server
npm install
npm run build
```

## Tools

| Tool | Description |
|------|-------------|
| `memory_search` | Semantic search — embed query via Ollama, find similar memories in Qdrant |
| `memory_store` | Store a new memory with category and importance |
| `memory_recent` | Get the N most recent memories by timestamp |
| `memory_delete` | Delete a memory by point ID |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_URL` | `http://localhost:6333` | Qdrant server URL |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server URL |
| `EMBEDDING_MODEL` | `snowflake-arctic-embed2` | Ollama embedding model |
| `COLLECTION_NAME` | `memories_tr` | Qdrant collection name |

## Configure in Claude Code

Add to `~/.claude/mcp.json` (or project `.claude/mcp.json`):

```json
{
  "mcpServers": {
    "truerecall": {
      "command": "node",
      "args": ["/path/to/openclaw-truerecall/mcp-server/dist/index.js"],
      "env": {
        "QDRANT_URL": "http://localhost:6333",
        "OLLAMA_URL": "http://localhost:11434",
        "EMBEDDING_MODEL": "snowflake-arctic-embed2",
        "COLLECTION_NAME": "memories_tr"
      }
    }
  }
}
```

See `claude_mcp_config.json` for a ready-to-copy template.

## Run standalone

```bash
npm start
```

The server communicates over stdio using the MCP protocol.
