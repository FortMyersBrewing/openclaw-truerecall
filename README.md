# TrueRecall: From Capture to Cross-Session Memory — A Build Report

*Built on top of [openclaw-true-recall-base](https://gitlab.com/mdkrush/openclaw-true-recall-base) by SpeedyFoxAi*

---

## What We Built

Starting from SpeedyFoxAi's TrueRecall Base (a real-time conversation capture system for OpenClaw), we extended it into a full cross-session memory system that gives OpenClaw agents persistent, searchable memory across every conversation context.

**The problem:** OpenClaw agents lose context between sessions. You solve a complex problem in a DM, then ask about it in a Slack channel — blank stare. The agent has no idea what happened in other sessions.

**The solution:** Every conversation turn gets embedded and stored in a vector database. Before each new prompt reaches the LLM, relevant memories from ALL past sessions are automatically retrieved and injected as context. The agent now "remembers" everything it's ever discussed, regardless of which channel or session it happened in.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Live Pipeline                      │
│                                                      │
│  Message → memory-qdrant plugin (before_agent_start) │
│         → Ollama embed → Qdrant search               │
│         → inject <relevant-memories> into prompt      │
│         → LLM responds with full cross-session context│
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│                 Capture Pipeline                     │
│                                                      │
│  Session JSONL → Multi-Agent Watcher (daemon)        │
│              → Ollama embed → Qdrant store            │
│                                                      │
│  Raw turns → Gems Extractor (daemon, Mercury 2)      │
│           → classify/extract → Qdrant store (curated) │
└─────────────────────────────────────────────────────┘
```

### Components

| Component | Role | Technology |
|-----------|------|-----------|
| **Qdrant** | Vector database | Docker container, localhost:6333 |
| **Ollama** | Local embeddings | snowflake-arctic-embed2 (1024-dim) |
| **Multi-Agent Watcher** | Capture all conversations in real-time | Python daemon (launchd) |
| **Gems Extractor** | Auto-curate important facts from conversations | Python daemon using Inception Mercury 2 |
| **memory-qdrant plugin** | Auto-recall before each prompt | OpenClaw TypeScript plugin |
| **recall.sh** | Manual CLI search tool | Bash + Python |

## What We Extended from TrueRecall Base

SpeedyFoxAi's original repo provided the foundation — a Python watcher that monitors session JSONL files and stores conversation turns in Qdrant. Here's what we added:

### 1. macOS Support
The original was built for Linux/systemd. We adapted it for macOS with:
- launchd plists instead of systemd service files
- Launcher shell scripts to handle Python venv activation + env vars
- Docker Desktop for Qdrant (instead of native Linux Docker)

### 2. Multi-Agent Watcher
The original watches one session directory. We rewrote it to:
- Monitor ALL agent session directories simultaneously
- Tag each memory with the source agent name
- Persist file positions across restarts (state file)
- Use zero external Python dependencies (urllib instead of requests)

### 3. Gems Extractor (New)
An LLM-powered curation layer that processes raw conversation turns and extracts standalone "gems" — concise facts worth remembering long-term.

- Uses Inception's Mercury 2 (diffusion-based LLM) for fast, cheap classification
- Categories: decision, preference, fact, solution, todo, architecture, credential, relationship
- JSON repair logic for handling Mercury's occasional truncated outputs
- Rate-limited to 180 req/min
- Gems are stored in the same Qdrant collection with `curated: true`
- Gems rank higher in search due to cleaner, more distilled content

### 4. memory-qdrant Plugin (New)
A native OpenClaw plugin that provides automatic cross-session memory:

- **Auto-Recall:** `before_agent_start` hook embeds the incoming message, searches Qdrant, and injects relevant memories as `<relevant-memories>` context before the LLM sees the prompt
- **Tools:** `memory_recall`, `memory_store`, `memory_forget` — same interface as the built-in memory-lancedb plugin
- **Security:** Prompt injection detection, XML escaping of memory content
- **Graceful degradation:** If Qdrant or Ollama are down, the agent continues normally without memories

### 5. Backfill Script
One-time script to process all historical session files into Qdrant. Deterministic point IDs make it idempotent (safe to re-run).

### 6. CLI Search Tool
`recall.sh` — standalone semantic search over all memories, filterable by agent and minimum score. Useful for debugging and manual lookups.

## Key Findings & Gotchas

### Vector Dimensions
The TrueRecall Base README states 768 dimensions for snowflake-arctic-embed2. **The actual output is 1024 dimensions.** This caused silent failures until we caught the mismatch.

### Mercury 2 Hidden Reasoning Tokens
Inception's Mercury 2 uses internal "reasoning tokens" that count against `max_tokens` but don't appear in the output. With `max_tokens: 300`, the model would burn 100-200 tokens on reasoning, leaving only 100 for the actual JSON response — causing truncated output.

**Fix:** Set `max_tokens` to 1000+ and use `reasoning_effort: "low"` for simple classification tasks.

### macOS Python Packaging
macOS 14+ blocks `pip install` on the system Python (PEP 668). Use a venv for any Python dependencies. We also eliminated the `requests` dependency in favor of `urllib` for the multi-agent watcher.

### launchd Environment Variables
Environment variables set in a launchd plist can be unreliable. Bake them into a launcher shell script instead. Also use `python -u` for unbuffered output, otherwise log files appear empty.

### Memory Injection Overhead
The auto-recall adds ~150-200 tokens per message (5 memories, truncated). This is ~3-4% overhead compared to the system prompt. The bigger cost is ~2-3 seconds latency from the Ollama embedding call.

## Results

- **16,600+ conversation turns** indexed from 88 historical sessions
- **Cross-session memory works** — ask about a topic discussed in a DM and get accurate context in a completely different Slack channel
- **Gems rank higher** in search than raw conversation turns due to cleaner content
- **Total infrastructure cost:** Free (all local — Qdrant Docker, Ollama, Mercury 2 at $0.25/1M tokens)
- **Backfill of entire history:** ~$3 in Mercury 2 API costs for gem extraction

## Repository

**GitHub:** [FortMyersBrewing/openclaw-truerecall](https://github.com/FortMyersBrewing/openclaw-truerecall)

Includes: multi-agent watcher, gems extractor, recall CLI, setup guide with macOS-specific instructions, and deployment documentation.

The memory-qdrant OpenClaw plugin is available separately at `~/.openclaw/extensions/memory-qdrant/`.

## Credits

- **SpeedyFoxAi** (mdkrush) — TrueRecall Base concept and original watcher implementation
- **Inception** — Mercury 2 diffusion LLM used for gems extraction
- Built with OpenClaw, Qdrant, and Ollama — all running locally on a Mac mini

---

## Quick Start

### Prerequisites
- macOS or Linux
- [Docker](https://docs.docker.com/get-docker/) (for Qdrant)
- [Ollama](https://ollama.com) (for local embeddings)
- [OpenClaw](https://github.com/openclaw/openclaw) agent running
- (Optional) [Inception API key](https://www.inceptionlabs.ai) for Gems extraction

### 1. Start Infrastructure

```bash
# Install & start Ollama
brew install ollama          # macOS
brew services start ollama
ollama pull snowflake-arctic-embed2

# Start Qdrant
docker run -d --name qdrant \
  -p 6333:6333 -p 6334:6334 \
  -v qdrant_storage:/qdrant/storage \
  --restart unless-stopped \
  qdrant/qdrant

# Create collection (1024 dimensions — NOT 768 as some docs claim)
curl -X PUT http://localhost:6333/collections/memories_tr \
  -H "Content-Type: application/json" \
  -d '{"vectors": {"size": 1024, "distance": "Cosine"}}'
```

### 2. Install Watcher

```bash
git clone https://github.com/FortMyersBrewing/openclaw-truerecall.git
cd openclaw-truerecall
python3 -m venv venv
./venv/bin/pip install requests

# Test it
./run-watcher.sh
# You should see: "🔍 TrueRecall Multi-Agent Watcher" and turns being captured
```

### 3. Install Plugin (Auto-Recall)

```bash
cp -r plugin/memory-qdrant ~/.openclaw/extensions/
cd ~/.openclaw/extensions/memory-qdrant && npm install
```

Add to your `openclaw.json`:
```json
{
  "plugins": {
    "allow": ["memory-qdrant"],
    "slots": { "memory": "memory-qdrant" },
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
          "minScore": 0.55,
          "maxResults": 5
        }
      }
    }
  }
}
```

Restart your gateway. Every new message now gets cross-session context injected automatically.

### 4. Install Gems (Optional)

```bash
export LLM_API_KEY="your-api-key"   # Inception, OpenAI, or any OpenAI-compatible provider
./gems/run-gems.sh --daemon
```

## Repo Structure

```
├── README.md                    # You are here
├── watcher/
│   ├── realtime_qdrant_watcher.py   # Original single-session watcher (upstream)
│   └── multi_agent_watcher.py       # Multi-agent watcher (our extension)
├── gems/
│   ├── extract_gems.py              # LLM-powered memory curation
│   └── run-gems.sh                  # Launcher with env var config
├── plugin/
│   └── memory-qdrant/               # OpenClaw auto-recall plugin
│       ├── index.ts
│       ├── config.ts
│       ├── openclaw.plugin.json
│       └── README.md
├── recall.py                    # CLI search tool
├── recall.sh                    # Launcher for recall CLI
├── run-watcher.sh               # Launcher for multi-agent watcher
└── docs/
    └── SETUP-REFERENCE.md       # Detailed setup guide with gotchas
```

## Based On

Built on top of [TrueRecall Base](https://gitlab.com/mdkrush/openclaw-true-recall-base) by SpeedyFoxAi. The original project provides the foundation — a Python watcher that captures OpenClaw conversations to Qdrant. We extended it with multi-agent support, automatic memory curation, a native OpenClaw plugin for auto-recall, and macOS compatibility.

## License

MIT

## Tuning Tips

### Memory Quality: minScore

The `minScore` setting in the plugin config controls the minimum cosine similarity threshold for memories to be injected. Higher = more relevant but fewer results, lower = more results but noisier.

| Value | Behavior |
|-------|----------|
| 0.4   | Very permissive — will include loosely related memories (may cause irrelevant context) |
| 0.55  | **Recommended** — good balance of relevance and coverage |
| 0.65+ | Strict — only highly relevant memories, may miss useful context |

If you're seeing unrelated memories being injected (e.g., a screenshot discussion triggering memories about a different screenshot), raise minScore. If important context is being missed, lower it.

### Filtering Noise

The watcher and gems extractor both have built-in filters to prevent junk from entering the database:

- **Watcher**: Skips messages under 5 words, media boilerplate (`[media attached:]`), and Slack file references
- **Gems extractor**: Requires min 50 chars + 5 words per turn, min 30 chars + 5 words per gem, and uses a strict prompt to skip conversational noise ("ok", "thanks", emoji-only messages)

### Pruning

If your database already has junk entries, use the prune script:
```bash
# Dry run first
python scripts/prune_short_memories.py --min-words 3 --dry-run

# Actually prune
python scripts/prune_short_memories.py --min-words 3
```
